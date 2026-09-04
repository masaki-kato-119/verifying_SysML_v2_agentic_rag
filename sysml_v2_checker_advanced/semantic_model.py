"""Semantic Model の関係エッジ解決（拡張仕様書8章）。

parse_sysml_with_semantic_model()（antlr_transformer.py）が構築するノード
索引（stable_id/source_range/parent_id）に、specialization/feature_typing
等のエッジを追加する。

設計方針（2026-09-03、Phase 2着手時にユーザー確認の上変更）:
linter.py には一切手を入れない。SysMLAdvancedLinter().lint(ast) を通常通り
呼び出し、呼び出し後に残る linter.symbols/element_refs/packages（名前解決
専用の内部状態）を読み取り専用で参照して、参照文字列を実際のノードへ
解決する。linter.py側の `_collect_symbols` を公開関数へ切り出す当初案
（拡張仕様書8.3章の初版）は、17個以上のインスタンス属性と密結合しており
侵襲的すぎると判断し、より低リスクなこちらの方式に変更した。

対象とするエッジ種別（拡張仕様書8.1章）:
- specialization / subsetting / redefinition（inheritanceフィールド由来）
- feature_typing（type_name / type_names / type_spec.name フィールド由来）
- connection（connect_usage/connection_usage/binding_connectorの各end由来）
- satisfy / verify（satisfy_requirement_usage/verify_requirement_usageの
  `by`フィールド由来）
- transition（表現力強化Stage 2, Group A e1。transitionノードのsource/target
  由来。source省略時は`parent_id`＝囲むstate usage/state defを遷移元とする）
- succession（表現力強化Stage 2, Group A e2。succession/succession_usageの
  firstEnd/thenEnd（またはisFlow=True時のfromEnd/toEnd）由来。裸の
  first_stmt/then_stmt/guarded_then_stmt/else_stmt文は対象外――遷移元が
  「直前の兄弟文」という文脈に依存するため、意図的に未対応としている）
- flow（表現力強化Stage 2, Group A e3。flow_from_stmt/flow_short_stmtの
  from_port/to_port由来。`owner.port`形式のドット区切り参照はownerまでの
  解決に留める、`_resolve_reference`のフォールバックを参照）

各エッジは resolution_status（拡張仕様書8.2章）を持つ:
- "resolved"：このファイル内のノードへ解決できた
- "unresolved_external"：標準ライブラリ・importで持ち込まれた外部型・
  組み込み型（Real等）など、`linter.py`自身がエラーとして検出しない参照
- "unresolved_error"：上記いずれにも該当せず、`linter.py`が実際にエラーと
  して検出する（lintの指摘とここでの分類が矛盾しないよう、判定は
  `linter._is_unverifiable_reference`/`_find_type_in_symbols`/
  `_find_element_in_symbols` をそのまま呼んで揃えている）
"""

from typing import Dict, List, Optional, Set, Tuple

from .linter import SysMLAdvancedLinter

_INHERITANCE_EDGE_KIND = {
    "specializes": "specialization",
    "subsets": "subsetting",
    "redefines": "redefinition",
    # `::>`(References)はfeatureの参照的な型付けの一種として扱う。
    "references": "feature_typing",
}

# connect_usage/connection_usage/binding_connectorはノード種別ごとに
# end用フィールド名が異なる（2項形。n-ary形は共通の"ends"リストへ入る）。
_CONNECTOR_END_FIELD_NAMES = (
    "from_end", "to_end",       # connect_usage
    "firstEnd", "thenEnd",      # connection_usage
    "leftEnd", "rightEnd",      # binding_connector
)
# 表現力強化h3: 各end参照フィールドに対応する多重度フィールド名（無ければ
# キー自体が省略されるため`node.get(...)`はNoneを返す）。end名の並び順は
# `_CONNECTOR_END_FIELD_NAMES`と揃えている。
_CONNECTOR_END_MULTIPLICITY_FIELD_NAMES = (
    "from_multiplicity", "to_multiplicity",     # connect_usage
    "firstMultiplicity", "thenMultiplicity",    # connection_usage
    "leftMultiplicity", "rightMultiplicity",    # binding_connector
)
_CONNECTION_NODE_TYPES = {"connect_usage", "connection_usage", "binding_connector"}
_REQUIREMENT_EDGE_KIND = {
    "satisfy_requirement_usage": "satisfy",
    "verify_requirement_usage": "verify",
}

# 状態遷移図対応（表現力強化Stage 2, Group A e1）。transitionStmt/
# implicitTransitionStmt/initialTransitionMemberは、antlr_transformer.py側で
# いずれも共通の"type": "transition"形（source/targetフィールド）に正規化
# 済みのため、単一の判定で3種の文法をまとめて扱える。


def _multiplicity_label(multiplicity: Optional[Dict]) -> Optional[str]:
    """表現力強化h3: `_multiplicity_dict`形（antlr_transformer.py）の値を
    エッジラベル用の短い文字列（"4"や"1..4"等）へ変換する。上下限が無い
    （`ordered`/`nonunique`のみで`[...]`を伴わない等）場合はNone。"""
    if not isinstance(multiplicity, dict):
        return None
    size = multiplicity.get("size")
    if not isinstance(size, dict):
        return None
    min_value, max_value = size.get("min"), size.get("max")
    if min_value == max_value:
        return str(min_value)
    return f"{min_value}..{max_value}"


def _connector_end_references(node: Dict) -> List[Tuple[str, Optional[str]]]:
    """connect_usage/connection_usage/binding_connectorのend群から
    (参照文字列, 多重度ラベルまたはNone) の組を集める（表現力強化h3で
    多重度ラベルを追加。それ以前は参照文字列のみを返していた）。

    各endは visitConnectorEnd/visitConnectorEndPath が返す
    `{"type": "connector_end", "reference": str, ...}` 形（self.visit()経由の
    ため既にPhase 1で個別のノードとして登録済み）。多重度は同じendの前に
    付く別フィールド（例: binding_connectorの`leftMultiplicity`）として
    ノード自身に格納されているため、endフィールドと対になる多重度フィールド
    名を`_CONNECTOR_END_MULTIPLICITY_FIELD_NAMES`で引く。
    """
    references: List[Tuple[str, Optional[str]]] = []
    for field, mult_field in zip(_CONNECTOR_END_FIELD_NAMES, _CONNECTOR_END_MULTIPLICITY_FIELD_NAMES):
        end = node.get(field)
        if isinstance(end, dict) and end.get("reference"):
            references.append((end["reference"], _multiplicity_label(node.get(mult_field))))
    ends_list = node.get("ends")
    if isinstance(ends_list, list):
        # n-ary形（3つ以上のend）は多重度フィールドが無いため常にNone。
        for end in ends_list:
            if isinstance(end, dict) and end.get("reference"):
                references.append((end["reference"], None))
    return references


def _build_reverse_index(nodes: Dict[str, Dict]) -> Dict[int, str]:
    """id(node) -> stable_id の逆引き表を作る。

    nodes[stable_id]["node"] は ast 内の実物と同一オブジェクトである
    （拡張仕様書4章）ため、linter.symbols 等から得た解決先ノードの
    id(node) をキーにそのままstable_idを引ける。
    """
    return {id(entry["node"]): stable_id for stable_id, entry in nodes.items()}


def build_element_index(nodes: Dict[str, Dict]) -> Dict[int, Dict]:
    """`LintIssue.to_dict(element_index=...)` に渡す索引を作る（拡張仕様書9章）。

    `LintIssue.node` は、この `nodes`（`parse_sysml_with_semantic_model()`/
    `build_semantic_model()` が返したものと**同じ ast** から `lint_sysml(ast)`
    を呼んだ場合に限り、ここに登録されたノードと同一オブジェクトになる
    （id(node)での突合が成立する）。別々にパースした2つの ast を混ぜて
    使うと一致しないので注意。
    """
    return {
        id(entry["node"]): {"element_id": stable_id, "source_range": entry["source_range"]}
        for stable_id, entry in nodes.items()
    }


def _resolve_reference(reference: str, linter: SysMLAdvancedLinter) -> Optional[Dict]:
    """参照文字列(qualified name)を実ノードへ解決するベストエフォート探索。

    linter.py本体の `_find_element_in_symbols`（linter.py:557）と同じ
    一致判定（完全一致 or キーの末尾`::`セグメント一致）を、解決先ノードも
    返せるようにここで再実装している（本体はbool判定のみでノードを
    返さないため）。linter.symbols/element_refs のキーはpackage単位でのみ
    ネストする非完全階層な名前（例: `part_def Engine`配下の`attribute power`
    は`Vehicle::power`であり`Vehicle::Engine::power`ではない）であり、
    参照は多くの場合、宣言箇所からの相対的な短い名前（`Engine`等）で
    書かれる。そのため「参照文字列を変形して候補を作る」のではなく
    「シンボル表側のキーを末尾セグメントで比較する」必要がある。

    同じ短縮名が複数ファイル内に存在する場合（曖昧）は最初に見つかった
    ものを返す既知の簡易実装（_find_element_in_symbolsの真偽判定と同じ
    割り切り）。標準ライブラリ型・他ファイル由来の型はここでは解決できず
    None を返す（意図的な既知の制約。次段階のresolution_status 3値分類で
    区別する）。

    `owner.port`形式のドット区切りアクセス（flow文のfrom_port/to_port等、
    表現力強化Stage 2 Group A e3で追加）は、シンボル表にはowner側の名前
    だけが登録されておりポート部分までは個別に引けないため、最初の
    セグメント（owner名）だけで再試行する。要素レベルの関連としては
    ownerが分かれば十分に有用なため。既存の"::"区切り参照に"."を含む
    文字列は現れないため、他のエッジ種別の解決挙動には影響しない。
    """
    if not reference:
        return None
    short_name = reference.rsplit("::", 1)[-1] if "::" in reference else reference
    for table in (linter.symbols, linter.element_refs, linter.packages):
        for sym_name, node in table.items():
            if sym_name == reference or sym_name.split("::")[-1] == short_name:
                return node
    if "." in reference:
        return _resolve_reference(reference.split(".", 1)[0], linter)
    return None


def _classify_resolution(reference: str, target: Optional[Dict], linter: SysMLAdvancedLinter) -> str:
    """resolution_status（拡張仕様書8.2章）を判定する。

    lintのエラー判定と矛盾させないため、linter.py本体の判定メソッドを
    そのまま呼ぶ（再実装しない）。`_find_type_in_symbols`/
    `_find_element_in_symbols` は組み込み型（self.types）も含めて
    「型/要素として有効か」を判定するため、targetがNone（このファイル内に
    ASTノードが無い＝組み込み型や別ファイル解決）でも真になりうる。
    """
    if target is not None:
        return "resolved"
    if linter._is_unverifiable_reference(reference):
        return "unresolved_external"
    if linter._find_type_in_symbols(reference) or linter._find_element_in_symbols(reference):
        return "unresolved_external"
    return "unresolved_error"


def _make_edge(
    from_id: str,
    target: Optional[Dict],
    kind: str,
    reference_text: str,
    reverse_index: Dict[int, str],
    linter: SysMLAdvancedLinter,
) -> Dict:
    target_id = reverse_index.get(id(target)) if target is not None else None
    resolution_status = _classify_resolution(reference_text, target, linter)
    return {
        "from_id": from_id,
        "to_id": target_id,
        "kind": kind,
        "resolved": target_id is not None,
        "resolution_status": resolution_status,
        "reference_text": reference_text,
    }


def _format_expression(expr: object) -> str:
    """式ASTを人間可読な短い文字列へ変換する（h2: guard式のラベル表示用）。
    未知の式形は`"…"`にフォールバックする（ラベル表示は補助情報であり、
    完全な式を再現する必要はないため）。"""
    if not isinstance(expr, dict):
        return str(expr) if expr is not None else "…"
    expr_type = expr.get("type")
    if expr_type == "name_ref":
        return str(expr.get("reference", "?"))
    if expr_type == "literal":
        return str(expr.get("value"))
    if expr_type == "binary_expr":
        left = _format_expression(expr.get("left"))
        right = _format_expression(expr.get("right"))
        return f"{left} {expr.get('op', '?')} {right}"
    return "…"


def _format_trigger(trigger: Optional[Dict]) -> Optional[str]:
    """h2: transitionの`trigger`（accept節）をラベル用文字列へ変換する。"""
    if not isinstance(trigger, dict):
        return None
    if "reference" in trigger:
        return str(trigger["reference"])
    if "trigger_kind" in trigger:
        return str(trigger["trigger_kind"])
    return None


def _format_effect(effect: Optional[Dict]) -> Optional[str]:
    """h2: transitionの`effect`（do節）をラベル用文字列へ変換する。"""
    if not isinstance(effect, dict):
        return None
    if "action_reference" in effect:
        return str(effect["action_reference"])
    send = effect.get("send")
    if isinstance(send, dict):
        to = send.get("to")
        return f"send to {to}" if to else "send"
    return None


def _format_transition_label(
    trigger: Optional[Dict], guard: Optional[Dict], effect: Optional[Dict]
) -> Optional[str]:
    """h2: UML/SysML標準記法に近い`trigger [guard] / effect`形のラベルを
    組み立てる。いずれも無ければNone（ラベル無し、遷移矢印のみ）を返す。"""
    trigger_text = _format_trigger(trigger)
    guard_text = _format_expression(guard["expression"]) if isinstance(guard, dict) else None
    effect_text = _format_effect(effect)

    if trigger_text is None and guard_text is None and effect_text is None:
        return None

    label = trigger_text or ""
    if guard_text is not None:
        label = f"{label} [{guard_text}]" if label else f"[{guard_text}]"
    if effect_text is not None:
        label = f"{label} / {effect_text}" if label else f"/ {effect_text}"
    return label


def _make_transition_edge(
    parent_id: Optional[str],
    source_ref: Optional[str],
    target_ref: str,
    reverse_index: Dict[int, str],
    linter: SysMLAdvancedLinter,
    trigger: Optional[Dict] = None,
    guard: Optional[Dict] = None,
    effect: Optional[Dict] = None,
) -> Dict:
    """transitionは`_make_edge`の前提（宣言しているノード自身が関係の起点）と
    異なり、source/targetという2つの外部参照の間の関係を表す。source省略時
    （暗黙遷移）は、Semantic Modelの`parent_id`（このtransitionを直接囲む
    state usage/state def自身）を遷移元として使う（`_assign_semantic_ids`が
    ツリー上の親としてstable_idを既に確定させているため、追加の文脈受け渡しは
    不要）。"""
    if source_ref is not None:
        source_target = _resolve_reference(source_ref, linter)
        from_id = reverse_index.get(id(source_target)) if source_target is not None else None
        from_status = _classify_resolution(source_ref, source_target, linter)
    else:
        from_id = parent_id
        from_status = "resolved" if from_id is not None else "unresolved_error"

    target = _resolve_reference(target_ref, linter)
    to_id = reverse_index.get(id(target)) if target is not None else None
    to_status = _classify_resolution(target_ref, target, linter)

    resolved = from_id is not None and to_id is not None
    if resolved:
        resolution_status = "resolved"
    elif "unresolved_error" in (from_status, to_status):
        resolution_status = "unresolved_error"
    else:
        resolution_status = "unresolved_external"

    edge = {
        "from_id": from_id,
        "to_id": to_id,
        "kind": "transition",
        "resolved": resolved,
        "resolution_status": resolution_status,
        "reference_text": target_ref,
    }
    label = _format_transition_label(trigger, guard, effect)
    if label is not None:
        edge["label"] = label
    return edge


def _succession_end_reference(value) -> Optional[str]:
    """succession/succession_usageのfirstEnd/thenEnd(またはisFlow=True時の
    fromEnd/toEnd)から参照文字列を取り出す（表現力強化Stage 2, Group A e2）。
    isFlow=Falseの場合はconnectorEnd形（`{"reference": str}`、connection系
    エッジ抽出の`_connector_end_references`と同型）、isFlow=Trueの場合は
    素の参照文字列そのもの、という2つの異なるAST形状を吸収する。"""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict) and value.get("reference"):
        return value["reference"]
    return None


def _make_reference_pair_edge(
    from_ref: str, to_ref: str, kind: str, reverse_index: Dict[int, str], linter: SysMLAdvancedLinter
) -> Dict:
    """宣言しているノード自身ではなく、2つの外部参照(from_ref, to_ref)間の
    関係を表す種別（succession/flow）向けの汎用エッジ構築。`_make_edge`は
    宣言ノード自身が関係の起点であることを前提にしているため使えない。"""
    from_target = _resolve_reference(from_ref, linter)
    from_id = reverse_index.get(id(from_target)) if from_target is not None else None
    from_status = _classify_resolution(from_ref, from_target, linter)

    to_target = _resolve_reference(to_ref, linter)
    to_id = reverse_index.get(id(to_target)) if to_target is not None else None
    to_status = _classify_resolution(to_ref, to_target, linter)

    resolved = from_id is not None and to_id is not None
    if resolved:
        resolution_status = "resolved"
    elif "unresolved_error" in (from_status, to_status):
        resolution_status = "unresolved_error"
    else:
        resolution_status = "unresolved_external"

    return {
        "from_id": from_id,
        "to_id": to_id,
        "kind": kind,
        "resolved": resolved,
        "resolution_status": resolution_status,
        "reference_text": f"{from_ref} -> {to_ref}",
    }


def build_relation_edges(
    ast: Dict, nodes: Dict[str, Dict], known_external_types: Optional[Set[str]] = None
) -> List[Dict]:
    """Semantic Modelの関係エッジ（拡張仕様書8.1,8.2章）を構築する。

    Args:
        known_external_types: `lint_sysml`と同じ意味（他ファイル・import経由で
            実在する型名の集合）。省略時は単体ファイル動作。
    """
    linter = SysMLAdvancedLinter()
    linter.lint(ast, known_external_types=known_external_types)

    reverse_index = _build_reverse_index(nodes)
    edges: List[Dict] = []

    for stable_id, entry in nodes.items():
        node = entry["node"]

        inheritance = node.get("inheritance")
        if isinstance(inheritance, dict):
            bases = inheritance.get("bases") or (
                [inheritance["base"]] if inheritance.get("base") else []
            )
            kind = _INHERITANCE_EDGE_KIND.get(inheritance.get("kind"), inheritance.get("kind"))
            for base_ref in bases:
                target = _resolve_reference(base_ref, linter)
                edges.append(_make_edge(stable_id, target, kind, base_ref, reverse_index, linter))

        # 表現力強化h3: 型付け(feature_typing)の多重度（`part engines : Engine[1..4];`
        # のようにノード自身が持つ`multiplicity`）を、すべてのfeature_typingエッジに
        # ラベルとして添える（h2で確立した`edge["label"]`の配管をそのまま再利用）。
        typing_multiplicity_label = _multiplicity_label(node.get("multiplicity"))

        type_name = node.get("type_name")
        if isinstance(type_name, str) and type_name:
            target = _resolve_reference(type_name, linter)
            edge = _make_edge(stable_id, target, "feature_typing", type_name, reverse_index, linter)
            if typing_multiplicity_label is not None:
                edge["label"] = typing_multiplicity_label
            edges.append(edge)

        # type_names[0] は type_name と重複するため2件目以降のみ追加する
        # （multitype、antlr_transformer.pyの各visitXxxで共通の設計）。
        extra_type_names = node.get("type_names")
        if isinstance(extra_type_names, list):
            for extra_name in extra_type_names[1:]:
                target = _resolve_reference(extra_name, linter)
                edge = _make_edge(stable_id, target, "feature_typing", extra_name, reverse_index, linter)
                if typing_multiplicity_label is not None:
                    edge["label"] = typing_multiplicity_label
                edges.append(edge)

        type_spec = node.get("type_spec")
        if isinstance(type_spec, dict) and type_spec.get("name"):
            target = _resolve_reference(type_spec["name"], linter)
            edge = _make_edge(stable_id, target, "feature_typing", type_spec["name"], reverse_index, linter)
            if typing_multiplicity_label is not None:
                edge["label"] = typing_multiplicity_label
            edges.append(edge)

        node_type = node.get("type")

        if node_type in _CONNECTION_NODE_TYPES:
            # 表現力強化h3: 各endの多重度（例: binding_connectorの
            # leftMultiplicity/rightMultiplicity）を、そのendへ向かうconnection
            # エッジ自身のラベルとして添える（end毎に別々のエッジが既に存在する
            # ため、1本のエッジに1つの多重度がそのまま対応し、UMLの関連端点
            # 多重度表記と同じ見た目になる）。
            for reference, mult_label in _connector_end_references(node):
                target = _resolve_reference(reference, linter)
                edge = _make_edge(stable_id, target, "connection", reference, reverse_index, linter)
                if mult_label is not None:
                    edge["label"] = mult_label
                edges.append(edge)

        req_edge_kind = _REQUIREMENT_EDGE_KIND.get(node_type)
        if req_edge_kind is not None:
            by_ref = node.get("by")
            if isinstance(by_ref, str) and by_ref:
                target = _resolve_reference(by_ref, linter)
                edges.append(_make_edge(stable_id, target, req_edge_kind, by_ref, reverse_index, linter))

        if node_type == "transition":
            target_ref = node.get("target")
            if isinstance(target_ref, str) and target_ref:
                edges.append(
                    _make_transition_edge(
                        entry["parent_id"],
                        node.get("source"),
                        target_ref,
                        reverse_index,
                        linter,
                        trigger=node.get("trigger"),
                        guard=node.get("guard"),
                        effect=node.get("effect"),
                    )
                )

        if node_type in ("succession", "succession_usage"):
            if node.get("isFlow"):
                from_raw, to_raw = node.get("fromEnd"), node.get("toEnd")
            else:
                from_raw, to_raw = node.get("firstEnd"), node.get("thenEnd")
            from_ref = _succession_end_reference(from_raw)
            to_ref = _succession_end_reference(to_raw)
            if from_ref and to_ref:
                edges.append(_make_reference_pair_edge(from_ref, to_ref, "succession", reverse_index, linter))

        if node_type in ("flow_from_stmt", "flow_short_stmt"):
            from_ref = node.get("from_port")
            to_ref = node.get("to_port")
            if isinstance(from_ref, str) and from_ref and isinstance(to_ref, str) and to_ref:
                edges.append(_make_reference_pair_edge(from_ref, to_ref, "flow", reverse_index, linter))

    return edges


def build_semantic_model(text: str, known_external_types: Optional[Set[str]] = None):
    """parse_sysml_with_semantic_model() + 関係エッジ構築をまとめて行う。

    戻り値は (ast, semantic_model) のタプル。semantic_model は
    {"nodes": {...}, "root_id": ..., "edges": [...]} の形。
    ast がパースエラーの場合は edges も空リストで返す。
    """
    from .antlr_transformer import parse_sysml_with_semantic_model

    ast, model = parse_sysml_with_semantic_model(text)
    if ast.get("type") == "error":
        model["edges"] = []
        return ast, model

    model["edges"] = build_relation_edges(ast, model["nodes"], known_external_types=known_external_types)
    return ast, model


def semantic_model_to_json_dict(semantic_model: Dict) -> Dict:
    """semantic_model（{"nodes", "root_id", "edges"}）をJSON化可能なdictへ変換する（拡張仕様書10章）。

    各ノードの `"node"`（生のASTノードへのPython参照）はJSON化できないため除外し、
    代わりに `"children_ids"`（`parent_id`が自分と一致する他ノードのstable_id一覧）を
    computed fieldとして追加する。完全なノード内容（属性値等）が必要な場合は、
    `element_id` を既存の `get_ast_json` の出力と突き合わせて参照する想定
    （ast自体は既存ツールで既に取得可能なため、ここでは重複させない）。
    """
    children_by_parent: Dict[Optional[str], List[str]] = {}
    for stable_id, entry in semantic_model["nodes"].items():
        children_by_parent.setdefault(entry["parent_id"], []).append(stable_id)

    nodes_json = {}
    for stable_id, entry in semantic_model["nodes"].items():
        nodes_json[stable_id] = {
            "type": entry["type"],
            "name": entry["name"],
            "parent_id": entry["parent_id"],
            "source_range": entry["source_range"],
            "children_ids": children_by_parent.get(stable_id, []),
        }

    return {
        "root_id": semantic_model["root_id"],
        "nodes": nodes_json,
        "edges": semantic_model["edges"],
    }

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

各エッジは resolution_status（拡張仕様書8.2章）を持つ:
- "resolved"：このファイル内のノードへ解決できた
- "unresolved_external"：標準ライブラリ・importで持ち込まれた外部型・
  組み込み型（Real等）など、`linter.py`自身がエラーとして検出しない参照
- "unresolved_error"：上記いずれにも該当せず、`linter.py`が実際にエラーと
  して検出する（lintの指摘とここでの分類が矛盾しないよう、判定は
  `linter._is_unverifiable_reference`/`_find_type_in_symbols`/
  `_find_element_in_symbols` をそのまま呼んで揃えている）
"""

from typing import Dict, List, Optional, Set

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
_CONNECTION_NODE_TYPES = {"connect_usage", "connection_usage", "binding_connector"}
_REQUIREMENT_EDGE_KIND = {
    "satisfy_requirement_usage": "satisfy",
    "verify_requirement_usage": "verify",
}


def _connector_end_references(node: Dict) -> List[str]:
    """connect_usage/connection_usage/binding_connectorのend群から参照文字列を集める。

    各endは visitConnectorEnd/visitConnectorEndPath が返す
    `{"type": "connector_end", "reference": str, ...}` 形（self.visit()経由の
    ため既にPhase 1で個別のノードとして登録済み）。ここではそのdictの
    "reference"文字列だけを取り出し、connect_usage自身からの参照解決に使う。
    """
    references: List[str] = []
    for field in _CONNECTOR_END_FIELD_NAMES:
        end = node.get(field)
        if isinstance(end, dict) and end.get("reference"):
            references.append(end["reference"])
    ends_list = node.get("ends")
    if isinstance(ends_list, list):
        for end in ends_list:
            if isinstance(end, dict) and end.get("reference"):
                references.append(end["reference"])
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
    """
    if not reference:
        return None
    short_name = reference.rsplit("::", 1)[-1] if "::" in reference else reference
    for table in (linter.symbols, linter.element_refs, linter.packages):
        for sym_name, node in table.items():
            if sym_name == reference or sym_name.split("::")[-1] == short_name:
                return node
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

        type_name = node.get("type_name")
        if isinstance(type_name, str) and type_name:
            target = _resolve_reference(type_name, linter)
            edges.append(_make_edge(stable_id, target, "feature_typing", type_name, reverse_index, linter))

        # type_names[0] は type_name と重複するため2件目以降のみ追加する
        # （multitype、antlr_transformer.pyの各visitXxxで共通の設計）。
        extra_type_names = node.get("type_names")
        if isinstance(extra_type_names, list):
            for extra_name in extra_type_names[1:]:
                target = _resolve_reference(extra_name, linter)
                edges.append(_make_edge(stable_id, target, "feature_typing", extra_name, reverse_index, linter))

        type_spec = node.get("type_spec")
        if isinstance(type_spec, dict) and type_spec.get("name"):
            target = _resolve_reference(type_spec["name"], linter)
            edges.append(_make_edge(stable_id, target, "feature_typing", type_spec["name"], reverse_index, linter))

        node_type = node.get("type")

        if node_type in _CONNECTION_NODE_TYPES:
            for reference in _connector_end_references(node):
                target = _resolve_reference(reference, linter)
                edges.append(_make_edge(stable_id, target, "connection", reference, reverse_index, linter))

        req_edge_kind = _REQUIREMENT_EDGE_KIND.get(node_type)
        if req_edge_kind is not None:
            by_ref = node.get("by")
            if isinstance(by_ref, str) and by_ref:
                target = _resolve_reference(by_ref, linter)
                edges.append(_make_edge(stable_id, target, req_edge_kind, by_ref, reverse_index, linter))

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

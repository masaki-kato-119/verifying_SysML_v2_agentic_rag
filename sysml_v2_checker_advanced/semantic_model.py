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

現時点のスコープ（Phase 2 第1弾）:
- specialization / subsetting / redefinition（inheritanceフィールド由来）
- feature_typing（type_name / type_names / type_spec.name フィールド由来）
のみを対象とする。connection/satisfy/verify系エッジと、
resolved/unresolved_external/unresolved_errorの3値分類は次段階に回す。
解決できなかった参照は一律 resolved=False, to_id=None として扱う。
"""

from typing import Dict, List, Optional

from .linter import SysMLAdvancedLinter

_INHERITANCE_EDGE_KIND = {
    "specializes": "specialization",
    "subsets": "subsetting",
    "redefines": "redefinition",
    # `::>`(References)はfeatureの参照的な型付けの一種として扱う。
    "references": "feature_typing",
}


def _build_reverse_index(nodes: Dict[str, Dict]) -> Dict[int, str]:
    """id(node) -> stable_id の逆引き表を作る。

    nodes[stable_id]["node"] は ast 内の実物と同一オブジェクトである
    （拡張仕様書4章）ため、linter.symbols 等から得た解決先ノードの
    id(node) をキーにそのままstable_idを引ける。
    """
    return {id(entry["node"]): stable_id for stable_id, entry in nodes.items()}


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


def _make_edge(from_id: str, target: Optional[Dict], kind: str, reference_text: str, reverse_index: Dict[int, str]) -> Dict:
    target_id = reverse_index.get(id(target)) if target is not None else None
    return {
        "from_id": from_id,
        "to_id": target_id,
        "kind": kind,
        "resolved": target_id is not None,
        "reference_text": reference_text,
    }


def build_relation_edges(ast: Dict, nodes: Dict[str, Dict]) -> List[Dict]:
    """Semantic Modelの関係エッジ（拡張仕様書8.1章、Phase 2第1弾分）を構築する。"""
    linter = SysMLAdvancedLinter()
    linter.lint(ast)

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
                edges.append(_make_edge(stable_id, target, kind, base_ref, reverse_index))

        type_name = node.get("type_name")
        if isinstance(type_name, str) and type_name:
            target = _resolve_reference(type_name, linter)
            edges.append(_make_edge(stable_id, target, "feature_typing", type_name, reverse_index))

        # type_names[0] は type_name と重複するため2件目以降のみ追加する
        # （multitype、antlr_transformer.pyの各visitXxxで共通の設計）。
        extra_type_names = node.get("type_names")
        if isinstance(extra_type_names, list):
            for extra_name in extra_type_names[1:]:
                target = _resolve_reference(extra_name, linter)
                edges.append(_make_edge(stable_id, target, "feature_typing", extra_name, reverse_index))

        type_spec = node.get("type_spec")
        if isinstance(type_spec, dict) and type_spec.get("name"):
            target = _resolve_reference(type_spec["name"], linter)
            edges.append(_make_edge(stable_id, target, "feature_typing", type_spec["name"], reverse_index))

    return edges


def build_semantic_model(text: str):
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

    model["edges"] = build_relation_edges(ast, model["nodes"])
    return ast, model

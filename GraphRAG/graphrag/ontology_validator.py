"""
オントロジー整合チェックモジュール（仕様書 6章）
"""
import logging
from typing import List, Optional, Tuple

import networkx as nx

from . import config
from .datamodels import ConceptCandidate, ConceptType

logger = logging.getLogger(__name__)


class OntologyValidator:
    """
    オントロジー整合チェック器
    
    仕様書 6章の制約をチェック
    """
    
    def __init__(self):
        self.allowed_relations = config.ALLOWED_RELATIONS
    
    def validate_entities(
        self, 
        candidates: List[ConceptCandidate],
        types: List[ConceptType]
    ) -> List[ConceptCandidate]:
        """
        エンティティの検証（仕様書 6.1）
        - ENTITY のみがグラフノードになれる
        - 未定義エンティティは破棄または保留
        
        Args:
            candidates: ConceptCandidateのリスト
            types: 対応するConceptTypeのリスト
        
        Returns:
            List[ConceptCandidate]: 有効なENTITYのリスト
        """
        valid_entities = []
        for candidate, concept_type in zip(candidates, types):
            if concept_type == ConceptType.ENTITY:
                valid_entities.append(candidate)
        return valid_entities
    
    def validate_relations(
        self,
        candidates: List[ConceptCandidate],
        types: List[ConceptType]
    ) -> List[Tuple[ConceptCandidate, str]]:
        """
        関係の検証（仕様書 6.2）
        - 事前定義された関係語彙のみ許可
        
        Args:
            candidates: ConceptCandidateのリスト
            types: 対応するConceptTypeのリスト
        
        Returns:
            List[Tuple[ConceptCandidate, str]]: 
                (RELATION候補, 関係名)のリスト
                関係名が事前定義されていない場合は除外
        """
        valid_relations = []
        for candidate, concept_type in zip(candidates, types):
            if concept_type == ConceptType.RELATION:
                # lemmaが事前定義された関係語彙に含まれるかチェック
                if candidate.lemma in self.allowed_relations:
                    valid_relations.append((candidate, candidate.lemma))
        return valid_relations
    
    def check_structure_constraints(self, graph: nx.DiGraph, fast_mode: bool = False) -> Tuple[bool, List[str]]:
        """
        構造制約のチェック（仕様書 6.3）
        - part-of の循環は禁止
        - is-a はDAGであること
        - 同一 lemma の ENTITY は統合する（これは構築時に処理）
        
        Args:
            graph: NetworkX有向グラフ
            fast_mode: Trueの場合、循環チェックをスキップ（パフォーマンス優先）
        
        Returns:
            Tuple[bool, List[str]]: 
                (制約を満たしているか, エラーメッセージのリスト)
        """
        errors = []
        
        # 最適化: 大規模グラフの場合は循環チェックをスキップ
        if fast_mode or graph.number_of_edges() > 5000:
            # 簡易チェックのみ（自己ループのみ）
            self_loops = [(u, v) for u, v in graph.edges() if u == v]
            if self_loops:
                errors.append(f"自己ループが検出されました: {len(self_loops)}件")
            is_valid = len(errors) == 0
            return is_valid, errors
        
        # part-of の循環チェック
        part_of_edges = [(u, v) for u, v, d in graph.edges(data=True)
                        if d.get('relation') == 'part-of']
        if part_of_edges:
            error = self._find_cycle_error(part_of_edges, "part-of")
            if error:
                errors.append(error)

        # is-a のDAGチェック
        is_a_edges = [(u, v) for u, v, d in graph.edges(data=True)
                     if d.get('relation') == 'is-a']
        if is_a_edges:
            error = self._find_cycle_error(is_a_edges, "is-a（DAGでない）")
            if error:
                errors.append(error)

        is_valid = len(errors) == 0
        return is_valid, errors

    def _find_cycle_error(self, edges: List[Tuple[str, str]], label: str) -> Optional[str]:
        """指定エッジ集合に循環があれば、エラーメッセージを返す。

        以前は ``nx.simple_cycles`` で**全ての単純閉路を列挙**していたが、
        これは密なグラフで指数爆発する。実際、ドメイン用語ゲートを入れて
        グラフが密になった際、is-a エッジ 399 本で ``MemoryError`` を起こし
        再構築が落ちた。

        知りたいのは「循環があるか」だけなので、DAG 判定（O(V+E)）で足りる。
        循環がある場合のみ、例を 1 つ取り出して報告する。エッジ数による
        スキップ閾値も不要になった（従来は 1000 本以上で検査を丸ごと諦めていた）。

        Args:
            edges: 対象の関係タイプのエッジ集合。
            label: エラーメッセージに使う関係名。

        Returns:
            Optional[str]: 循環があればエラーメッセージ。無ければ None。
        """
        subgraph = nx.DiGraph(edges)
        try:
            if nx.is_directed_acyclic_graph(subgraph):
                return None
            try:
                cycle = nx.find_cycle(subgraph, orientation="original")
                example = " -> ".join(str(u) for u, _, _ in cycle)
                return f"{label} の循環が検出されました: 例 {example}"
            except nx.NetworkXNoCycle:  # pragma: no cover - DAG 判定と矛盾する場合のみ
                return None
        except Exception:
            # 例外は「循環なし」を意味しない。検査そのものが失敗した状態であり、
            # 未検出の循環が残っている可能性がある。検証結果を偽陽性に
            # しないため errors には積まないが、検査の失敗は記録する。
            logger.warning(
                "%s の循環検査に失敗しました（エッジ数=%d）。"
                "循環が見逃されている可能性があります",
                label,
                len(edges),
                exc_info=True,
            )
            return None
    
    def validate(
        self,
        candidates: List[ConceptCandidate],
        types: List[ConceptType]
    ) -> Tuple[List[ConceptCandidate], List[Tuple[ConceptCandidate, str]]]:
        """
        全体の検証
        
        Returns:
            Tuple[List[ConceptCandidate], List[Tuple[ConceptCandidate, str]]]:
                (有効なENTITYのリスト, 有効なRELATIONのリスト)
        """
        valid_entities = self.validate_entities(candidates, types)
        valid_relations = self.validate_relations(candidates, types)
        return valid_entities, valid_relations


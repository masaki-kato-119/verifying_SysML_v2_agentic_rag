"""軽量GraphRAG用のグラフストア。

目的:
- チャンク間の「関係性」を軽量に保持し、検索時に近傍チャンクを追加/優先するための基盤。
- まずは最小実装として「同一ファイル内の隣接チャンク（chunk_indexの前後）」を表現する。

設計:
- networkx の DiGraph を使用（将来、relation_typeや重みを追加しやすい）。
- 永続化はオプション（pickle）。
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import networkx as nx


@dataclass(frozen=True)
class Neighbor:
    """近傍ノード情報。

    Attributes:
        chunk_id: 近傍チャンクのID。
        distance: 起点からの距離（エッジ数、hop数）。
        relation: 関係性の種類（例: "next", "prev"）。Noneの場合は未設定。
    """

    chunk_id: str
    distance: int
    relation: Optional[str] = None


class GraphStore:
    """軽量なグラフストア（GraphRAG用）。

    チャンク間の「関係性」を networkx の DiGraph で管理し、
    検索時に近傍チャンクを追加/優先するための基盤を提供します。

    現在の実装:
    - 同一ファイル内の隣接チャンク（chunk_indexの前後）を `next/prev` エッジとして表現
    - BFSによる近傍探索（距離つき）
    - pickleによる永続化（オプション）

    将来の拡張:
    - LLMによる関係抽出（依存関係、因果関係など）
    - より複雑な関係性の表現
    - 重み付きエッジの活用

    Attributes:
        _persist_path: グラフの永続化パス（pickle形式）。Noneの場合は永続化しない。
        _graph: networkx の DiGraph インスタンス。
    """

    def __init__(self, *, persist_path: Optional[Path] = None) -> None:
        """GraphStoreを初期化する。

        Args:
            persist_path: グラフの永続化パス（pickle形式）。
                Noneの場合は永続化しない。
                文字列が渡された場合はPathオブジェクトに変換します。
                指定したパスに既存のグラフがある場合は自動的にロードします。
                壊れたpickle等でロードに失敗した場合は空のグラフで開始します（Graphは補助情報のため）。
        """
        if persist_path is not None and isinstance(persist_path, str):
            persist_path = Path(persist_path)
        self._persist_path = persist_path
        self._graph: nx.DiGraph = nx.DiGraph()

        if self._persist_path is not None and self._persist_path.exists():
            # 壊れたpickle等で起動不能になるのを避ける（Graphは補助情報のため）。
            # pickle.load()は破損データに対して UnpicklingError, EOFError,
            # AttributeError, ImportError など多様な例外を送出しうるため、
            # 種類を限定せず広く捕捉して空グラフにフォールバックする。
            try:
                self.load()
            except Exception:  # noqa: BLE001
                self._graph = nx.DiGraph()

    @property
    def persist_path(self) -> Optional[Path]:
        """グラフの永続化パスを取得する。

        Returns:
            Optional[Path]: 永続化パス。永続化しない場合はNone。
        """
        return self._persist_path

    def clear(self) -> None:
        """グラフをクリアする（すべてのノードとエッジを削除）。

        永続化されたファイルは削除されません。必要に応じて手動で削除してください。
        """
        self._graph.clear()

    def add_chunk_node(self, chunk_id: str, *, text: str = "", metadata: Optional[Dict[str, Any]] = None) -> None:
        """チャンクをノードとして追加する。

        Args:
            chunk_id: チャンクの一意識別子（通常は `document_id::chunk-{index}` 形式）。
            text: チャンクのテキスト内容（将来の拡張用、現状は使用しない）。
            metadata: ノードに付与するメタデータ（例: file_name, file_path, chunk_index など）。
        """
        meta = metadata or {}
        meta["entity_type"] = "chunk"
        # text は将来の拡張で使う（現状は検索はDB側から取得する）
        self._graph.add_node(chunk_id, text=text, **meta)

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        *,
        relation: str,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """関係性をエッジとして追加する。

        Args:
            source_id: 起点チャンクのID。
            target_id: 終点チャンクのID。
            relation: 関係性の種類（例: "next", "prev", "depends_on", "causes" など）。
            weight: エッジの重み（デフォルト: 1.0）。将来の拡張で使用。
            metadata: エッジに付与する追加メタデータ。
        """
        meta = metadata or {}
        self._graph.add_edge(source_id, target_id, relation=relation, weight=weight, **meta)

    def add_bidirectional_edge(
        self,
        a: str,
        b: str,
        *,
        relation_ab: str,
        relation_ba: str,
        weight: float = 1.0,
    ) -> None:
        """双方向の関係を追加する（例: next/prev）。

        Args:
            a: チャンクAのID。
            b: チャンクBのID。
            relation_ab: A→Bの関係性（例: "next"）。
            relation_ba: B→Aの関係性（例: "prev"）。
            weight: エッジの重み（デフォルト: 1.0）。
        """
        self.add_edge(a, b, relation=relation_ab, weight=weight)
        self.add_edge(b, a, relation=relation_ba, weight=weight)

    def has_node(self, chunk_id: str) -> bool:
        """指定したchunk_idのノードが存在するか確認する。

        Args:
            chunk_id: 確認対象のchunk_id。

        Returns:
            bool: ノードが存在する場合はTrue、存在しない場合はFalse。
        """
        return self._graph.has_node(chunk_id)

    def has_edge(self, source_id: str, target_id: str) -> bool:
        """指定したエッジが存在するか確認する。

        Args:
            source_id: 起点チャンクのID。
            target_id: 終点チャンクのID。

        Returns:
            bool: エッジが存在する場合はTrue、存在しない場合はFalse。
        """
        return self._graph.has_edge(source_id, target_id)

    def num_nodes(self) -> int:
        """グラフ内のノード数を返す。

        Returns:
            int: ノード数。
        """
        return self._graph.number_of_nodes()

    def num_edges(self) -> int:
        """グラフ内のエッジ数を返す。

        Returns:
            int: エッジ数。
        """
        return self._graph.number_of_edges()

    def get_node_degree(self, chunk_id: str) -> int:
        """ノードの次数（接続数）を取得する。

        Args:
            chunk_id: チャンクID。

        Returns:
            int: 次数（入次数 + 出次数）。ノードが存在しない場合は0。
        """
        if not self._graph.has_node(chunk_id):
            return 0
        return self._graph.in_degree(chunk_id) + self._graph.out_degree(chunk_id)

    def get_node_centrality(self, chunk_id: str) -> float:
        """ノードの中心性（次数中心性）を取得する。

        Args:
            chunk_id: チャンクID。

        Returns:
            float: 次数中心性（0.0〜1.0）。ノードが存在しない場合は0.0。
        """
        if not self._graph.has_node(chunk_id):
            return 0.0
        if self._graph.number_of_nodes() <= 1:
            return 1.0
        # 次数中心性 = 次数 / (ノード数 - 1)
        degree = self.get_node_degree(chunk_id)
        return degree / (self._graph.number_of_nodes() - 1)

    def get_min_distance_to_seeds(
        self,
        chunk_id: str,
        seed_ids: List[str],
        max_depth: int = 3,
    ) -> Optional[int]:
        """seed_idsからの最短距離を取得する。

        Args:
            chunk_id: 対象チャンクID。
            seed_ids: 起点チャンクIDのリスト。
            max_depth: 探索の最大深さ。

        Returns:
            Optional[int]: 最短距離（hop数）。到達不可能な場合はNone。
        """
        if not self._graph.has_node(chunk_id):
            return None
        if chunk_id in seed_ids:
            return 0

        # BFSで最短距離を計算
        visited = set(seed_ids)
        queue = [(sid, 0) for sid in seed_ids]

        while queue:
            current, distance = queue.pop(0)
            if distance >= max_depth:
                continue

            for neighbor in self._graph.successors(current):
                if neighbor == chunk_id:
                    return distance + 1
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, distance + 1))

        return None

    def neighbors_with_distance(
        self,
        start_ids: Iterable[str],
        *,
        max_depth: int = 1,
        limit: int = 50,
        include_start: bool = False,
        only_chunk_ids: bool = False,
    ) -> List[Neighbor]:
        """start_ids から BFS で近傍ノードを距離つきで返す。

        有向グラフの「後続（successors）」方向に探索し、距離（hop数）と関係性を付与して返します。
        複数の起点から同時に探索する multi-source BFS を実装しています。

        Args:
            start_ids: 探索の起点となるチャンクIDのリスト。
            max_depth: 探索の最大深さ（hop数、デフォルト: 1）。
            limit: 返す近傍ノードの最大数（デフォルト: 50）。
            include_start: Trueの場合、起点ノード自体も結果に含める（デフォルト: False）。
            only_chunk_ids: Trueの場合、戻り値に含めるノードを「チャンクID形式」に限定する。
                （例: "::chunk-" を含むIDのみを返す。探索自体は中間ノードも辿る）

        Returns:
            List[Neighbor]: 距離（昇順）でソートされた近傍ノードのリスト。
                各ノードには距離と関係性が付与されています。

        Example:
            >>> gs = GraphStore()
            >>> gs.add_chunk_node("a")
            >>> gs.add_chunk_node("b")
            >>> gs.add_chunk_node("c")
            >>> gs.add_bidirectional_edge("a", "b", relation_ab="next", relation_ba="prev")
            >>> gs.add_bidirectional_edge("b", "c", relation_ab="next", relation_ba="prev")
            >>> neighbors = gs.neighbors_with_distance(["a"], max_depth=2)
            >>> [n.chunk_id for n in neighbors]
            ['b', 'c']
            >>> neighbors[0].distance
            1
        """
        if max_depth <= 0:
            return []

        start_list = [s for s in start_ids if self._graph.has_node(s)]
        if not start_list:
            return []

        results: List[Neighbor] = []
        seen: Dict[str, int] = {}

        # multi-source BFS（簡易）
        queue: List[Tuple[str, int]] = []
        for s in start_list:
            queue.append((s, 0))
            seen[s] = 0

        while queue and len(results) < limit:
            node, depth = queue.pop(0)
            if depth >= max_depth:
                continue

            for nbr in self._graph.successors(node):
                next_depth = depth + 1
                if nbr in seen and seen[nbr] <= next_depth:
                    continue
                seen[nbr] = next_depth

                if include_start or nbr not in start_list:
                    # only_chunk_ids の場合、結果にはチャンクIDらしいものだけを入れる。
                    # ただし探索は継続したいので、results 追加条件だけに適用する。
                    nbr_id = str(nbr)
                    if (not only_chunk_ids) or ("::chunk-" in nbr_id):
                        # relation は最短経路上の直前エッジの relation を付ける（簡易）
                        edge_data = self._graph.get_edge_data(node, nbr) or {}
                        results.append(
                            Neighbor(chunk_id=nbr_id, distance=next_depth, relation=edge_data.get("relation"))
                        )
                        if len(results) >= limit:
                            break

                queue.append((str(nbr), next_depth))

        # 距離昇順（同距離は入力順のまま）
        results.sort(key=lambda x: x.distance)
        return results

    def save(self) -> None:
        """グラフを永続化（pickle）する。

        `persist_path` が設定されている場合のみ使用可能です。
        ディレクトリが存在しない場合は自動作成します。

        Raises:
            ValueError: `persist_path` が設定されていない場合。
            IOError: ファイルの書き込みに失敗した場合。
        """
        if self._persist_path is None:
            raise ValueError("persist_path is not set")
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._persist_path, "wb") as f:
            pickle.dump(self._graph, f, protocol=pickle.HIGHEST_PROTOCOL)

    def load(self) -> None:
        """永続化されたグラフをロードする。

        `persist_path` が設定されている場合のみ使用可能です。
        ファイルが存在しない場合は何もしません（初回実行時）。

        Raises:
            ValueError: `persist_path` が設定されていない場合、または
                ファイル内のオブジェクトが DiGraph でない場合。
            IOError: ファイルの読み込みに失敗した場合。

        Note:
            セキュリティ注意: pickle.load()は逆シリアライズ時に任意コードを
            実行し得る。`persist_path`はconfig.GRAPH_PATH固定でMCPツール引数
            等の外部入力からは変更できないため現状は安全だが、この関数を
            外部指定のパスに対して呼び出すよう変更してはならない。isinstance
            チェックはロード後にしか働かず、コード実行そのものは防げない点に注意。
        """
        if self._persist_path is None:
            raise ValueError("persist_path is not set")
        if not self._persist_path.exists():
            # 何もしない（初回）
            return
        with open(self._persist_path, "rb") as f:
            obj = pickle.load(f)
        if not isinstance(obj, nx.DiGraph):
            raise ValueError("invalid graph object in persist file")
        self._graph = obj

    # ============================================================================
    # GraphRAG拡張: 仕様書検証向けエンティティ（Constraint, SyntaxRule, SpecClause, Term）
    # ============================================================================

    def add_constraint_node(
        self,
        constraint_id: str,
        *,
        name: str = "",
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Constraint（検証ルール・制約）をノードとして追加する。

        Args:
            constraint_id: Constraintの一意識別子（例: "C-012"）。
            name: Constraint名（例: "Port Definition Rule"）。
            description: Constraintの説明。
            metadata: 追加メタデータ。
        """
        meta = metadata or {}
        meta["entity_type"] = "constraint"
        meta["name"] = name
        meta["description"] = description
        self._graph.add_node(constraint_id, **meta)

    def add_syntax_rule_node(
        self,
        rule_id: str,
        *,
        name: str = "",
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """SyntaxRule（構文ルール）をノードとして追加する。

        Args:
            rule_id: SyntaxRuleの一意識別子（例: "SR-05"）。
            name: SyntaxRule名（例: "Action Body Syntax"）。
            description: SyntaxRuleの説明。
            metadata: 追加メタデータ。
        """
        meta = metadata or {}
        meta["entity_type"] = "syntax_rule"
        meta["name"] = name
        meta["description"] = description
        self._graph.add_node(rule_id, **meta)

    def add_spec_clause_node(
        self,
        clause_id: str,
        *,
        clause_number: str = "",
        title: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """SpecClause（仕様書条文ID）をノードとして追加する。

        Args:
            clause_id: SpecClauseの一意識別子（例: "7.3.1"）。
            clause_number: 条文番号（例: "7.3.1"）。
            title: 条文タイトル。
            metadata: 追加メタデータ。
        """
        meta = metadata or {}
        meta["entity_type"] = "spec_clause"
        meta["clause_number"] = clause_number
        meta["title"] = title
        self._graph.add_node(clause_id, **meta)

    def add_term_node(
        self,
        term_id: str,
        *,
        term: str = "",
        definition: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Term（用語）をノードとして追加する。

        Args:
            term_id: Termの一意識別子（例: "term::action"）。
            term: 用語名（例: "action"）。
            definition: 用語の定義。
            metadata: 追加メタデータ。
        """
        meta = metadata or {}
        meta["entity_type"] = "term"
        meta["term"] = term
        meta["definition"] = definition
        self._graph.add_node(term_id, **meta)

    def get_related_entities(
        self,
        chunk_ids: List[str],
        *,
        entity_types: Optional[List[str]] = None,
        relations: Optional[List[str]] = None,
        max_depth: int = 2,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """指定したチャンクIDから関連するエンティティを取得する。

        Args:
            chunk_ids: 起点となるチャンクIDのリスト。
            entity_types: 取得するエンティティタイプ（例: ["constraint", "syntax_rule", "spec_clause"]）。
                Noneの場合はすべてのタイプを取得。
            relations: 取得する関係タイプ（例: ["derived_from", "refers_to"]）。
                Noneの場合はすべての関係を取得。
            max_depth: 探索の最大深さ（hop数、デフォルト: 2）。

        Returns:
            Dict[str, List[Dict[str, Any]]]: エンティティタイプをキー、エンティティ情報のリストを値とする辞書。
                各エンティティ情報には以下が含まれる:
                - id: エンティティID
                - entity_type: エンティティタイプ
                - relation: 関係タイプ
                - distance: 起点からの距離
                - metadata: エンティティのメタデータ
        """
        if entity_types is None:
            entity_types = ["constraint", "syntax_rule", "spec_clause", "term"]
        if relations is None:
            relations = ["derived_from", "refers_to", "defined_in", "contains", "used_in"]

        results: Dict[str, List[Dict[str, Any]]] = {et: [] for et in entity_types}

        # BFSで探索
        visited: Dict[str, int] = {}
        queue: List[Tuple[str, int, Optional[str]]] = [(cid, 0, None) for cid in chunk_ids if self._graph.has_node(cid)]

        for cid in chunk_ids:
            visited[cid] = 0

        while queue:
            node_id, depth, relation = queue.pop(0)
            if depth >= max_depth:
                continue

            for successor in self._graph.successors(node_id):
                edge_data = self._graph.get_edge_data(node_id, successor) or {}
                edge_relation = edge_data.get("relation")

                # 関係タイプでフィルタ
                if relations and edge_relation not in relations:
                    continue

                # 既に訪問済みで、より短い経路がある場合はスキップ
                if successor in visited and visited[successor] <= depth + 1:
                    continue

                visited[successor] = depth + 1

                # ノードのメタデータを取得
                node_data = self._graph.nodes[successor]
                entity_type = node_data.get("entity_type")

                # エンティティタイプでフィルタ
                if entity_type and entity_type in entity_types:
                    entity_info = {
                        "id": str(successor),
                        "entity_type": entity_type,
                        "relation": edge_relation,
                        "distance": depth + 1,
                        "metadata": dict(node_data),
                    }
                    results[entity_type].append(entity_info)

                # 次の探索に追加
                queue.append((str(successor), depth + 1, edge_relation))

        # 重複を除去（同じIDで距離が最小のもののみ残す）
        for entity_type in results:
            seen_ids: Dict[str, Dict[str, Any]] = {}
            for entity in results[entity_type]:
                eid = entity["id"]
                if eid not in seen_ids or entity["distance"] < seen_ids[eid]["distance"]:
                    seen_ids[eid] = entity
            results[entity_type] = list(seen_ids.values())

        return results


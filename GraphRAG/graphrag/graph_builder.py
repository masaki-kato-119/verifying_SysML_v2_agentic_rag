"""
Graph構築モジュール（仕様書 7章）
NetworkXを使用
"""
import logging
import re
from time import perf_counter
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from . import config
from .datamodels import ConceptCandidate, ConceptFeatures, ConceptType
from .ontology_validator import OntologyValidator

logger = logging.getLogger(__name__)


class GraphBuilder:
    """
    グラフ構築器
    
    仕様書 7章に基づく
    - ノード: ConceptType == ENTITY
    - エッジ: Relation のみ、方向性を持つ
    - 属性: VALUE はノード属性として格納
    - EVENT は時系列補助情報として分離可能
    """

    # 1 文から取り出すエンティティの上限（探索コストの抑制用）
    MAX_ENTITIES_PER_SENTENCE = 20

    def __init__(self, domain: str = 'universal'):
        """
        グラフ構築器を初期化
        
        Args:
            domain: ドメイン（'universal', 'sysml_v2', 'software_architecture', 'business_process'）
        """
        self.validator = OntologyValidator()
        self.graph = nx.DiGraph()
        # 元のテキストチャンクへの参照を保持
        self.source_chunks: Dict[str, str] = {}  # chunk_id -> text
        self.node_to_chunks: Dict[str, List[str]] = {}  # node_name -> [chunk_id, ...]
        self.edge_to_chunks: Dict[Tuple[str, str], List[str]] = {}  # (source, target) -> [chunk_id, ...]
        # チャンク分割結果をキャッシュ（最適化）
        self._cached_chunks: Optional[Dict[str, str]] = None
        self._cached_text: Optional[str] = None
        # 関係語彙の単語境界パターンのキャッシュ（文ごとに再コンパイルしない）
        self._vocab_patterns: Dict[str, "re.Pattern[str]"] = {}
        # エンティティ名用のパターンキャッシュ。複数形を許容する点が
        # 関係語彙と異なるため、キャッシュを共有してはいけない。
        self._term_patterns: Dict[str, "re.Pattern[str]"] = {}
        # Phase 2: ドメイン関係マネージャー
        from .domain_relation_manager import DomainRelationManager
        self.domain_manager = DomainRelationManager(domain=domain)
    
    def _is_stopword(self, lemma: str) -> bool:
        """
        ストップワードかどうかを判定
        
        Args:
            lemma: 正規化された単語
        
        Returns:
            bool: ストップワードの場合True
        """
        from . import config
        
        # ストップワードチェック
        if lemma.lower() in config.STOPWORDS:
            return True
        
        # 短語フィルタ（最小文字数未満）
        if len(lemma) < config.MIN_WORD_LENGTH:
            return True
        
        return False
    
    def _merge_entities(self, entities: List[ConceptCandidate]) -> Dict[str, ConceptCandidate]:
        """
        同一 lemma の ENTITY を統合（仕様書 6.3）
        ストップワードと短語を除外
        品詞フィルタを適用（名詞、動詞のみ許可）
        
        Args:
            entities: ENTITY候補のリスト
        
        Returns:
            Dict[str, ConceptCandidate]: lemmaをキーとした統合済みエンティティ
        """
        from .datamodels import POS
        
        merged = {}
        for entity in entities:
            lemma = entity.lemma
            
            # ストップワードと短語を除外
            if self._is_stopword(lemma):
                continue
            
            # 品詞フィルタ: 名詞（NOUN, PROPN）、動詞（VERB）、形容詞（ADJ）を許可
            if entity.pos not in [POS.NOUN, POS.PROPN, POS.VERB, POS.ADJ]:
                continue
            
            if lemma not in merged:
                merged[lemma] = entity
            # 既に存在する場合は最初のものを保持（統合）
        return merged

    def _merge_alias_duplicate_nodes(self, graph: nx.DiGraph) -> int:
        """SYSML_V2_ALIASESの表記ゆれで分裂した重複ノードを1つに統合する。

        抽出パイプラインは同じ概念でも、BNF文法名由来の連結スペル
        （例: "requirementusage"）と地の文由来の分かち書き（例:
        "requirement usage"）を別々の lemma として候補化することがある。
        `_merge_entities` は厳密な文字列一致でしか統合しないため、この
        表記ゆれは別ノードとして残ってしまい、片方にしかエッジが無い
        「準孤立ノード」を生む（a4_graph_path_precision調査で発覚、
        qa-attribution-02の経路探索精度低下の根本原因）。

        SYSML_V2_ALIASESの各エイリアス群（同一概念の表記ゆれリスト）を
        使って、実際にグラフ上に複数ノードとして存在する組を検出し、
        分かち書き形（自然文の問い合わせに近い）を正としてエッジ・
        チャンク参照を統合する。

        Args:
            graph: 統合対象のグラフ（in-placeで変更する）。

        Returns:
            int: 統合し削除した重複ノード数。
        """
        merged_count = 0
        for variants in config.SYSML_V2_ALIASES.values():
            present = [v for v in variants if v in graph]
            if len(present) < 2:
                continue

            spaced = [v for v in present if " " in v]
            if spaced:
                canonical = spaced[0]
            else:
                canonical = max(present, key=lambda v: graph.in_degree(v) + graph.out_degree(v))

            for dup in present:
                if dup == canonical:
                    continue
                self._merge_node_into(graph, dup, canonical)
                merged_count += 1

        if merged_count:
            logger.info(f"表記ゆれ重複ノード統合完了: {merged_count}ノードを統合")
        return merged_count

    def _merge_node_into(self, graph: nx.DiGraph, dup: str, canonical: str) -> None:
        """dupノードの入出力エッジ・チャンク参照をcanonicalへ付け替えてdupを削除する。"""
        for _, target, data in list(graph.out_edges(dup, data=True)):
            if target == canonical:
                continue
            self._add_or_merge_edge(graph, canonical, target, data)
        for source, _, data in list(graph.in_edges(dup, data=True)):
            if source == canonical:
                continue
            self._add_or_merge_edge(graph, source, canonical, data)

        dup_chunks = graph.nodes[dup].get('source_chunks', [])
        if dup_chunks:
            canonical_chunks = list(graph.nodes[canonical].get('source_chunks', []))
            for c in dup_chunks:
                if c not in canonical_chunks:
                    canonical_chunks.append(c)
            graph.nodes[canonical]['source_chunks'] = canonical_chunks

        node_to_chunks = graph.graph.get('node_to_chunks')
        if isinstance(node_to_chunks, dict) and dup in node_to_chunks:
            existing = node_to_chunks.setdefault(canonical, [])
            for c in node_to_chunks.pop(dup):
                if c not in existing:
                    existing.append(c)

        edge_to_chunks = graph.graph.get('edge_to_chunks')
        if isinstance(edge_to_chunks, dict):
            for key in [k for k in edge_to_chunks if dup in k]:
                new_key = tuple(canonical if n == dup else n for n in key)
                if new_key[0] == new_key[1]:
                    del edge_to_chunks[key]
                    continue
                existing = edge_to_chunks.setdefault(new_key, [])
                for c in edge_to_chunks.pop(key):
                    if c not in existing:
                        existing.append(c)

        graph.remove_node(dup)

    @staticmethod
    def _add_or_merge_edge(graph: nx.DiGraph, source: str, target: str, data: Dict[str, Any]) -> None:
        """source->target エッジを追加する。既存エッジがあればsource_chunksのみ併合する。"""
        if graph.has_edge(source, target):
            existing = graph[source][target]
            existing_chunks = list(existing.get('source_chunks', []))
            for c in data.get('source_chunks', []):
                if c not in existing_chunks:
                    existing_chunks.append(c)
            if existing_chunks:
                existing['source_chunks'] = existing_chunks
        else:
            graph.add_edge(source, target, **data)

    def build(
        self,
        candidates: List[ConceptCandidate],
        features_list: List[ConceptFeatures],
        types: List[ConceptType],
        text: Optional[str] = None
    ) -> nx.DiGraph:
        """
        グラフを構築
        
        Args:
            candidates: ConceptCandidateのリスト
            features_list: ConceptFeaturesのリスト
            types: ConceptTypeのリスト
            text: 元のテキスト（チャンク参照用）
        
        Returns:
            nx.DiGraph: 構築されたグラフ
        """
        build_start = perf_counter()
        logger.info(f"グラフ構築開始: {len(candidates)}候補, テキスト長: {len(text) if text else 0}文字")
        
        # チャンク参照を初期化
        # 注意: source_chunksが既に設定されている場合（process_pdfで事前にDBに保存済み）は初期化しない
        if not self.source_chunks:
            self.source_chunks = {}
        self.node_to_chunks = {}
        self.edge_to_chunks = {}
        # メモリ最適化: キャッシュは削除（必要に応じて再計算）
        self._cached_chunks = None
        self._cached_text = None
        
        # テキストをチャンクに分割（元のテキスト参照用、1回だけ実行）
        # 注意: source_chunksが既に設定されている場合は再分割しない（process_pdfで事前にDBに保存済み）
        if text and not self.source_chunks:
            start_time = perf_counter()
            chunks = self._split_into_chunks(text)
            chunk_time = perf_counter() - start_time
            logger.info(f"チャンク分割完了: {len(chunks)}チャンク, 所要時間: {chunk_time:.2f}秒")
            
            # メモリ最適化: source_chunksのみ保持（キャッシュは保持しない）
            for chunk_id, chunk_text in chunks.items():
                self.source_chunks[chunk_id] = chunk_text
            
            # メモリ最適化: 大きなテキストの場合はキャッシュを保持しない
            # チャンク数が少ない場合のみキャッシュを保持（メモリ使用量を制限）
            if len(chunks) < 1000:  # チャンク数が1000未満の場合のみキャッシュ
                self._cached_chunks = chunks
                self._cached_text = text
            else:
                # 大きなテキストの場合はキャッシュを保持しない（メモリ節約）
                logger.debug(f"メモリ最適化: チャンク数が多いためキャッシュを保持しません ({len(chunks)}チャンク)")
                self._cached_chunks = None
                self._cached_text = None
        elif self.source_chunks:
            # source_chunksが既に設定されている場合（process_pdfで事前にDBに保存済み）
            logger.debug(f"チャンクは既に設定されています: {len(self.source_chunks)}チャンク（再分割をスキップ）")
            # キャッシュは設定しない（メモリ節約）
            self._cached_chunks = None
            self._cached_text = None
        
        # オントロジー整合チェック
        start_time = perf_counter()
        valid_entities, valid_relations = self.validator.validate(
            candidates, types
        )
        validate_time = perf_counter() - start_time
        logger.info(f"オントロジー整合チェック完了: {len(valid_entities)}エンティティ, {len(valid_relations)}関係, 所要時間: {validate_time:.2f}秒")

        # ドメイン用語ゲート（C-lite）
        # ENTITY 判定は POS ベースなので、固有名詞タグが付いた語はすべて通る。
        # その結果 "omg" や "usa" のような無関係な語がノードになり、
        # ノード母集団の 97.5% が「PDF 中で大文字始まりだったか」で決まっていた。
        # SysML v2 の用語辞書で母集団をドメインへ接地させる。
        if config.DOMAIN_TERM_GATE:
            before = len(valid_entities)
            domain_terms = config.domain_term_set()
            valid_entities = [
                e for e in valid_entities if str(e.lemma).lower().strip() in domain_terms
            ]
            logger.info(
                f"ドメイン用語ゲート: {before} -> {len(valid_entities)} エンティティ"
                f"（辞書 {len(domain_terms)} 語）"
            )

        # 同一lemmaのENTITYを統合
        merged_entities = self._merge_entities(valid_entities)
        logger.info(f"エンティティ統合完了: {len(merged_entities)}エンティティ")
        
        # グラフを初期化
        self.graph = nx.DiGraph()
        
        # ノードの追加（ENTITYのみ）
        start_time = perf_counter()
        for lemma, entity in merged_entities.items():
            # 対応するFeaturesを取得
            entity_features = None
            for candidate, features in zip(candidates, features_list):
                if candidate == entity:
                    entity_features = features
                    break
            
            # ノード属性を設定
            # concept_type は分類器（Classifier）の出力。保存しないとオントロジー層の
            # 判定結果が下流へ届かず、node_type_filter やパス品質スコアリングが
            # 常に 'unknown' 扱いになって機能しない（フィルタ指定時は必ず 0 件になる）。
            #
            # 注意: ノードになれるのは OntologyValidator.validate_entities を通った
            # ENTITY だけなので、現状この値は常に ENTITY である。フィルタが
            # 「動く」ようにはなるが、種別による絞り込みの効果は無い。
            # 種別で絞りたい場合は、ノードの母集団自体を見直す必要がある。
            node_attrs = {
                'lemma': lemma,
                'concept_type': ConceptType.ENTITY.value,
                # 後方互換: 下流は 'type' を参照している箇所がある
                'type': ConceptType.ENTITY.value,
                'pos': entity.pos.value,
                'is_proper': entity.is_proper,
                'has_numeric_id': entity.has_numeric_id,
                'is_abstract': entity.is_abstract,
            }
            
            if entity_features:
                node_attrs.update({
                    'has_identity': entity_features.has_identity,
                    'persistent': entity_features.persistent,
                    'referable': entity_features.referable,
                    'attribute_count': entity_features.attribute_count,
                })
            
            self.graph.add_node(lemma, **node_attrs)
            
            # ノードに関連するチャンクを記録（テキストがある場合）
            # 最適化: チャンク検索は後でまとめて実行（メモリと速度の最適化）
            # ここではスキップし、エッジ追加後にまとめて処理
        
        node_time = perf_counter() - start_time
        logger.info(f"ノード追加完了: {self.graph.number_of_nodes()}ノード, 所要時間: {node_time:.2f}秒")
        
        # VALUEをノード属性として格納
        value_attributes = {}
        for candidate, features, concept_type in zip(candidates, features_list, types):
            if concept_type == ConceptType.VALUE:
                # このVALUEがどのENTITYに関連するかは後で決定
                # ここでは一時的に保存
                value_attributes[candidate.lemma] = {
                    'value': candidate.lemma,
                    'features': features
                }
        
        # エッジの追加（文単位解析 + 共起関係ベース）
        # 仕様書の原則に従い、ルールベースで決定論的にエッジを生成
        start_time = perf_counter()
        if text:
            # 文単位解析で関係語彙から関係タイプを自動判定
            self._add_edges_from_sentence_analysis(
                text, candidates, types, valid_entities, merged_entities
            )
        else:
            # テキストがない場合は共起関係ベースのみ
            self._add_edges_from_cooccurrence(
                candidates, types, valid_entities, merged_entities
            )
        edge_time = perf_counter() - start_time
        logger.info(f"エッジ追加完了: {self.graph.number_of_edges()}エッジ, 所要時間: {edge_time:.2f}秒")
        
        # 最適化: ノード-チャンク関連をまとめて構築（エッジ追加後、またはエッジが0個でも構築）
        if text and self.source_chunks and self.graph.number_of_nodes() > 0:
            start_time = perf_counter()
            logger.info("ノード-チャンク関連を構築中...")
            chunks_to_search = self._cached_chunks if self._cached_chunks else self.source_chunks
            text_lower = text.lower()  # 一度だけ小文字化
            
            # 最適化: ノードをバッチで処理
            nodes_processed = 0
            for lemma in self.graph.nodes():
                # 最適化: テキストに含まれていない場合はスキップ
                if lemma.lower() not in text_lower:
                    continue
                
                related_chunks = self._find_chunks_for_node(lemma, text, chunks_to_search)
                if related_chunks:
                    # 最適化: 最初の5チャンクのみ保持（メモリ節約）
                    related_chunks = related_chunks[:5]
                    self.node_to_chunks[lemma] = related_chunks
                    self.graph.nodes[lemma]['source_chunks'] = related_chunks
                
                nodes_processed += 1
                if nodes_processed % 1000 == 0:
                    logger.debug(f"ノード-チャンク関連構築進捗: {nodes_processed}/{self.graph.number_of_nodes()}ノード")
            
            node_chunk_time = perf_counter() - start_time
            logger.info(f"ノード-チャンク関連構築完了: {len(self.node_to_chunks)}ノード, 所要時間: {node_chunk_time:.2f}秒")
        
        # 表記ゆれ（連結スペル vs 分かち書き）で分裂した重複ノードを統合
        self._merge_alias_duplicate_nodes(self.graph)

        # 構造制約のチェック
        # 最適化: 大規模グラフの場合は循環チェックをスキップ（パフォーマンス優先）
        start_time = perf_counter()
        if self.graph.number_of_edges() > 5000:
            logger.warning("大規模グラフのため、構造制約チェックをスキップします（パフォーマンス優先）")
            constraint_time = 0.0
        else:
            is_valid, errors = self.validator.check_structure_constraints(self.graph)
            if not is_valid:
                # エラーをログに記録
                for error in errors:
                    logger.warning(f"構造制約違反: {error}")
            constraint_time = perf_counter() - start_time
            logger.info(f"構造制約チェック完了: 所要時間: {constraint_time:.2f}秒")
        
        total_time = perf_counter() - build_start
        logger.info(f"グラフ構築完了: {self.graph.number_of_nodes()}ノード, {self.graph.number_of_edges()}エッジ, 総所要時間: {total_time:.2f}秒")
        
        # チャンク参照情報をグラフの属性に保存
        if self.source_chunks:
            self.graph.graph['source_chunks'] = self.source_chunks
            self.graph.graph['node_to_chunks'] = self.node_to_chunks
            self.graph.graph['edge_to_chunks'] = self.edge_to_chunks
            logger.info(f"チャンク参照情報を保存: {len(self.source_chunks)}チャンク, {len(self.node_to_chunks)}ノード, {len(self.edge_to_chunks)}エッジ")
        
        return self.graph
    
    def add_relation(
        self,
        source: str,
        target: str,
        relation_type: str,
        attributes: Optional[Dict] = None,
        source_text: Optional[str] = None
    ) -> bool:
        """
        関係を追加
        
        Args:
            source: ソースノード（lemma）
            target: ターゲットノード（lemma）
            relation_type: 関係タイプ（事前定義されたもののみ）
            attributes: 追加の属性
            source_text: 元のテキスト（チャンク参照用）
        
        Returns:
            bool: 追加に成功したかどうか
        """
        # ストップワードチェック（エッジ生成時にストップワードノードを除外）
        if self._is_stopword(source) or self._is_stopword(target):
            return False
        
        # ノードが存在するかチェック
        if source not in self.graph or target not in self.graph:
            return False
        
        # 関係タイプが許可されているかチェック
        if relation_type not in config.ALLOWED_RELATIONS:
            return False
        
        # エッジを追加
        edge_attrs = {'relation': relation_type}
        if attributes:
            edge_attrs.update(attributes)
        
        # エッジに関連するチャンクを記録（テキストがある場合）
        if source_text:
            # source_textは通常文単位なので、全体のチャンクとは別に処理
            # ただし、キャッシュされたチャンクがある場合はそれを使用
            if self._cached_chunks and self._cached_text and source_text in self._cached_text:
                # 全体テキストの一部の場合はキャッシュを使用
                chunks = self._cached_chunks
            else:
                # 文単位のテキストの場合は新しく分割（軽量）
                chunks = self._split_into_chunks(source_text)
            
            related_chunks = self._find_chunks_for_edge(source, target, source_text, chunks)
            if related_chunks:
                self.edge_to_chunks[(source, target)] = related_chunks
                edge_attrs['source_chunks'] = related_chunks
        
        self.graph.add_edge(source, target, **edge_attrs)
        
        # 構造制約を再チェック
        is_valid, errors = self.validator.check_structure_constraints(self.graph)
        if not is_valid:
            # 制約違反の場合はエッジを削除
            self.graph.remove_edge(source, target)
            return False
        
        return True
    
    def _split_into_chunks(self, text: str) -> Dict[str, str]:
        """
        テキストをチャンクに分割（元のテキスト参照用）
        目次チャンクをフィルタリング
        
        Args:
            text: 入力テキスト
            
        Returns:
            Dict[str, str]: chunk_id -> chunk_text のマッピング（目次チャンク除去済み）
        """
        from . import config
        chunks = {}
        chunk_size = config.CHUNK_SIZE
        chunk_overlap = config.CHUNK_OVERLAP
        
        start = 0
        chunk_id = 0
        
        while start < len(text):
            end = start + chunk_size
            chunk_text = text[start:end]
            
            if chunk_text.strip():
                chunk_key = f"chunk_{chunk_id}"
                chunks[chunk_key] = chunk_text
                chunk_id += 1
            
            # オーバーラップを考慮して次の開始位置を設定
            start = end - chunk_overlap
            if start >= len(text):
                break
        
        # 目次チャンクをフィルタリング
        filtered_chunks = config.filter_table_of_contents_chunks(chunks)
        
        return filtered_chunks
    
    def _find_chunks_for_node(self, node_name: str, text: str, chunks: Dict[str, str]) -> List[str]:
        """
        ノード名が含まれるチャンクを検索（Phase 3: メモリ最適化版）
        
        Args:
            node_name: ノード名（lemma）
            text: 元のテキスト
            chunks: チャンクのマッピング（空文字列の場合はDBから取得が必要）
        
        Returns:
            List[str]: チャンクIDのリスト
        """
        related_chunks = []
        node_lower = node_name.lower()
        
        # Phase 3: メモリ最適化 - チャンクテキストが空の場合はスキップ
        # （大きなチャンクセットの場合、テキストは保持していない）
        empty_chunks = all(not chunk_text for chunk_text in chunks.values())
        
        if empty_chunks:
            # チャンクテキストが保持されていない場合は、テキスト全体で検索
            if text:
                text_lower = text.lower()
                if node_lower not in text_lower:
                    return []  # テキストに含まれていない場合は早期リターン
                # テキスト全体から位置を特定してチャンクIDを推定
                # （簡易版: 最初の5チャンクを返す）
                chunk_ids = list(chunks.keys())[:5]
                return chunk_ids
            return []
        
        # 最適化: チャンク数が多い場合は、テキスト全体で先に検索してから該当チャンクを特定
        if len(chunks) > 100:
            # テキスト全体でノード名を検索
            text_lower = text.lower() if text else ""
            if text_lower and node_lower not in text_lower:
                return []  # テキストに含まれていない場合は早期リターン
        
        # 最適化: チャンクを一度だけ小文字化して検索（メモリと速度の最適化）
        # ただし、メモリ使用量を考慮して、チャンク数が多い場合は早期終了
        max_chunks_to_check = 1000  # 最大1000チャンクまでチェック（メモリ節約）
        chunks_checked = 0
        
        for chunk_id, chunk_text in chunks.items():
            # Phase 3: 空のチャンクテキストはスキップ
            if not chunk_text:
                continue
            
            # 最適化: チャンク数が多い場合は早期終了
            if chunks_checked >= max_chunks_to_check:
                break
            
            # 最適化: チャンクテキストを小文字化して検索
            if node_lower in chunk_text.lower():
                related_chunks.append(chunk_id)
                # 最適化: 十分なチャンクが見つかったら早期終了（最初の5個のみ必要）
                if len(related_chunks) >= 5:
                    break
            
            chunks_checked += 1
        
        return related_chunks
    
    def _find_chunks_for_edge(self, source: str, target: str, text: str, chunks: Dict[str, str]) -> List[str]:
        """
        エッジ（source-target）が含まれるチャンクを検索
        
        Args:
            source: ソースノード名
            target: ターゲットノード名
            text: 元のテキスト
            chunks: チャンクのマッピング
            
        Returns:
            List[str]: チャンクIDのリスト
        """
        related_chunks = []
        source_lower = source.lower()
        target_lower = target.lower()
        
        # 最適化: チャンク数が多い場合は、テキスト全体で先に検索
        if len(chunks) > 100:
            text_lower = text.lower()
            if source_lower not in text_lower or target_lower not in text_lower:
                return []  # テキストに含まれていない場合は早期リターン
        
        for chunk_id, chunk_text in chunks.items():
            chunk_lower = chunk_text.lower()
            # 両方のノード名が含まれるチャンクを関連チャンクとする
            if source_lower in chunk_lower and target_lower in chunk_lower:
                related_chunks.append(chunk_id)
        
        return related_chunks
    
    def get_source_chunks(self) -> Dict[str, str]:
        """元のテキストチャンクを取得"""
        return self.source_chunks
    
    def _add_edges_from_cooccurrence(
        self,
        candidates: List[ConceptCandidate],
        types: List[ConceptType],
        valid_entities: List[ConceptCandidate],
        merged_entities: Dict[str, ConceptCandidate]
    ) -> None:
        """
        共起関係からエッジを生成（ルールベース、決定論的）
        
        仕様書の原則に従い：
        - 同一入力 → 同一グラフ
        - すべての判断はif文で説明可能
        
        Args:
            candidates: 全候補リスト
            types: 対応するConceptTypeのリスト
            valid_entities: 有効なエンティティのリスト
            merged_entities: 統合済みエンティティの辞書
        """
        # エンティティの出現位置を記録
        entity_positions: Dict[str, List[int]] = {}
        for i, (candidate, concept_type) in enumerate(zip(candidates, types)):
            if concept_type == ConceptType.ENTITY and candidate.lemma in merged_entities:
                lemma = candidate.lemma
                if lemma not in entity_positions:
                    entity_positions[lemma] = []
                entity_positions[lemma].append(i)
        
        # 共起ウィンドウサイズ（近接度の閾値）
        # 同じ文や近い文脈に出現したエンティティ間の関係を抽出
        cooccurrence_window = config.COOCCURRENCE_WINDOW
        min_cooccurrence = config.MIN_COOCCURRENCE
        
        # エンティティペアの共起回数をカウント
        logger.info(f"共起関係計算開始: {len(entity_positions)}エンティティ")
        start_time = perf_counter()
        
        cooccurrence_count: Dict[Tuple[str, str], int] = {}
        entity_list = list(entity_positions.items())
        total_pairs = len(entity_list) * (len(entity_list) - 1) // 2
        
        processed_pairs = 0
        for i, (lemma1, positions1) in enumerate(entity_list):
            for j, (lemma2, positions2) in enumerate(entity_list[i+1:], start=i+1):
                # 共起回数をカウント
                count = 0
                for pos1 in positions1:
                    for pos2 in positions2:
                        if abs(pos1 - pos2) <= cooccurrence_window:
                            count += 1
                
                if count > 0:
                    cooccurrence_count[(lemma1, lemma2)] = count
                
                processed_pairs += 1
                if processed_pairs % 1000 == 0:
                    logger.info(f"共起関係計算進捗: {processed_pairs}/{total_pairs}ペア処理完了")
        
        cooccurrence_time = perf_counter() - start_time
        logger.info(f"共起関係計算完了: 所要時間: {cooccurrence_time:.2f}秒")
        
        # 共起回数が閾値以上のペアにエッジを追加
        for (source, target), count in cooccurrence_count.items():
            if count >= min_cooccurrence:
                # デフォルトの関係タイプとして "depends-on" を使用
                # （仕様書6.2の事前定義された関係語彙の一つ）
                self.add_relation(source, target, "depends-on")
    
    def find_term_position(self, sentence: str, term: str) -> int:
        """文中の語の出現位置を返す（見つからなければ -1）。

        英数字の語は単語境界で、大文字小文字を無視して照合する。
        部分文字列一致だと ``"portion"`` が ``"port"`` に、``"sometimes"`` が
        ``"time"`` に、``"packages"`` が ``"package"`` にマッチしてしまい、
        まったく無関係なノード対からエッジが生成される。

        ノード名は lemma（単数形）なので、末尾の複数形だけは許容する。
        ここを厳密一致にすると ``"ports"`` ``"actions"`` のような通常の
        言い回しを取りこぼし、再現率が大きく落ちる。

        日本語は語境界の概念が使えないため、部分文字列で照合する。

        Args:
            sentence: 対象の文。
            term: 探す語（関係語彙またはエンティティ名）。

        Returns:
            int: 出現位置。見つからない場合は -1。
        """
        if term.isascii():
            # 関係語彙用のキャッシュとは分ける（あちらは複数形を許容しない）
            pattern = self._term_patterns.get(term)
            if pattern is None:
                pattern = re.compile(
                    rf"(?<![0-9A-Za-z]){re.escape(term)}(?:es|s)?(?![0-9A-Za-z])",
                    re.IGNORECASE,
                )
                self._term_patterns[term] = pattern
            match = pattern.search(sentence)
            return match.start() if match else -1
        return sentence.find(term)

    def find_relation_vocab(self, sentence: str, vocab: str) -> int:
        """文中の関係語彙の出現位置を返す（見つからなければ -1）。

        英語の関係語彙は単語境界で、大文字小文字を無視して照合する。
        単純な部分文字列一致だと ``"is"`` が ``"this"`` や ``"analysis"`` に
        マッチしてしまい、無関係な語のペアから is-a エッジが大量に生まれる。
        逆に大文字小文字を区別すると、文頭の ``"Is"`` や ``"Are"`` を取りこぼす。

        ただし**複数語の語彙は左側の境界を要求しない**。PDF からのテキスト抽出で
        単語間の空白が落ちており（``"Adependencyis a kind of relationship"``）、
        左境界を課すと ``"is a kind of"`` の 84%、``"is a"`` の 81% を
        取りこぼしていた。複数語は十分に特徴的なので、左を緩めても
        誤検出は実測でゼロだった。

        単語 1 つの語彙は両側の境界を課したままにする。緩めると ``"because"``
        が ``"use"`` に、``"redefines"`` が ``"defines"`` にマッチしてしまう。

        日本語の関係語彙（「は」「である」など）は語境界の概念が使えないため、
        従来どおり部分文字列で照合する。

        Args:
            sentence: 対象の文。
            vocab: 関係語彙。

        Returns:
            int: 出現位置。見つからない場合は -1。
        """
        if vocab.isascii():
            pattern = self._vocab_patterns.get(vocab)
            if pattern is None:
                # 複数語なら左境界を課さない（PDF の空白欠落を拾うため）
                left = "" if " " in vocab else "(?<![0-9A-Za-z])"
                pattern = re.compile(
                    rf"{left}{re.escape(vocab)}(?![0-9A-Za-z])", re.IGNORECASE
                )
                self._vocab_patterns[vocab] = pattern
            match = pattern.search(sentence)
            return match.start() if match else -1
        return sentence.find(vocab)

    def _add_edges_from_sentence_analysis(
        self,
        text: str,
        candidates: List[ConceptCandidate],
        types: List[ConceptType],
        valid_entities: List[ConceptCandidate],
        merged_entities: Dict[str, ConceptCandidate]
    ) -> None:
        """
        文単位解析で関係語彙から関係タイプを自動判定してエッジを生成
        
        仕様書の原則に従い：
        - 同一入力 → 同一グラフ
        - すべての判断はif文で説明可能
        
        Args:
            text: 元のテキスト
            candidates: 全候補リスト
            types: 対応するConceptTypeのリスト
            valid_entities: 有効なエンティティのリスト
            merged_entities: 統合済みエンティティの辞書
        """
        
        # 文に分割（日本語・英語対応）
        sentences = self._split_sentences(text)
        
        # エンティティのlemmaセットを作成（高速検索用）
        entity_lemmas = set(merged_entities.keys())
        
        # 各文を解析
        logger.info(f"文解析開始: {len(sentences)}文, {len(entity_lemmas)}エンティティ, {len(config.RELATION_VOCABULARY)}関係語彙")
        start_time = perf_counter()
        
        # 関係語彙のセットを作成（早期終了用）
        relation_vocabs = set(config.RELATION_VOCABULARY.keys())
        
        # バッチ処理用: 構造制約チェックをまとめて実行
        BATCH_SIZE = 1000  # 1000エッジ追加ごとに構造制約チェック
        edges_added_since_check = 0
        
        processed_sentences = 0
        for sentence in sentences:
            # 早期終了: 文に関係語彙が含まれていない場合はスキップ
            has_relation_vocab = any(
                self.find_relation_vocab(sentence, vocab) >= 0 for vocab in relation_vocabs
            )
            if not has_relation_vocab:
                processed_sentences += 1
                if processed_sentences % 100 == 0:
                    logger.info(f"文解析進捗: {processed_sentences}/{len(sentences)}文処理完了")
                continue
            
            # エンティティ抽出を1回だけ実行（キャッシュ）
            entities_in_sentence = self._extract_entities_from_sentence(
                sentence, entity_lemmas, candidates, types
            )
            
            # エンティティが含まれていない場合はスキップ
            if not entities_in_sentence:
                processed_sentences += 1
                if processed_sentences % 100 == 0:
                    logger.info(f"文解析進捗: {processed_sentences}/{len(sentences)}文処理完了")
                continue
            
            # 関係語彙を検出
            for vocab, relation_type in config.RELATION_VOCABULARY.items():
                # 単語境界で照合する（"this" の "is" などに反応させない）
                vocab_pos = self.find_relation_vocab(sentence, vocab)
                if vocab_pos >= 0:
                    # 関係語彙の前後のエンティティを取得
                    before_entities = [
                        e for e in entities_in_sentence 
                        if e['position'] < vocab_pos
                    ]
                    after_entities = [
                        e for e in entities_in_sentence 
                        if e['position'] > vocab_pos
                    ]
                    
                    # 最も近いエンティティペアを選択
                    if before_entities and after_entities:
                        # 関係語彙に最も近いエンティティを選択
                        source = max(before_entities, key=lambda x: x['position'])['lemma']
                        target = min(after_entities, key=lambda x: x['position'])['lemma']
                        
                        # ストップワードチェック
                        if self._is_stopword(source) or self._is_stopword(target):
                            continue
                        
                        # ノードが存在するかチェック
                        if source not in self.graph or target not in self.graph:
                            continue
                        
                        # 関係タイプが許可されているかチェック
                        if relation_type not in config.ALLOWED_RELATIONS:
                            continue
                        
                        # エッジを直接追加（構造制約チェックは後でまとめて実行）
                        edge_attrs = {'relation': relation_type}
                        
                        # チャンク情報の処理（軽量化、最適化）
                        # 最適化: チャンク検索を簡略化（最初の1チャンクのみ、またはスキップ）
                        # 大規模グラフの場合はチャンク検索をスキップしてパフォーマンスを優先
                        if self.graph.number_of_edges() < 5000:
                            # 小規模グラフの場合のみチャンク検索を実行
                            if self._cached_chunks and self._cached_text and sentence in self._cached_text:
                                chunks = self._cached_chunks
                            elif self.source_chunks:
                                chunks = self.source_chunks
                            else:
                                chunks = self._split_into_chunks(sentence)
                            
                            related_chunks = self._find_chunks_for_edge(source, target, sentence, chunks)
                            if related_chunks:
                                # 最適化: 最初の3チャンクのみ保持（メモリ節約）
                                related_chunks = related_chunks[:3]
                                self.edge_to_chunks[(source, target)] = related_chunks
                                edge_attrs['source_chunks'] = related_chunks
                        
                        # エッジを追加（重複チェックのみ）
                        if not self.graph.has_edge(source, target):
                            self.graph.add_edge(source, target, **edge_attrs)
                            edges_added_since_check += 1
                            
                            # バッチサイズに達したら簡易的な構造制約チェック
                            if edges_added_since_check >= BATCH_SIZE:
                                # 自己ループのみチェック（軽量）
                                invalid_edges = [(u, v) for u, v in self.graph.edges() if u == v]
                                for u, v in invalid_edges:
                                    self.graph.remove_edge(u, v)
                                edges_added_since_check = 0
            
            processed_sentences += 1
            if processed_sentences % 100 == 0:
                logger.info(f"文解析進捗: {processed_sentences}/{len(sentences)}文処理完了")
        
        # 残りのエッジに対して簡易的な構造制約チェック
        if edges_added_since_check > 0:
            invalid_edges = [(u, v) for u, v in self.graph.edges() if u == v]
            for u, v in invalid_edges:
                self.graph.remove_edge(u, v)
        
        # 最終的な構造制約チェック（全エッジに対して1回だけ）
        # 最適化: 大規模グラフの場合は循環チェックをスキップ（パフォーマンス優先）
        if self.graph.number_of_edges() > 5000:
            logger.warning("大規模グラフのため、構造制約チェックをスキップします（パフォーマンス優先）")
        else:
            is_valid, errors = self.validator.check_structure_constraints(self.graph)
            if not is_valid:
                for error in errors:
                    logger.warning(f"構造制約違反: {error}")
        
        sentence_time = perf_counter() - start_time
        logger.info(f"文解析完了: {self.graph.number_of_edges()}エッジ追加, 所要時間: {sentence_time:.2f}秒")
        
        # 関係語彙が見つからなかった場合は共起関係ベースで補完
        if self.graph.number_of_edges() == 0:
            self._add_edges_from_cooccurrence(
                candidates, types, valid_entities, merged_entities
            )
    
    def _split_sentences(self, text: str) -> List[str]:
        """
        テキストを文に分割（日本語・英語対応）
        
        Args:
            text: 入力テキスト
            
        Returns:
            List[str]: 文のリスト
        """
        import re
        
        # 日本語の文末記号（。！？）と英語の文末記号（.!?）で分割
        # 複数の連続する文末記号も考慮
        pattern = r'[。！？.!?]+'
        sentences = re.split(pattern, text)
        
        # 空文字列を除去し、前後の空白を削除
        sentences = [s.strip() for s in sentences if s.strip()]
        
        return sentences
    
    def _extract_entities_from_sentence(
        self,
        sentence: str,
        entity_lemmas: Set[str],
        candidates: List[ConceptCandidate],
        types: List[ConceptType]
    ) -> List[Dict[str, Any]]:
        """
        文からエンティティを抽出（出現位置も記録、最適化版）
        
        Args:
            sentence: 文
            entity_lemmas: エンティティのlemmaセット
            candidates: 全候補リスト（未使用、後方互換性のため）
            types: 対応するConceptTypeのリスト（未使用、後方互換性のため）
        
        Returns:
            List[Dict]: エンティティ情報（lemma, position）のリスト
        """
        # 長い lemma から照合する。短い順に見て先着順で採ると
        # "action definition" が "action" に潰され、複合語のドメイン用語が
        # 常に一般語に負ける（旧実装は短い順＋10件で打ち切りだった）。
        entities: List[Dict[str, Any]] = []
        taken: List[Tuple[int, int]] = []

        for lemma in sorted(entity_lemmas, key=len, reverse=True):
            position = self.find_term_position(sentence, lemma)
            if position < 0:
                continue

            # 既に採用した語と文字範囲が重なる場合は飛ばす（長い語を優先）
            span = (position, position + len(lemma))
            if any(span[0] < end and start < span[1] for start, end in taken):
                continue

            taken.append(span)
            entities.append({'lemma': lemma, 'position': position})
            if len(entities) >= self.MAX_ENTITIES_PER_SENTENCE:
                break

        # 位置でソート（関係語彙の前後判定に使うため）
        entities.sort(key=lambda x: x['position'])

        return entities


"""
メインパイプライン（仕様書 3章）
全体の処理フローを統合
"""
import logging
from time import perf_counter
from typing import Optional

import networkx as nx

from .candidate_generator import CandidateGenerator
from .candidate_generator_en import CandidateGeneratorEN
from .chunk_storage import ChunkStorage
from .classifier import Classifier
from .config import GRAPHS_DIR
from .feature_estimator import FeatureEstimator
from .graph_builder import GraphBuilder
from .graph_persistence import GraphPersistence
from .language_detector import Language, LanguageDetector
from .morphological_analyzer import MorphologicalAnalyzer
from .morphological_analyzer_en import MorphologicalAnalyzerEN
from .normalizer import Normalizer
from .normalizer_en import NormalizerEN
from .ontology_validator import OntologyValidator
from .pdf_processor import PDFProcessor
from .query_engine import GraphQueryEngine

logger = logging.getLogger(__name__)


class OntologyGraphPipeline:
    """
    オントロジー駆動グラフ構築パイプライン
    
    仕様書 3章の処理フローを実装:
    1. 形態素解析（Sudachi）
    2. 概念候補生成（信用しない）
    3. ConceptCandidate 正規化（日本語依存）
    4. Feature 推定（言語非依存）
    5. 概念分類（Entity / Relation / Event / Value）
    6. オントロジー整合チェック
    7. Graph 構築
    """
    
    def __init__(self, use_llm: bool = False, chunk_storage: Optional[ChunkStorage] = None):
        """
        パイプラインを初期化
        
        Args:
            use_llm: LLMを使用するかどうか（オプション、仕様書 8章）
            chunk_storage: チャンクストレージ（Noneの場合はデフォルトを使用）
        """
        self.use_llm = use_llm
        self.language_detector = LanguageDetector()
        self.chunk_storage = chunk_storage or ChunkStorage()
        
        # 日本語用のモジュール
        self.analyzer_ja = MorphologicalAnalyzer()
        self.candidate_generator_ja = CandidateGenerator()
        self.normalizer_ja = Normalizer()
        
        # 英語用のモジュール
        try:
            self.analyzer_en = MorphologicalAnalyzerEN()
            self.candidate_generator_en = CandidateGeneratorEN()
            self.normalizer_en = NormalizerEN()
            self.english_supported = True
        except ImportError:
            # NLTKがインストールされていない場合
            self.analyzer_en = None
            self.candidate_generator_en = None
            self.normalizer_en = None
            self.english_supported = False
        
        # 言語非依存のモジュール
        self.feature_estimator = FeatureEstimator()
        self.classifier = Classifier()
        self.validator = OntologyValidator()
        self.graph_builder = GraphBuilder()
        
        # PDF処理器（オプション）
        try:
            self.pdf_processor = PDFProcessor()
            self.pdf_supported = True
        except ImportError:
            self.pdf_processor = None
            self.pdf_supported = False
    
    
    def get_statistics(self, graph: nx.DiGraph) -> dict:
        """
        グラフの統計情報を取得（仕様書 9章）
        
        Returns:
            dict: 統計情報
        """
        return {
            'node_count': graph.number_of_nodes(),
            'edge_count': graph.number_of_edges(),
            'nodes': list(graph.nodes()),
            'edges': list(graph.edges(data=True))
        }
    
    def save_graph(self, graph: nx.DiGraph, filepath: str, document_name: Optional[str] = None, format: str = 'pickle') -> None:
        """
        グラフを保存（pickle形式）
        チャンク情報はSQLite3に保存
        
        Args:
            graph: 保存するグラフ
            filepath: 保存先ファイルパス
            document_name: ドキュメント名（ファイル名など、Noneの場合はファイルパスから自動取得）
            format: 保存形式 ('pickle' のみサポート)
        """
        from pathlib import Path
        
        # ファイルパスを相対パスに正規化（グラフIDの一貫性のため、プロジェクトルート基準）
        normalized_filepath = self.chunk_storage._normalize_to_relative_path(filepath)
        
        # グラフファイルパスをグラフの属性に保存（正規化された相対パス）
        graph.graph['graph_filepath'] = normalized_filepath
        
        # ドキュメント名を取得（指定されていない場合はファイルパスから取得）
        if document_name is None:
            document_name = Path(filepath).name
        
        # グラフの属性にドキュメント名を保存
        graph.graph['document_name'] = document_name
        
        # チャンク情報をSQLite3に保存（正規化された相対パスを使用）
        graph_id = self.chunk_storage.register_graph(
            normalized_filepath,
            document_name=document_name,
            node_count=graph.number_of_nodes(),
            edge_count=graph.number_of_edges()
        )
        
        # GraphBuilderからチャンク情報を取得してSQLite3に保存
        source_chunks = self.graph_builder.get_source_chunks()
        node_to_chunks = self.graph_builder.node_to_chunks
        edge_to_chunks = self.graph_builder.edge_to_chunks
        
        # グラフIDとチャンク情報をログに出力（デバッグ用）
        logger.info(f"グラフ保存開始: graph_id={graph_id}, filepath={normalized_filepath}")
        logger.info(f"チャンク情報: source_chunks={len(source_chunks) if source_chunks else 0}, "
                   f"node_to_chunks={len(node_to_chunks) if node_to_chunks else 0}, "
                   f"edge_to_chunks={len(edge_to_chunks) if edge_to_chunks else 0}")
        
        # チャンクを保存（process_pdfで既に保存されている場合はスキップ）
        if source_chunks:
            # 既にDBに保存されているか確認
            logger.debug(f"save_graph: チャンク保存前の確認開始, graph_id={graph_id}, source_chunks数={len(source_chunks)}")
            existing_chunks = self.chunk_storage.get_chunks(graph_id)
            logger.debug(f"save_graph: 既存チャンク数={len(existing_chunks)}, graph_id={graph_id}")
            if len(existing_chunks) == 0:
                # DBに保存されていない場合のみ保存
                batch_size = 1000
                if len(source_chunks) > 10000:
                    batch_size = 500
                
                self.chunk_storage.save_chunks(graph_id, source_chunks, batch_size=batch_size)
                
                # 保存後の確認（メモリ使用量を考慮して、大きなデータの場合はスキップ）
                if len(source_chunks) < 10000:
                    saved_chunks = self.chunk_storage.get_chunks(graph_id)
                    logger.info(f"チャンク保存確認: 保存したチャンク数={len(source_chunks)}, "
                               f"データベース内のチャンク数={len(saved_chunks)}")
                    if len(saved_chunks) != len(source_chunks):
                        logger.error("チャンク保存エラー: 保存数が一致しません！")
                else:
                    logger.info(f"チャンク保存確認: 保存したチャンク数={len(source_chunks)} (確認はスキップ)")
            else:
                # 既にDBに保存されている場合はスキップ
                logger.info(f"チャンクは既にDBに保存されています: {len(existing_chunks)}チャンク（スキップ）")
            
            # メモリ最適化: 保存後にメモリから解放
            del source_chunks
            import gc
            gc.collect()
        else:
            logger.warning("source_chunksが空です。チャンクが保存されません。")
        
        if node_to_chunks:
            self.chunk_storage.save_node_chunks(graph_id, node_to_chunks)
            # メモリ最適化: 保存後にメモリから解放
            del node_to_chunks
            import gc
            gc.collect()
        
        if edge_to_chunks:
            self.chunk_storage.save_edge_chunks(graph_id, edge_to_chunks)
            # メモリ最適化: 保存後にメモリから解放
            del edge_to_chunks
            import gc
            gc.collect()
        
        # グラフ本体を保存（pickle形式、チャンク情報は含まない）
        GraphPersistence.save(graph, filepath, format)
    
    def load_graph(self, filepath: str, format: str = 'auto') -> nx.DiGraph:
        """
        グラフを読み込み（仕様書: JSON / pickle）
        
        Args:
            filepath: 読み込み元ファイルパス
            format: 読み込み形式 ('json', 'pickle', 'auto')
        
        Returns:
            nx.DiGraph: 読み込まれたグラフ
        """
        return GraphPersistence.load(filepath, format)
    
    def process(self, text: str, language: Optional[str] = None) -> nx.DiGraph:
        """
        テキストを処理してグラフを構築（テスト用）
        
        Args:
            text: 処理するテキスト
            language: 言語指定（'ja', 'en', None=自動検出）
        
        Returns:
            nx.DiGraph: 構築された知識グラフ
        """
        logger.info(f"テキスト処理開始: テキスト長: {len(text)}文字")
        
        # 言語を検出
        if language is None:
            detected_lang = self.language_detector.detect(text)
            if detected_lang == Language.ENGLISH:
                language = 'en'
            elif detected_lang == Language.JAPANESE:
                language = 'ja'
            else:
                language = 'ja'  # デフォルト
        
        # [2] 概念候補生成（信用しない）
        if language == 'en':
            if not self.english_supported:
                raise ImportError("English support requires NLTK")
            raw_candidates = self.candidate_generator_en.generate(text)
        else:
            raw_candidates = self.candidate_generator_ja.generate(text)
        
        # [3] ConceptCandidate 正規化（言語依存）
        if language == 'en':
            normalized_candidates = self.normalizer_en.normalize(raw_candidates)
        else:
            normalized_candidates = self.normalizer_ja.normalize(raw_candidates)
        
        # [4] Feature 推定（言語非依存）
        features_list = self.feature_estimator.estimate_batch(normalized_candidates)
        
        # [5] 概念分類（Entity / Relation / Event / Value）
        types = self.classifier.classify_batch(features_list)
        
        # [7] Graph 構築
        graph = self.graph_builder.build(
            normalized_candidates,
            features_list,
            types,
            text=text
        )
        
        # LLMによる補助処理（オプション）
        if self.use_llm:
            # 仕様書 8章: LLMは限定された操作のみ
            # 実装は将来拡張
            pass
        
        logger.info(f"テキスト処理完了: ノード数={graph.number_of_nodes()}, エッジ数={graph.number_of_edges()}")
        
        return graph
    
    def process_pdf(self, filepath: str, language: Optional[str] = None, pages: Optional[list] = None) -> nx.DiGraph:
        """
        PDFファイルを処理してグラフを構築し、自動的に保存
        
        Args:
            filepath: PDFファイルのパス
            language: 言語指定（'ja', 'en', None=自動検出）
            pages: 処理するページ番号のリスト（Noneの場合は全ページ）
        
        Returns:
            nx.DiGraph: 構築された知識グラフ
        """
        from pathlib import Path
        
        if not self.pdf_supported:
            raise ImportError(
                "PDF support requires pypdf or pdfplumber. "
                "Install with: pip install pypdf or pip install pdfplumber"
            )
        
        pdf_start = perf_counter()
        logger.info(f"PDF処理開始: {filepath}, ページ: {pages if pages else '全ページ'}")
        
        # PDFからテキストを抽出
        start_time = perf_counter()
        text = self.pdf_processor.extract_text(filepath, pages=pages)
        extract_time = perf_counter() - start_time
        logger.info(f"PDFテキスト抽出完了: {len(text)}文字, 所要時間: {extract_time:.2f}秒")
        
        # ドキュメント名を取得（ファイル名）
        document_name = Path(filepath).name
        
        # 保存先ファイルパスを自動生成（常に GraphRAG/data/graphs/{PDFファイル名}.pkl）
        graphs_dir = GRAPHS_DIR
        graphs_dir.mkdir(parents=True, exist_ok=True)
        # PDFファイル名から拡張子を除いて.pklに変更
        pdf_name = Path(filepath).stem
        output_filepath = str(graphs_dir / f"{pdf_name}.pkl")
        
        # グラフIDを事前に生成（チャンク保存に必要）
        normalized_filepath = self.chunk_storage._normalize_to_relative_path(output_filepath)
        graph_id = self.chunk_storage.register_graph(
            normalized_filepath,
            document_name=document_name,
            node_count=0,  # まだグラフは構築されていない
            edge_count=0
        )
        logger.info(f"グラフIDを事前生成: {graph_id}, filepath={normalized_filepath}")
        
        # テキストをチャンクに分割してDBに保存（グラフ構築の前）
        chunk_start = perf_counter()
        logger.info(f"チャンク分割開始: テキスト長: {len(text)}文字")
        chunks = self.graph_builder._split_into_chunks(text)
        chunk_time = perf_counter() - chunk_start
        logger.info(f"チャンク分割完了: {len(chunks)}チャンク, 所要時間: {chunk_time:.2f}秒")
        
        # チャンクをDBに保存（グラフ構築の前に確実に保存）
        save_chunks_start = perf_counter()
        logger.info(f"チャンクをDBに保存開始: {len(chunks)}チャンク")
        batch_size = 1000
        if len(chunks) > 10000:
            batch_size = 500
        self.chunk_storage.save_chunks(graph_id, chunks, batch_size=batch_size)
        save_chunks_time = perf_counter() - save_chunks_start
        logger.info(f"チャンクをDBに保存完了: 所要時間: {save_chunks_time:.2f}秒")
        
        # GraphBuilderのsource_chunksに設定（グラフ構築時に使用）
        self.graph_builder.source_chunks = chunks.copy()
        
        # テキストを処理（内部処理）
        process_start = perf_counter()
        logger.info(f"テキスト処理開始: テキスト長: {len(text)}文字")
        
        # 言語を検出
        start_time = perf_counter()
        if language is None:
            detected_lang = self.language_detector.detect(text)
            if detected_lang == Language.ENGLISH:
                language = 'en'
            elif detected_lang == Language.JAPANESE:
                language = 'ja'
            else:
                # デフォルトは日本語
                language = 'ja'
        detect_time = perf_counter() - start_time
        logger.info(f"言語検出完了: {language}, 所要時間: {detect_time:.2f}秒")
        
        # [1] 形態素解析
        # 注意: 出力は正解として扱わない（仕様書 5.1）
        
        # [2] 概念候補生成（信用しない）
        start_time = perf_counter()
        if language == 'en':
            if not self.english_supported:
                raise ImportError(
                    "English support requires NLTK. "
                    "Install with: pip install nltk"
                )
            raw_candidates = self.candidate_generator_en.generate(text)
        else:
            # 日本語（デフォルト）
            raw_candidates = self.candidate_generator_ja.generate(text)
        candidate_time = perf_counter() - start_time
        logger.info(f"概念候補生成完了: {len(raw_candidates)}候補, 所要時間: {candidate_time:.2f}秒")
        
        # [3] ConceptCandidate 正規化（言語依存）
        start_time = perf_counter()
        if language == 'en':
            normalized_candidates = self.normalizer_en.normalize(raw_candidates)
        else:
            normalized_candidates = self.normalizer_ja.normalize(raw_candidates)
        normalize_time = perf_counter() - start_time
        logger.info(f"正規化完了: {len(normalized_candidates)}候補, 所要時間: {normalize_time:.2f}秒")
        
        # [4] Feature 推定（言語非依存）
        start_time = perf_counter()
        features_list = self.feature_estimator.estimate_batch(normalized_candidates)
        feature_time = perf_counter() - start_time
        logger.info(f"Feature推定完了: {len(features_list)}特徴, 所要時間: {feature_time:.2f}秒")
        
        # [5] 概念分類（Entity / Relation / Event / Value）
        start_time = perf_counter()
        types = self.classifier.classify_batch(features_list)
        classify_time = perf_counter() - start_time
        logger.info(f"概念分類完了: 所要時間: {classify_time:.2f}秒")
        
        # [6] オントロジー整合チェック
        # （GraphBuilder内で実行）
        
        # [7] Graph 構築
        # 注意: source_chunksは既にDBに保存済みなので、グラフ構築時には参照IDだけ使用
        graph = self.graph_builder.build(
            normalized_candidates,
            features_list,
            types,
            text=text  # 元のテキストを渡す（ノード-チャンク関連の構築のため）
        )
        
        # チャンク情報はSQLite3に保存するため、グラフの属性には保存しない
        # グラフファイルパスとドキュメント名は save_graph で設定される
        # 注意: source_chunksは既にDBに保存済み
        
        # LLMによる補助処理（オプション）
        if self.use_llm:
            # 仕様書 8章: LLMは限定された操作のみ
            # 実装は将来拡張
            pass
        
        process_time = perf_counter() - process_start
        logger.info(f"テキスト処理完了: 総所要時間: {process_time:.2f}秒")
        
        # メモリ最適化: 処理済みデータを解放
        del raw_candidates
        del normalized_candidates
        del features_list
        del types
        import gc
        gc.collect()
        logger.debug("メモリ最適化: 処理済みデータを解放しました")
        
        # グラフを自動保存（SQLite3とpickle形式）
        save_start = perf_counter()
        self.save_graph(graph, output_filepath, document_name=document_name, format='pickle')
        save_time = perf_counter() - save_start
        logger.info(f"グラフ保存完了: {output_filepath}, 所要時間: {save_time:.2f}秒")
        
        # メモリ最適化: テキストを解放（グラフ構築後は不要）
        del text
        gc.collect()
        logger.debug("メモリ最適化: テキストデータを解放しました")
        
        total_time = perf_counter() - pdf_start
        logger.info(f"PDF処理完了: 総所要時間: {total_time:.2f}秒")
        
        return graph
    
    def get_pdf_metadata(self, filepath: str) -> dict:
        """
        PDFファイルのメタデータを取得
        
        Args:
            filepath: PDFファイルのパス
        
        Returns:
            dict: メタデータ
        """
        if not self.pdf_supported:
            raise ImportError(
                "PDF support requires pypdf or pdfplumber. "
                "Install with: pip install pypdf or pip install pdfplumber"
            )
        
        return self.pdf_processor.get_metadata(filepath)
    
    def create_query_engine(self, graph: nx.DiGraph) -> GraphQueryEngine:
        """
        GraphQueryEngineを作成
        
        Args:
            graph: 検索対象のグラフ
        
        Returns:
            GraphQueryEngine: クエリエンジン
        """
        return GraphQueryEngine(graph)
    
    def compare_graphs(self, graph1: nx.DiGraph, graph2: nx.DiGraph) -> dict:
        """
        2つのグラフを比較（グラフ安定度の計算、仕様書 9章）
        
        Args:
            graph1: 比較するグラフ1
            graph2: 比較するグラフ2
        
        Returns:
            dict: 比較結果（グラフ安定度を含む）
        """
        return GraphPersistence.compare_graphs(graph1, graph2)


def main():
    """使用例"""
    # パイプラインを初期化
    pipeline = OntologyGraphPipeline(use_llm=False)
    
    # 日本語サンプルテキスト
    sample_text_ja = """
    システムの要求仕様を定義する。
    設計は制約を満たす必要がある。
    コンポーネントAはコンポーネントBに依存する。
    """
    
    print("=== 日本語テキストの処理 ===")
    graph_ja = pipeline.process(sample_text_ja)
    stats_ja = pipeline.get_statistics(graph_ja)
    print(f"ノード数: {stats_ja['node_count']}")
    print(f"エッジ数: {stats_ja['edge_count']}")
    print(f"ノード: {stats_ja['nodes']}")
    
    # 英語サンプルテキスト
    if pipeline.english_supported:
        print("\n=== 英語テキストの処理 ===")
        sample_text_en = """
        System requirements are defined.
        Design must satisfy constraints.
        Component A depends on Component B.
        """
        graph_en = pipeline.process(sample_text_en)
        stats_en = pipeline.get_statistics(graph_en)
        print(f"ノード数: {stats_en['node_count']}")
        print(f"エッジ数: {stats_en['edge_count']}")
        print(f"ノード: {stats_en['nodes']}")
    else:
        print("\n英語サポートは利用できません（NLTKが必要です）")


if __name__ == "__main__":
    main()


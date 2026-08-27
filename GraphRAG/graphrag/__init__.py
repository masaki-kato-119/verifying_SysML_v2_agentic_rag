"""
オントロジー駆動GraphRAGパイプライン

**公開契約について**: このプロジェクトの公開インターフェースは
``GraphRAG/mcp_server.py``（MCPサーバー、stdio経由）です。この ``graphrag``
パッケージ（本ファイルが再エクスポートする一部のクラス以外の、
normalizer/candidate_generator/query_expander等の約25モジュール）は
内部実装であり、モジュール構成・関数シグネチャの安定性は保証されません。
"""
from .datamodels import POS, ConceptCandidate, ConceptFeatures, ConceptType
from .graph_persistence import GraphPersistence
from .pipeline import OntologyGraphPipeline
from .query_engine import GraphQueryEngine

__all__ = [
    'OntologyGraphPipeline',
    'ConceptCandidate',
    'ConceptFeatures',
    'ConceptType',
    'POS',
    'GraphPersistence',
    'GraphQueryEngine',
]

__version__ = '1.0.0'


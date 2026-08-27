"""HybridSearchResult: ハイブリッド検索1件分の結果レコード。

search.py / search_scoring.py / search_diversity.py / search_graph_augment.py
の全てから参照されるため、循環importを避けて独立モジュールに置く。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class HybridSearchResult:
    """ハイブリッド検索の結果レコード。

    ベクトル検索・メタ検索どちらか一方、または両方からスコアを持ちます。

    Attributes:
        chunk_id: チャンクの一意識別子。
        text: チャンクのテキスト内容。
        metadata: メタデータの辞書。
        score_vector: ベクトル検索スコア（0.0〜1.0）。
        score_meta: メタ検索スコア（0.0〜1.0）。
        score_hybrid: ハイブリッドスコア（重み付き和）。
        score_rerank: Cross-Encoderによるリランキングスコア（オプション）。
    """

    chunk_id: str
    text: str
    metadata: Dict[str, Any]
    score_vector: float = 0.0
    score_meta: float = 0.0
    score_hybrid: float = 0.0
    # Cross-Encoder によるリランキングスコア（オプション）
    score_rerank: float = 0.0

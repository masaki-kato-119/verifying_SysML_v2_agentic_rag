"""
Evidence Extractor（証拠抽出器）
ノード/エッジから参照元テキストを小さく返す「根拠抜粋」機能
"""
import re
from typing import Dict, List, Optional, Set

from .chunk_storage import ChunkStorage


class EvidenceExtractor:
    """
    証拠抽出器
    
    ノード/エッジに関連する根拠情報を要約・抜粋する機能を提供
    """
    
    def __init__(self, chunk_storage: ChunkStorage):
        """
        証拠抽出器を初期化
        
        Args:
            chunk_storage: チャンクストレージ
        """
        self.chunk_storage = chunk_storage
    
    def extract_evidence_summary(
        self,
        graph_id: str,
        node_name: Optional[str] = None,
        edge_key: Optional[tuple] = None,
        max_chunk_length: int = 200,
        highlight_terms: Optional[List[str]] = None,
        max_chunks: int = 3
    ) -> Dict:
        """
        ノード/エッジに関連する根拠情報を要約
        
        Args:
            graph_id: グラフID
            node_name: ノード名（ノードの根拠を取得する場合）
            edge_key: エッジキー（source, target）（エッジの根拠を取得する場合）
            max_chunk_length: チャンクの最大文字数
            highlight_terms: ハイライトする用語のリスト
            max_chunks: 最大チャンク数
        
        Returns:
            dict: 根拠要約情報
        """
        try:
            # チャンクIDを取得
            chunk_ids = []
            if node_name:
                chunk_ids = self.chunk_storage.get_node_chunks(graph_id, node_name)
            elif edge_key and len(edge_key) >= 2:
                chunk_ids = self.chunk_storage.get_edge_chunks(graph_id, edge_key[0], edge_key[1])
            
            if not chunk_ids:
                return {
                    "success": True,
                    "evidence_type": "node" if node_name else "edge",
                    "target": node_name or edge_key,
                    "summaries": [],
                    "total_chunks": 0,
                    "message": "関連するチャンクが見つかりませんでした"
                }
            
            # チャンクを取得（最大数まで）
            limited_chunk_ids = chunk_ids[:max_chunks]
            chunks = self.chunk_storage.get_chunks(graph_id, limited_chunk_ids)
            
            # 要約を生成
            summaries = []
            for chunk_id, chunk_text in chunks.items():
                summary = self._create_chunk_summary(
                    chunk_id=chunk_id,
                    chunk_text=chunk_text,
                    max_length=max_chunk_length,
                    highlight_terms=highlight_terms,
                    target_term=node_name if node_name else (
                        f"{edge_key[0]}-{edge_key[1]}" if edge_key else None
                    )
                )
                summaries.append(summary)
            
            return {
                "success": True,
                "evidence_type": "node" if node_name else "edge",
                "target": node_name or edge_key,
                "summaries": summaries,
                "total_chunks": len(chunk_ids),
                "shown_chunks": len(summaries),
                "reference_ids": {
                    "graph_id": graph_id,
                    "node_name": node_name,
                    "edge_key": edge_key,
                    "chunk_ids": limited_chunk_ids
                }
            }
        
        except Exception as e:  # noqa: BLE001 - チャンク取得〜要約生成の複数処理をまとめてAPI応答（success/error）に変換するため意図的に広く捕捉
            return {
                "success": False,
                "error": str(e),
                "evidence_type": "node" if node_name else "edge",
                "target": node_name or edge_key
            }
    
    def _create_chunk_summary(
        self,
        chunk_id: str,
        chunk_text: str,
        max_length: int,
        highlight_terms: Optional[List[str]] = None,
        target_term: Optional[str] = None
    ) -> Dict:
        """
        チャンクの要約を作成
        
        Args:
            chunk_id: チャンクID
            chunk_text: チャンクテキスト
            max_length: 最大文字数
            highlight_terms: ハイライトする用語のリスト
            target_term: ターゲット用語（ノード名やエッジ名）
        
        Returns:
            dict: チャンク要約
        """
        # ハイライト用語を準備
        terms_to_highlight = set()
        if highlight_terms:
            terms_to_highlight.update(highlight_terms)
        if target_term:
            terms_to_highlight.add(target_term)
        
        # 関連部分を抽出
        relevant_text = self._extract_relevant_text(
            chunk_text, 
            terms_to_highlight, 
            max_length
        )
        
        # ハイライトを適用
        highlighted_text = self._apply_highlights(relevant_text, terms_to_highlight)
        
        return {
            "chunk_id": chunk_id,
            "summary_text": highlighted_text,
            "original_length": len(chunk_text),
            "summary_length": len(relevant_text),
            "highlighted_terms": list(terms_to_highlight),
            "is_truncated": len(chunk_text) > max_length
        }
    
    def _extract_relevant_text(
        self, 
        text: str, 
        terms: Set[str], 
        max_length: int
    ) -> str:
        """
        関連する部分のテキストを抽出
        
        Args:
            text: 元のテキスト
            terms: 関連用語のセット
            max_length: 最大文字数
        
        Returns:
            str: 抽出されたテキスト
        """
        if len(text) <= max_length:
            return text
        
        # 関連用語が含まれる位置を検索
        term_positions = []
        for term in terms:
            if not term:
                continue
            # 大文字小文字を無視して検索
            for match in re.finditer(re.escape(term), text, re.IGNORECASE):
                term_positions.append((match.start(), match.end()))
        
        if not term_positions:
            # 関連用語が見つからない場合は先頭から切り取り
            return text[:max_length] + "..." if len(text) > max_length else text
        
        # 最初の関連用語の位置を中心に抽出
        first_pos = min(term_positions, key=lambda x: x[0])
        start_pos = max(0, first_pos[0] - max_length // 3)
        end_pos = min(len(text), start_pos + max_length)
        
        # 文の境界で調整（可能であれば）
        extracted = text[start_pos:end_pos]
        
        # 前後に省略記号を追加
        if start_pos > 0:
            extracted = "..." + extracted
        if end_pos < len(text):
            extracted = extracted + "..."
        
        return extracted
    
    def _apply_highlights(self, text: str, terms: Set[str]) -> str:
        """
        テキストにハイライトを適用
        
        Args:
            text: テキスト
            terms: ハイライトする用語のセット
        
        Returns:
            str: ハイライト適用済みテキスト
        """
        highlighted = text
        
        # 用語の長さでソート（長い用語から処理して重複を避ける）
        sorted_terms = sorted([term for term in terms if term], key=len, reverse=True)
        
        for term in sorted_terms:
            # 大文字小文字を無視してハイライト
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            highlighted = pattern.sub(f"**{term}**", highlighted)
        
        return highlighted
    
    def get_enhanced_source_text(
        self,
        graph_id: str,
        node_name: str,
        max_chunks: int = 5,
        max_chunk_length: int = 200,
        return_format: str = "summary",
        highlight_terms: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        強化されたソーステキスト取得
        
        Args:
            graph_id: グラフID
            node_name: ノード名
            max_chunks: 最大チャンク数
            max_chunk_length: チャンクの最大文字数
            return_format: 返却形式（'summary' | 'full'）
            highlight_terms: ハイライトする用語のリスト
        
        Returns:
            List[Dict]: 強化されたソーステキストのリスト
        """
        try:
            # チャンクIDを取得
            chunk_ids = self.chunk_storage.get_node_chunks(graph_id, node_name)
            
            if not chunk_ids:
                return []
            
            # チャンクを取得（最大数まで）
            limited_chunk_ids = chunk_ids[:max_chunks]
            chunks = self.chunk_storage.get_chunks(graph_id, limited_chunk_ids)
            
            # 強化されたソーステキストを生成
            enhanced_texts = []
            for chunk_id, chunk_text in chunks.items():
                if return_format == "summary":
                    # 要約形式
                    summary = self._create_chunk_summary(
                        chunk_id=chunk_id,
                        chunk_text=chunk_text,
                        max_length=max_chunk_length,
                        highlight_terms=highlight_terms,
                        target_term=node_name
                    )
                    enhanced_texts.append({
                        "chunk_id": chunk_id,
                        "text": summary["summary_text"],
                        "is_summary": True,
                        "original_length": summary["original_length"],
                        "highlighted_terms": summary["highlighted_terms"]
                    })
                else:
                    # 全文形式
                    highlighted_text = self._apply_highlights(
                        chunk_text, 
                        set(highlight_terms or []) | {node_name}
                    )
                    enhanced_texts.append({
                        "chunk_id": chunk_id,
                        "text": highlighted_text,
                        "is_summary": False,
                        "original_length": len(chunk_text),
                        "highlighted_terms": list(set(highlight_terms or []) | {node_name})
                    })
            
            return enhanced_texts

        # チャンク取得〜ハイライト生成の複数処理をまとめてベストエフォート化するため意図的に広く捕捉
        except Exception:  # noqa: BLE001
            return []

    def get_enhanced_edge_source_text(
        self,
        graph_id: str,
        source: str,
        target: str,
        max_chunks: int = 5,
        max_chunk_length: int = 200,
        return_format: str = "summary",
        highlight_terms: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        強化されたエッジソーステキスト取得
        
        Args:
            graph_id: グラフID
            source: ソースノード名
            target: ターゲットノード名
            max_chunks: 最大チャンク数
            max_chunk_length: チャンクの最大文字数
            return_format: 返却形式（'summary' | 'full'）
            highlight_terms: ハイライトする用語のリスト
        
        Returns:
            List[Dict]: 強化されたエッジソーステキストのリスト
        """
        try:
            # チャンクIDを取得
            chunk_ids = self.chunk_storage.get_edge_chunks(graph_id, source, target)
            
            if not chunk_ids:
                return []
            
            # チャンクを取得（最大数まで）
            limited_chunk_ids = chunk_ids[:max_chunks]
            chunks = self.chunk_storage.get_chunks(graph_id, limited_chunk_ids)
            
            # 強化されたエッジソーステキストを生成
            enhanced_texts = []
            edge_terms = {source, target}
            if highlight_terms:
                edge_terms.update(highlight_terms)
            
            for chunk_id, chunk_text in chunks.items():
                if return_format == "summary":
                    # 要約形式
                    summary = self._create_chunk_summary(
                        chunk_id=chunk_id,
                        chunk_text=chunk_text,
                        max_length=max_chunk_length,
                        highlight_terms=list(edge_terms),
                        target_term=f"{source}-{target}"
                    )
                    enhanced_texts.append({
                        "chunk_id": chunk_id,
                        "text": summary["summary_text"],
                        "is_summary": True,
                        "original_length": summary["original_length"],
                        "highlighted_terms": summary["highlighted_terms"]
                    })
                else:
                    # 全文形式
                    highlighted_text = self._apply_highlights(chunk_text, edge_terms)
                    enhanced_texts.append({
                        "chunk_id": chunk_id,
                        "text": highlighted_text,
                        "is_summary": False,
                        "original_length": len(chunk_text),
                        "highlighted_terms": list(edge_terms)
                    })
            
            return enhanced_texts

        # チャンク取得〜ハイライト生成の複数処理をまとめてベストエフォート化するため意図的に広く捕捉
        except Exception:  # noqa: BLE001
            return []
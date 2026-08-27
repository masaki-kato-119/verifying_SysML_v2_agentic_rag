"""
ノード要約機能（Phase 5）

断片的な情報を統合し、理解しやすい要約を生成
LLM-based 要約・統合機能を実装
"""
import logging
from typing import Dict, List, Optional

import networkx as nx

from . import config
from .chunk_storage import ChunkStorage

logger = logging.getLogger(__name__)


class NodeSummarizer:
    """
    ノード要約機能
    
    断片的な情報を統合し、理解しやすい要約を生成
    """
    
    def __init__(
        self, 
        graph: nx.DiGraph,
        chunk_storage: Optional[ChunkStorage] = None,
        llm_client: Optional[object] = None
    ):
        """
        ノード要約機能を初期化
        
        Args:
            graph: 対象のグラフ
            chunk_storage: チャンクストレージ
            llm_client: LLMクライアント（Noneの場合は簡易版を使用）
        """
        self.graph = graph
        self.chunk_storage = chunk_storage
        self.llm_client = llm_client
        self.summary_cache = {}
    
    def summarize_node(
        self, 
        node_name: str, 
        summary_type: str = "overview",
        max_chunks: int = 10
    ) -> Dict:
        """
        ノードの要約を生成
        
        Args:
            node_name: ノード名
            summary_type: 要約タイプ（overview/detailed/technical）
            max_chunks: 最大チャンク数
        
        Returns:
            Dict: 要約情報
        """
        if node_name not in self.graph.nodes():
            return {
                'node': node_name,
                'summary': f"ノード '{node_name}' が見つかりませんでした。",
                'summary_type': summary_type,
                'error': 'node_not_found'
            }
        
        # キャッシュチェック
        cache_key = f"{node_name}_{summary_type}"
        if cache_key in self.summary_cache:
            return self.summary_cache[cache_key]
        
        # 1. ソーステキスト取得
        source_chunks = self._get_source_chunks(node_name, max_chunks)
        
        # 2. 関連ノード情報取得
        related_info = self._get_related_nodes_info(node_name)
        
        # 3. 要約生成（LLMが利用可能な場合はLLM、そうでない場合は簡易版）
        if self.llm_client:
            summary = self._generate_summary_with_llm(
                node_name, 
                source_chunks, 
                related_info, 
                summary_type
            )
        else:
            summary = self._generate_summary_simple(
                node_name,
                source_chunks,
                related_info,
                summary_type
            )
        
        # 4. 結果をキャッシュして返却
        result = {
            'node': node_name,
            'summary': summary,
            'summary_type': summary_type,
            'source_chunks_count': len(source_chunks),
            'related_nodes': related_info['nodes'],
            'confidence': self._calculate_confidence(source_chunks)
        }
        
        self.summary_cache[cache_key] = result
        return result
    
    def _get_source_chunks(self, node_name: str, max_chunks: int) -> List[str]:
        """
        ノードのソースチャンクを取得
        
        Args:
            node_name: ノード名
            max_chunks: 最大チャンク数
        
        Returns:
            List[str]: ソースチャンクのリスト
        """
        if not self.chunk_storage:
            logger.debug(f"ソースチャンク取得: chunk_storageが設定されていません。node_name={node_name}")
            return []
        
        try:
            # グラフIDを取得（複数の方法を試す）
            graph_id = self.graph.graph.get('graph_id')
            
            # graph_idが見つからない場合、graph_filepathから生成を試みる
            if not graph_id:
                graph_filepath = self.graph.graph.get('graph_filepath')
                if graph_filepath:
                    # ChunkStorageのメソッドを使ってgraph_idを取得
                    graph_id = self.chunk_storage.get_graph_id(graph_filepath)
                    logger.debug(f"ソースチャンク取得: graph_filepathからgraph_idを取得しました。graph_id={graph_id}")
            
            if not graph_id:
                logger.warning(f"ソースチャンク取得: graph_idが見つかりません。node_name={node_name}, graph_attrs={list(self.graph.graph.keys())}")
                return []
            
            # チャンクIDを取得
            chunk_ids = self.chunk_storage.get_node_chunks(graph_id, node_name)
            if not chunk_ids:
                logger.debug(f"ソースチャンク取得: チャンクIDが見つかりませんでした。node_name={node_name}, graph_id={graph_id}")
                return []
            
            logger.debug(f"ソースチャンク取得: {len(chunk_ids)}個のチャンクIDを取得しました。node_name={node_name}")
            
            # チャンクを取得
            chunks = self.chunk_storage.get_chunks(graph_id, chunk_ids[:max_chunks])
            result = list(chunks.values())
            logger.debug(f"ソースチャンク取得: {len(result)}個のチャンクを取得しました。node_name={node_name}")
            return result
        # chunk_storageはテスト・利用先で差し替え可能なインターフェースであり、
        # 実装依存の様々な例外（DB以外のバックエンドを含む）を返しうるため意図的に広く捕捉する
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ソースチャンク取得エラー: {e}, node_name={node_name}")
            import traceback
            logger.debug(traceback.format_exc())
            return []
    
    def _get_related_nodes_info(self, node_name: str) -> Dict:
        """
        関連ノード情報を取得
        
        Args:
            node_name: ノード名
        
        Returns:
            Dict: 関連ノード情報
        """
        neighbors = list(self.graph.neighbors(node_name))
        predecessors = list(self.graph.predecessors(node_name))
        
        return {
            'nodes': neighbors[:10] + predecessors[:10],  # 最大10個ずつ
            'neighbor_count': len(neighbors),
            'predecessor_count': len(predecessors)
        }
    
    def _generate_summary_with_llm(
        self, 
        node_name: str, 
        source_chunks: List[str], 
        related_info: Dict, 
        summary_type: str
    ) -> str:
        """
        LLMで要約を生成
        
        Args:
            node_name: ノード名
            source_chunks: ソースチャンク
            related_info: 関連ノード情報
            summary_type: 要約タイプ
        
        Returns:
            str: 生成された要約
        """
        # 要約タイプ別のプロンプト
        prompts = {
            "overview": f"""
以下の情報から、{node_name}について簡潔に要約してください：

【元テキスト】
{chr(10).join(source_chunks[:5])}

【関連概念】
{', '.join(related_info['nodes'][:5])}

【要求】
- 3-5文で簡潔に
- 専門用語は分かりやすく説明
- 最も重要な特徴を強調

要約:
""",
            "detailed": f"""
以下の情報から、{node_name}について詳細に説明してください：

【元テキスト】
{chr(10).join(source_chunks[:10])}

【関連概念】
{', '.join(related_info['nodes'][:10])}

【要求】
- 定義、特徴、用途を含む
- 関連概念との関係を説明
- 具体例があれば含める

詳細説明:
""",
            "technical": f"""
以下の情報から、{node_name}の技術的詳細をまとめてください：

【元テキスト】
{chr(10).join(source_chunks[:10])}

【関連概念】
{', '.join(related_info['nodes'][:10])}

【要求】
- 技術仕様に焦点
- 制約や制限事項を含む
- 実装上の注意点があれば含める

技術詳細:
"""
        }
        
        prompt = prompts.get(summary_type, prompts["overview"])
        
        try:
            # LLMクライアントがgenerateメソッドを持つことを想定
            if hasattr(self.llm_client, 'generate'):
                return self.llm_client.generate(prompt)
            elif hasattr(self.llm_client, 'chat') and hasattr(self.llm_client.chat, 'completions'):
                # OpenAI API形式
                response = self.llm_client.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "あなたは技術文書の要約を生成する専門家です。"},
                        {"role": "user", "content": prompt}
                    ],
                    # reasoning モデルは temperature 非対応、max_tokens も使えない。
                    # reasoning トークン分の余裕を見て予算を広げている。
                    reasoning_effort="low",
                    max_completion_tokens=1200,
                )
                return response.choices[0].message.content
            else:
                # LLMが利用できない場合は簡易版にフォールバック
                return self._generate_summary_simple(node_name, source_chunks, related_info, summary_type)
        except Exception as e:  # noqa: BLE001 - LLM API呼び出しの失敗理由を問わず簡易版フォールバックに委ねるため意図的に広く捕捉
            logger.warning(f"LLM要約生成エラー: {e}。簡易版にフォールバックします。")
            return self._generate_summary_simple(node_name, source_chunks, related_info, summary_type)
    
    def _generate_summary_simple(
        self,
        node_name: str,
        source_chunks: List[str],
        related_info: Dict,
        summary_type: str
    ) -> str:
        """
        簡易版要約生成（LLMなし、改善版）
        
        Args:
            node_name: ノード名
            source_chunks: ソースチャンク
            related_info: 関連ノード情報
            summary_type: 要約タイプ
        
        Returns:
            str: 生成された要約
        """
        if not source_chunks:
            # ソースチャンクがない場合でも、関連ノード情報から推論
            if related_info['nodes']:
                related_text = ', '.join(related_info['nodes'][:5])
                return f"{node_name}は、{related_text}などの概念と関連しています。詳細な情報はソーステキストから取得できませんでした。"
            return f"{node_name}に関する情報が見つかりませんでした。"
        
        # チャンクから重要な情報を抽出（改善版）
        # 1. ノード名を含む文を優先的に抽出
        relevant_sentences = []
        for chunk in source_chunks[:3]:  # 最大3チャンク
            sentences = chunk.split('.')
            for sentence in sentences:
                sentence = sentence.strip()
                if node_name.lower() in sentence.lower() and len(sentence) > 20:
                    relevant_sentences.append(sentence)
                    if len(relevant_sentences) >= 3:
                        break
            if len(relevant_sentences) >= 3:
                break
        
        # 2. 要約タイプに応じた情報量を調整
        if summary_type == "overview":
            # 概要版: 最初のチャンクから重要な部分を抽出
            if relevant_sentences:
                preview = '. '.join(relevant_sentences[:2]) + '.'
            else:
                preview = source_chunks[0][:300] if len(source_chunks[0]) > 300 else source_chunks[0]
            
            related_text = ""
            if related_info['nodes']:
                related_text = f" 関連概念には{', '.join(related_info['nodes'][:5])}などがあります。"
            
            summary = f"{node_name}について: {preview}{related_text}"
        
        elif summary_type == "detailed":
            # 詳細版: 複数チャンクから情報を統合
            if relevant_sentences:
                main_text = '. '.join(relevant_sentences[:4]) + '.'
            else:
                main_text = source_chunks[0][:400] if len(source_chunks[0]) > 400 else source_chunks[0]
            
            additional_info = ""
            if len(source_chunks) > 1:
                additional_chunks = [chunk[:150] for chunk in source_chunks[1:3] if chunk]
                if additional_chunks:
                    additional_info = f" 追加情報: {' '.join(additional_chunks)}"
            
            related_text = ""
            if related_info['nodes']:
                related_text = f" 関連概念: {', '.join(related_info['nodes'][:8])}。"
            
            summary = f"{node_name}について: {main_text}{additional_info}{related_text}"
        
        else:  # technical
            # 技術版: 定義や仕様に焦点
            if relevant_sentences:
                technical_text = '. '.join(relevant_sentences[:3]) + '.'
            else:
                technical_text = source_chunks[0][:350] if len(source_chunks[0]) > 350 else source_chunks[0]
            
            related_text = ""
            if related_info['nodes']:
                related_text = f" 関連する技術概念: {', '.join(related_info['nodes'][:5])}。"
            
            summary = f"{node_name}の技術的詳細: {technical_text}{related_text}"
        
        return summary
    
    def _calculate_confidence(self, source_chunks: List[str]) -> float:
        """
        要約の信頼度を計算
        
        Args:
            source_chunks: ソースチャンク
        
        Returns:
            float: 信頼度（0.0-1.0）
        """
        if not source_chunks:
            return 0.0
        
        # チャンク数に基づく信頼度
        chunk_count = len(source_chunks)
        if chunk_count >= 5:
            return 0.9
        elif chunk_count >= 3:
            return 0.7
        elif chunk_count >= 1:
            return 0.5
        else:
            return 0.0

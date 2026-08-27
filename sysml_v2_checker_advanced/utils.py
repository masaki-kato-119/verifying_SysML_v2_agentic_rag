"""
SysML v2 Advanced Checker Utilities

ユーティリティ関数
"""

import json
from typing import Any, Dict


def ast_to_json(ast: Dict, pretty: bool = True) -> str:
    """
    ASTをJSON文字列に変換（RAG + GPT統合用）

    ASTから位置情報を除外し、JSON形式に変換します。
    RAGシステムやGPTに渡すために使用します。

    Args:
        ast: パース済みのAST
        pretty: Trueの場合、インデント付きで整形

    Returns:
        JSON文字列
    """
    def clean_node(node: Any) -> Any:
        """
        再帰的にノードをクリーンアップ

        位置情報（line, column等）を除外します。

        Args:
            node: クリーンアップするノード

        Returns:
            クリーンアップされたノード
        """
        if isinstance(node, dict):
            result = {}
            for key, value in node.items():
                # 位置情報は除外
                if key not in ["line", "column", "end_line", "end_column"]:
                    result[key] = clean_node(value)
            return result
        elif isinstance(node, list):
            return [clean_node(item) for item in node]
        elif isinstance(node, (str, int, float, bool, type(None))):
            return node
        else:
            # その他のオブジェクトは文字列に変換
            return str(node)

    cleaned = clean_node(ast)
    if pretty:
        return json.dumps(cleaned, indent=2, ensure_ascii=False)
    else:
        return json.dumps(cleaned, ensure_ascii=False)
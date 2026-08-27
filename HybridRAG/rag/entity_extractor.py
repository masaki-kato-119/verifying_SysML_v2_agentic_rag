"""エンティティ自動抽出モジュール（GraphRAG拡張機能用）。

このモジュールは、ドキュメントからConstraint、SyntaxRule、SpecClause、Termを
自動的に抽出する機能を提供します。

抽出方法:
1. LLMを使った抽出: チャンクのテキストから構造化されたエンティティを抽出
2. パーサーを使った抽出: 構造化されたドキュメント（特に仕様書）から自動抽出
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from .config import OPENAI_TIMEOUT_SECONDS, require_openai_api_key

logger = logging.getLogger(__name__)

# エンティティ抽出用のデフォルトモデル（軽量モデルを推奨）
DEFAULT_ENTITY_EXTRACTION_MODEL = os.getenv("RAG_ENTITY_EXTRACTION_MODEL", "gpt-5.6-luna")

# OpenAI SDKのインポート（オプション）
try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = None


def extract_entities_with_llm(
    chunks: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    max_constraints: int = 20,
    max_syntax_rules: int = 20,
    max_spec_clauses: int = 20,
    max_terms: int = 20,
) -> Dict[str, List[Dict[str, Any]]]:
    """LLMを使ってチャンクからエンティティ（Constraint, SyntaxRule, SpecClause, Term）を抽出する。

    Args:
        chunks: チャンク情報のリスト。各要素は以下のキーを含む:
            - chunk_id: チャンクID（例: "doc1::chunk-0"）
            - text: チャンクのテキスト内容
            - metadata: 追加メタデータ（オプション）
        model: 使用するLLMモデル名（デフォルト: 環境変数 RAG_ENTITY_EXTRACTION_MODEL、
            未設定なら "gpt-5.6-luna"）。低コストの軽量モデルを推奨。
        max_constraints: 抽出するConstraintの最大数（デフォルト: 20）。
        max_syntax_rules: 抽出するSyntaxRuleの最大数（デフォルト: 20）。
        max_spec_clauses: 抽出するSpecClauseの最大数（デフォルト: 20）。
        max_terms: 抽出するTermの最大数（デフォルト: 20）。

    Returns:
        Dict[str, List[Dict[str, Any]]]: 抽出されたエンティティの辞書。以下のキーを含む:
            - constraints: Constraint情報のリスト
            - syntax_rules: SyntaxRule情報のリスト
            - spec_clauses: SpecClause情報のリスト
            - terms: Term情報のリスト

    Raises:
        RuntimeError: OpenAI APIキーが設定されていない場合。
        Exception: OpenAI API呼び出しに失敗した場合。
    """
    if not OPENAI_AVAILABLE:
        raise RuntimeError("OpenAI SDKが利用できません。pip install openai を実行してください。")

    require_openai_api_key()
    client = OpenAI(api_key=require_openai_api_key(), timeout=OPENAI_TIMEOUT_SECONDS)
    
    # モデルを決定（指定がない場合は軽量モデルを使用）
    if model is None:
        model = DEFAULT_ENTITY_EXTRACTION_MODEL

    # チャンクのテキストを結合（最初の10000文字まで）
    combined_text = "\n\n".join(
        [f"[{chunk.get('chunk_id', 'unknown')}]\n{chunk.get('text', '')}" for chunk in chunks[:50]]
    )
    if len(combined_text) > 10000:
        combined_text = combined_text[:10000] + "... (truncated)"

    # LLMプロンプトを作成
    prompt = f"""以下のドキュメントチャンクから、仕様書検証に必要なエンティティを抽出してください。

# 抽出対象のエンティティタイプ

1. **Constraint（制約・検証ルール）**
   - 例: "Ports must be defined before use"
   - 例: "State machines must have at least one initial state"
   - 形式: ルールや制約を表す文

2. **SyntaxRule（構文ルール）**
   - 例: "Action body must follow specific syntax"
   - 例: "Multiplicity expressions must follow the specified format"
   - 形式: 構文に関するルール

3. **SpecClause（仕様書条文）**
   - 例: "7.3.1 Port Definition"
   - 例: "8.2.3 State Machine Semantics"
   - 形式: 章番号や節番号を含む仕様書の参照

4. **Term（用語定義）**
   - 例: "port: A connection point that allows interaction..."
   - 形式: 用語とその定義

# 出力形式

以下のJSON形式で出力してください：

```json
{{
  "constraints": [
    {{
      "id": "C-001",
      "name": "Port Definition Rule",
      "description": "Ports must be defined before use",
      "related_chunks": ["doc1::chunk-0", "doc1::chunk-5"]
    }}
  ],
  "syntax_rules": [
    {{
      "id": "SR-05",
      "name": "Action Body Syntax",
      "description": "Action body must follow specific syntax",
      "related_chunks": ["doc1::chunk-10"]
    }}
  ],
  "spec_clauses": [
    {{
      "id": "clause-7.3.1",
      "clause_number": "7.3.1",
      "title": "Port Definition",
      "related_chunks": ["doc1::chunk-0", "doc1::chunk-1"]
    }}
  ],
  "terms": [
    {{
      "id": "term-port",
      "term": "port",
      "definition": "A port is a connection point that allows interaction between a block and its environment",
      "related_chunks": ["doc1::chunk-0"]
    }}
  ]
}}
```

# 注意事項

- 各エンティティには、そのエンティティが記述されているチャンクIDを`related_chunks`に含めてください
- IDは一意である必要があります（例: C-001, SR-05, clause-7.3.1, term-port）
- 抽出できないエンティティタイプは空のリストとして返してください
- 最大で各タイプ{max_constraints}件まで抽出してください

# ドキュメントチャンク

{combined_text}
"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "あなたは仕様書解析の専門家です。ドキュメントから構造化されたエンティティを正確に抽出してください。",
                },
                {"role": "user", "content": prompt},
            ],
            # reasoning モデルは temperature 非対応。max_tokens も使えない。
            # reasoning トークンも予算を食うため元の 4000 に余裕を足している。
            reasoning_effort="low",
            max_completion_tokens=6000,
        )

        content = response.choices[0].message.content or "{}"

        # JSONを抽出（コードブロック内のJSONを探す）
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        else:
            # コードブロックがない場合は、最初のJSONオブジェクトを探す
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                content = json_match.group(0)

        entities = json.loads(content)

        # デフォルト値を設定
        result = {
            "constraints": entities.get("constraints", [])[:max_constraints],
            "syntax_rules": entities.get("syntax_rules", [])[:max_syntax_rules],
            "spec_clauses": entities.get("spec_clauses", [])[:max_spec_clauses],
            "terms": entities.get("terms", [])[:max_terms],
        }

        logger.info(
            "extract_entities_with_llm.success",
            extra={
                "event": "extract_entities_with_llm.success",
                "num_constraints": len(result["constraints"]),
                "num_syntax_rules": len(result["syntax_rules"]),
                "num_spec_clauses": len(result["spec_clauses"]),
                "num_terms": len(result["terms"]),
            },
        )

        return result

    except json.JSONDecodeError as e:
        logger.warning(
            "extract_entities_with_llm.json_decode_error",
            extra={
                "event": "extract_entities_with_llm.json_decode_error",
                "error": str(e),
                "content_preview": content[:200] if "content" in locals() else "",
            },
        )
        return {
            "constraints": [],
            "syntax_rules": [],
            "spec_clauses": [],
            "terms": [],
        }
    except Exception as e:
        logger.error(
            "extract_entities_with_llm.error",
            extra={
                "event": "extract_entities_with_llm.error",
                "error": str(e),
            },
            exc_info=True,
        )
        raise


def extract_entities_with_parser(
    chunks: List[Dict[str, Any]],
    *,
    file_type: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """パーサーを使ってチャンクからエンティティを抽出する。

    現在は基本的なパターンマッチングを実装。
    将来的には、より高度なパーサー（SysMLパーサー等）を統合可能。

    Args:
        chunks: チャンク情報のリスト。
        file_type: ファイルタイプ（例: "sysml", "pdf"）。パーサーの選択に使用。

    Returns:
        Dict[str, List[Dict[str, Any]]]: 抽出されたエンティティの辞書。
    """
    result = {
        "constraints": [],
        "syntax_rules": [],
        "spec_clauses": [],
        "terms": [],
    }

    # 基本的なパターンマッチング
    constraint_pattern = re.compile(
        r"(?:must|shall|should|required|constraint|rule|validation).*?(?:\.|$)",
        re.IGNORECASE | re.MULTILINE,
    )
    clause_pattern = re.compile(r"(\d+\.\d+(?:\.\d+)?)\s+(.+)", re.MULTILINE)
    term_pattern = re.compile(r"(\w+):\s*(.+?)(?:\.|$)", re.MULTILINE)

    constraint_id_counter = 1

    for chunk in chunks:
        chunk_id = chunk.get("chunk_id", "")
        text = chunk.get("text", "")

        # Constraintの抽出
        for match in constraint_pattern.finditer(text):
            constraint_text = match.group(0).strip()
            if len(constraint_text) > 20:  # 短すぎるものは除外
                result["constraints"].append(
                    {
                        "id": f"C-{constraint_id_counter:03d}",
                        "name": constraint_text[:50] + ("..." if len(constraint_text) > 50 else ""),
                        "description": constraint_text,
                        "related_chunks": [chunk_id],
                    }
                )
                constraint_id_counter += 1

        # SpecClauseの抽出（章番号パターン）
        for match in clause_pattern.finditer(text):
            clause_number = match.group(1)
            title = match.group(2).strip()[:100]
            result["spec_clauses"].append(
                {
                    "id": f"clause-{clause_number.replace('.', '-')}",
                    "clause_number": clause_number,
                    "title": title,
                    "related_chunks": [chunk_id],
                }
            )

        # Termの抽出（用語: 定義 のパターン）
        for match in term_pattern.finditer(text):
            term = match.group(1).strip()
            definition = match.group(2).strip()
            if len(definition) > 10:  # 短すぎるものは除外
                result["terms"].append(
                    {
                        "id": f"term-{term.lower().replace(' ', '-')}",
                        "term": term,
                        "definition": definition,
                        "related_chunks": [chunk_id],
                    }
                )

    logger.info(
        "extract_entities_with_parser.success",
        extra={
            "event": "extract_entities_with_parser.success",
            "num_constraints": len(result["constraints"]),
            "num_spec_clauses": len(result["spec_clauses"]),
            "num_terms": len(result["terms"]),
        },
    )

    return result


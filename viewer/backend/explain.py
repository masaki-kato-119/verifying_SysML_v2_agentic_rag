"""選択要素の自然文説明生成（Group4 b17, R2）。

選択要素・関連エッジ・Findingの内容をLLMに渡し、平易な説明を生成する。
b15の決定（MCPクライアント経由）はHybridRAG/GraphRAGの検索・グラフロジックへの
アクセスに関する判断であり、本タスクが必要とするのは汎用のLLM呼び出し
（プロンプト→テキスト生成）で対象が異なる。実際、`GraphRAG/graphrag/`内部
（例:`node_summarizer.py`）自身もOpenAI APIをMCP経由ではなく直接呼び出して
おり、それと同じ直接呼び出し方式をここでも踏襲する（b15はgraphrag/ragの
「ビジネスロジックの直接import」を避ける決定であり、openaiパッケージの直接
利用とは無関係）。

生成された説明は必ず「推論であること」を明示し、Viewer側は入力に使った
関連エッジ・Findingをそのまま「根拠」として機械的に返す（LLMの自由記述に
根拠表示を依存させない、決定的で検証しやすい設計）。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# GraphRAG/graphrag/config.py の既定値と同じモデル名を踏襲する。ただし
# b15の決定によりgraphrag内部モジュールはimportしない（値の重複は許容する
# ――内部シグネチャへの依存ではなく、単なる既定値の踏襲のため）。
_DEFAULT_LLM_MODEL = "gpt-5.6-luna"


def _format_edges(related_edges: List[Dict[str, Any]]) -> str:
    if not related_edges:
        return "（関連エッジなし）"
    lines = []
    for edge in related_edges:
        direction = "→" if edge.get("direction") == "outgoing" else "←"
        lines.append(f"- {direction} {edge.get('kind')} {direction} {edge.get('other_label')} ({edge.get('other_type')})")
    return "\n".join(lines)


def _format_findings(findings: List[Dict[str, Any]]) -> str:
    if not findings:
        return "（Findingなし）"
    lines = []
    for finding in findings:
        rule = f"({finding.get('rule')}) " if finding.get("rule") else ""
        lines.append(f"- [{finding.get('severity')}] {rule}{finding.get('message')}")
    return "\n".join(lines)


def _build_prompt(element: Dict[str, Any], related_edges: List[Dict[str, Any]], findings: List[Dict[str, Any]]) -> str:
    return (
        f"以下はSysML v2モデル中の1要素と、その周辺情報です。\n\n"
        f"要素: {element.get('label')} (種別: {element.get('type')}, id: {element.get('id')})\n\n"
        f"関連エッジ:\n{_format_edges(related_edges)}\n\n"
        f"Finding（lintの指摘事項）:\n{_format_findings(findings)}\n\n"
        f"この要素が何を表しているか、なぜこれらのエッジ・Findingを持つと考えられるかを、"
        f"SysMLに詳しくない読み手にも分かる平易な日本語で3〜5文程度で説明してください。"
        f"与えられた情報だけからの推測であり断定できない場合は、その旨を明示してください。"
    )


_SYSTEM_PROMPT = (
    "あなたはSysML v2モデルの要素を分かりやすく説明するアシスタントです。"
    "回答は必ず、これがモデルの正式な仕様ではなく限られた情報からの推論であることを"
    "冒頭か末尾で一言明示してください。憶測で断定せず、不確かな点は不確かと述べてください。"
)


async def explain_element(
    element: Dict[str, Any], related_edges: List[Dict[str, Any]], findings: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Returns:
        {"available": True, "explanation": str,
         "basis": {"related_edges": [...], "findings": [...]}} 成功時。
        {"available": False, "error": str} API未設定/呼び出し失敗時
        （Viewer本体の表示は妨げないよう例外は投げない）。
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"available": False, "error": "OPENAI_API_KEYが設定されていません"}

    try:
        from openai import OpenAI  # 遅延import: このモジュール自体はopenai未インストールでもimportできるようにする

        client = OpenAI(api_key=api_key)
        model = os.environ.get("VIEWER_LLM_MODEL", _DEFAULT_LLM_MODEL)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_prompt(element, related_edges, findings)},
            ],
            reasoning_effort="low",
            max_completion_tokens=500,
        )
        explanation = response.choices[0].message.content
    except Exception as e:  # noqa: BLE001 - 外部API呼び出し境界: 失敗理由を問わずViewer側は表示継続する
        return {"available": False, "error": str(e)}

    return {
        "available": True,
        "explanation": explanation,
        "basis": {"related_edges": related_edges, "findings": findings},
    }

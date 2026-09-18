"""FastAPIアプリ本体（実装仕様書7.3節）。

起動方法:
    uvicorn viewer.backend.app:app --reload

エンドポイントはPOST /api/modelとGET /api/healthの2つのみ（Phase Aでは
「1回のテキスト送信で全部返す」単一エンドポイントに単純化する、実装仕様書
7.3節の方針通り）。
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sysml_v2_checker_advanced.parser import lint_sysml
from sysml_v2_checker_advanced.semantic_model import (
    build_element_index,
    build_semantic_model,
    semantic_model_to_json_dict,
)
from viewer.apply_fix import FixApplicationError, apply_fix_candidate
from viewer.backend.explain import explain_element
from viewer.backend.rag_client import get_rag_client
from viewer.backend.related_concepts import search_related_concepts
from viewer.graph_ir import (
    VIEW_TYPE_ACTIVITY,
    VIEW_TYPE_STATE_MACHINE,
    VIEW_TYPE_STRUCTURE,
    build_graph_ir,
)
from viewer.impact import build_impact_map
from viewer.svg_renderer import render_svg
from viewer.view_ir import build_flow_view_ir, build_view_ir

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="SysML v2 Viewer Backend")

# フロントエンド（8章、素のHTML+JS+Monaco Editor。ビルドステップ無し）を
# 同一オリジンで配信する。別オリジンでの配信にするとブラウザのCORS制約への
# 対応が別途必要になるため、それを避ける設計判断。
app.mount("/static", StaticFiles(directory=_FRONTEND_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "index.html")


class ModelRequest(BaseModel):
    text: str
    view_type: str = VIEW_TYPE_STRUCTURE
    collapsed_ids: List[str] = []
    pinned_positions: Dict[str, Dict[str, float]] = {}


class ModelResponse(BaseModel):
    ast_error: Optional[str] = None
    semantic_model: Optional[Dict[str, Any]] = None
    graph_ir: Optional[Dict[str, Any]] = None
    view_ir: Optional[Dict[str, Any]] = None
    svg: Optional[str] = None
    findings: Optional[List[Dict[str, Any]]] = None
    # 要素id -> 影響先リスト（viewer/impact.py）。2026-09-14にフロントエンドの
    # 走査をここへ移した（走査の意味論をpytestで固定するため。詳細は同モジュール）。
    impact: Optional[Dict[str, List[Dict[str, Any]]]] = None
    view_type_error: Optional[str] = None


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/model", response_model=ModelResponse)
def get_model(request: ModelRequest) -> ModelResponse:
    """SysMLテキストを解析し、Semantic Model・Graph IR・View IR・SVGを
    まとめて返す。構文エラー時は`ast_error`のみ設定し他はNoneのまま返す
    （実装仕様書8.4節：フロントエンド側が直前成功時の表示を維持する設計の
    ため、ここではエラーメッセージだけを渡せればよい）。
    """
    ast, semantic_model = build_semantic_model(request.text)

    if ast.get("type") == "error":
        return ModelResponse(ast_error=ast.get("message"))

    # element_indexはast由来のnodeオブジェクト同一性で突合するため、
    # 同じastから得たsemantic_modelを使う必要がある（拡張仕様書9章の制約。
    # GraphRAG/mcp_server.pyのvalidate_sysml_modelと同じ呼び出し順序）。
    # view_type="verification"（Group2 b8）がfindingの要素idを起点にする
    # ため、Graph IR構築より先にfindingsを求める。
    issues = lint_sysml(ast)
    element_index = build_element_index(semantic_model["nodes"])
    findings = [issue.to_dict(element_index) for issue in issues]
    finding_element_ids = {f["element_id"] for f in findings if f["element_id"]}

    try:
        graph_ir = build_graph_ir(
            semantic_model, view_type=request.view_type, finding_element_ids=finding_element_ids
        )
    except ValueError as e:
        return ModelResponse(view_type_error=str(e))
    # 表現力強化Stage 3, Group B f4 / Group C g3: state_machine/activityは
    # 入れ子矩形（包含関係の表現）ではなく層状（フロー）レイアウトを使う。
    # 手動配置は2026-09-18に対応した（それまでこの2ビューだけドラッグしても
    # 位置を覚えなかった）。**pinned_positionsの座標の意味が両者で違う**――
    # フロー側は入れ子を作らないので絶対座標、build_view_ir側は親を持つノードが
    # 相対オフセット（各関数のdocstring参照）。折りたたみは未対応のまま
    # （フラットな層配置では「子を畳む」の意味が構造ビューと同じにならない）。
    if request.view_type in (VIEW_TYPE_STATE_MACHINE, VIEW_TYPE_ACTIVITY):
        view_ir = build_flow_view_ir(graph_ir, pinned_positions=request.pinned_positions)
    else:
        view_ir = build_view_ir(
            graph_ir, collapsed_ids=set(request.collapsed_ids), pinned_positions=request.pinned_positions
        )
    svg = render_svg(view_ir)

    return ModelResponse(
        semantic_model=semantic_model_to_json_dict(semantic_model),
        graph_ir=graph_ir,
        view_ir=view_ir,
        svg=svg,
        findings=findings,
        impact=build_impact_map(graph_ir),
    )


class ApplyFixRequest(BaseModel):
    text: str
    source_range: Dict[str, Any]
    edit: Dict[str, Any]


@app.post("/api/apply-fix")
def post_apply_fix(request: ApplyFixRequest) -> Dict[str, Any]:
    """修正候補を適用した**プレビュー**を返す（Phase D、構想書§11）。

    確定はしない。新しいテキストと、それを再パース・再検証した結果の
    Finding を返すだけで、エディタへ書き戻すかどうかは利用者が決める
    （§12-5 Human authority）。UIはこの応答を使って「適用すると指摘が
    どう変わるか」を確定前に見せる。

    再パース・再検証は `/api/model` と同じ経路を通す（差分表示のために
    別の実装を持つと、プレビューと本番で結果がずれる余地ができる）。
    """
    try:
        new_text = apply_fix_candidate(request.text, request.source_range, request.edit)
    except FixApplicationError as error:
        return {"applied": False, "error": str(error)}

    ast, semantic_model = build_semantic_model(new_text)
    if ast.get("type") == "error":
        # 候補を当てた結果パースできなくなった場合。**これも見せる**べき情報で、
        # 「適用すると壊れる候補」を確定前に知らせる意味がある。
        return {
            "applied": True,
            "text": new_text,
            "ast_error": ast.get("message"),
            "findings": None,
        }

    issues = lint_sysml(ast)
    element_index = build_element_index(semantic_model["nodes"])
    return {
        "applied": True,
        "text": new_text,
        "ast_error": None,
        "findings": [issue.to_dict(element_index) for issue in issues],
    }


@app.get("/api/related-concepts")
async def get_related_concepts(element_type: str, label: str) -> Dict[str, Any]:
    """選択要素の型・ラベルでGraphRAGを検索し、関連概念を返す（Group4 b16,
    R1-2）。Findingsとは異なりモデル事実ではなく外部知識ベースからの参考情報
    のため、フロントエンド側で視覚的に区別して表示する（構想書8.2節）。
    GraphRAGサーバーが未起動/呼び出し失敗の場合も、Viewer本体の表示は妨げない
    よう例外を投げず`available: False`で返す。
    """
    try:
        client = await get_rag_client()
    except Exception as e:  # noqa: BLE001 - MCPサーバー起動失敗等もエラー応答に変換する
        return {"available": False, "error": str(e), "concepts": []}
    return await search_related_concepts(client.call_tool, element_type, label)


class ExplainRequest(BaseModel):
    element: Dict[str, Any]
    related_edges: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []


@app.post("/api/explain")
async def post_explain(request: ExplainRequest) -> Dict[str, Any]:
    """選択要素・関連エッジ・Findingの内容をLLMに渡し、平易な説明を生成する
    （Group4 b17, R2）。根拠はLLMの自由記述に依存させず、入力に使った
    related_edges/findingsをそのまま`basis`として機械的に返す（決定的で
    検証しやすい設計）。OPENAI_API_KEY未設定・呼び出し失敗時も例外を投げず
    `available: False`で返し、Viewer本体の表示は妨げない。
    """
    return await explain_element(request.element, request.related_edges, request.findings)

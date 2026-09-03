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
from viewer.graph_ir import build_graph_ir
from viewer.svg_renderer import render_svg
from viewer.view_ir import build_view_ir

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


class ModelResponse(BaseModel):
    ast_error: Optional[str] = None
    semantic_model: Optional[Dict[str, Any]] = None
    graph_ir: Optional[Dict[str, Any]] = None
    view_ir: Optional[Dict[str, Any]] = None
    svg: Optional[str] = None
    findings: Optional[List[Dict[str, Any]]] = None


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

    graph_ir = build_graph_ir(semantic_model)
    view_ir = build_view_ir(graph_ir)
    svg = render_svg(view_ir)

    # element_indexはast由来のnodeオブジェクト同一性で突合するため、
    # 同じastから得たsemantic_modelを使う必要がある（拡張仕様書9章の制約。
    # GraphRAG/mcp_server.pyのvalidate_sysml_modelと同じ呼び出し順序）。
    issues = lint_sysml(ast)
    element_index = build_element_index(semantic_model["nodes"])
    findings = [issue.to_dict(element_index) for issue in issues]

    return ModelResponse(
        semantic_model=semantic_model_to_json_dict(semantic_model),
        graph_ir=graph_ir,
        view_ir=view_ir,
        svg=svg,
        findings=findings,
    )

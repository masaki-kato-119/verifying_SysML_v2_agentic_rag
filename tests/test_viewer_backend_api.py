"""viewer/backend/app.py の統合テスト（SysMLv2_Viewer_実装仕様書.md 7章）。

`tests/mcp_integration_helpers.py`はMCPサーバーを実サブプロセスとして起動する
スタイルだが、FastAPIアプリはASGI標準の`TestClient`（httpx経由）で実際の
ASGIリクエスト/レスポンス処理（ルーティング・Pydanticバリデーション・
シリアライズ）を丸ごと通す方式が標準かつ十分な統合テストになるため、こちらを
採用する（実プロセス起動はポート衝突・後片付けの管理コストが増える割に、
検証できる範囲がほぼ変わらないため）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from viewer.backend.app import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_model_endpoint_returns_full_pipeline_output():
    response = client.post("/api/model", json={"text": "package P { part def A { attribute x : Real; } }"})
    assert response.status_code == 200

    data = response.json()
    assert data["ast_error"] is None
    assert "$root::A" in data["semantic_model"]["nodes"]
    assert any(n["id"] == "$root::A" for n in data["graph_ir"]["nodes"])
    assert any(n["id"] == "$root::A" for n in data["view_ir"]["nodes"])
    assert data["svg"].startswith("<svg")
    assert data["findings"] == []


def test_model_endpoint_returns_findings_with_element_id_and_source_range():
    """実装仕様書6章: LintIssue.to_dict(element_index)由来のfindingsを返す。
    astとsemantic_modelが同一呼び出し(build_semantic_model)由来のため、
    element_idが正しく突合できることを確認する（拡張仕様書9章の制約）。
    """
    response = client.post(
        "/api/model",
        json={"text": "package P { part def A { attribute x : NoSuchType; } }"},
    )
    data = response.json()

    assert len(data["findings"]) == 1
    finding = data["findings"][0]
    assert finding["severity"] == "warning"
    assert finding["element_id"] == "$root::A::x"
    assert finding["source_range"] is not None


def test_model_endpoint_reports_parse_error_without_crashing():
    response = client.post("/api/model", json={"text": "this is not valid sysml {{{"})
    assert response.status_code == 200

    data = response.json()
    assert data["ast_error"] is not None
    assert data["semantic_model"] is None
    assert data["graph_ir"] is None
    assert data["view_ir"] is None
    assert data["svg"] is None
    assert data["findings"] is None


def test_model_endpoint_requires_text_field():
    response = client.post("/api/model", json={})
    assert response.status_code == 422  # FastAPI/Pydanticの自動バリデーション

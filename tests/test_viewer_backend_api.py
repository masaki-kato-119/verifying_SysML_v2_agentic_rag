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
from viewer.view_ir import _LABEL_HEIGHT, _PADDING

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


def test_model_endpoint_defaults_to_structure_view():
    response = client.post("/api/model", json={"text": "package P { part def A; }"})
    data = response.json()
    assert any(n["id"] == "$root::A" for n in data["graph_ir"]["nodes"])


def test_model_endpoint_accepts_requirement_traceability_view_type():
    text = (
        "package P { part def System; part system; requirement def Req1; "
        "requirement req1 : Req1; satisfy requirement req1 : Req1 by system; }"
    )
    response = client.post("/api/model", json={"text": text, "view_type": "requirement_traceability"})
    data = response.json()
    assert data["view_type_error"] is None
    types = {n["type"] for n in data["graph_ir"]["nodes"]}
    assert types == {"requirement_def", "satisfy_requirement_usage", "part_instance"}


def test_model_endpoint_state_machine_view_uses_flow_layout():
    """表現力強化Stage 3, Group B f4: view_type="state_machine"は
    build_flow_view_ir（層状レイアウト）を使う。build_view_ir（入れ子矩形）
    とは異なり、ノードのx,yは親子の包含関係ではなく遷移の層に基づく。"""
    text = """
    state def AdvancedSwitch {
        entry; then Off;
        state Off;
        state On;
        transition first Off accept TurnOn then On;
    }
    """
    response = client.post("/api/model", json={"text": text, "view_type": "state_machine"})
    data = response.json()
    assert data["view_type_error"] is None
    assert data["view_ir"]["view_type"] == "state_machine"
    types = {n["type"] for n in data["graph_ir"]["nodes"]}
    assert types == {"state_def", "state_usage"}
    by_id = {n["id"]: n for n in data["view_ir"]["nodes"]}
    # Offは暗黙遷移の対象(層1)、Onはそこからの遷移先(層2)のため、yが単調に増える。
    assert by_id["$root::AdvancedSwitch::Off"]["y"] < by_id["$root::AdvancedSwitch::On"]["y"]


def test_model_endpoint_activity_view_uses_flow_layout():
    """表現力強化Stage 3, Group C g3: view_type="activity"もstate_machineと
    同じくbuild_flow_view_ir（層状レイアウト）を使う。"""
    text = """
    action def Act {
        action step1;
        action step2;
        first step1 then step2;
    }
    """
    response = client.post("/api/model", json={"text": text, "view_type": "activity"})
    data = response.json()
    assert data["view_type_error"] is None
    assert data["view_ir"]["view_type"] == "activity"
    types = {n["type"] for n in data["graph_ir"]["nodes"]}
    assert types == {"action_def", "action_usage"}
    by_id = {n["id"]: n for n in data["view_ir"]["nodes"]}
    assert by_id["$root::Act::step1"]["y"] < by_id["$root::Act::step2"]["y"]


def test_model_endpoint_verification_view_limits_to_finding_related_nodes():
    """Group2 b8(V2): view_type="verification"は、Findingが付いた要素
    (ここでは$root::A::x)だけに絞られる。xのfeature_typing参照先(NoSuchType)は
    unresolvedなので辿れず、他の要素は含まれない。"""
    response = client.post(
        "/api/model",
        json={
            "text": "package P { part def A { attribute x : NoSuchType; } }",
            "view_type": "verification",
        },
    )
    data = response.json()
    assert data["view_type_error"] is None
    assert [n["id"] for n in data["graph_ir"]["nodes"]] == ["$root::A::x"]
    assert data["graph_ir"]["edges"] == []
    assert len(data["findings"]) == 1


def test_model_endpoint_collapsed_ids_excludes_descendants_from_view_ir():
    """Group2 b10(V4): collapsed_idsに指定した要素の子孫はView IRから除外される
    （Graph IRには影響しない＝Explorer等は折りたたみの影響を受けない設計）。"""
    text = "package P { part def A { attribute x : Real; } }"
    response = client.post("/api/model", json={"text": text, "collapsed_ids": ["$root::A"]})
    data = response.json()
    assert any(n["id"] == "$root::A" for n in data["graph_ir"]["nodes"])
    assert any(n["id"] == "$root::A::x" for n in data["graph_ir"]["nodes"])
    view_ir_ids = {n["id"] for n in data["view_ir"]["nodes"]}
    assert "$root::A" in view_ir_ids
    assert "$root::A::x" not in view_ir_ids


def test_model_endpoint_pinned_positions_are_reflected_in_view_ir():
    """Group3 b11(L1-1): pinned_positionsに指定した座標がView IR出力に反映される。
    $root::Aは親($root)を持つため、値は親の内容領域起点からの相対オフセットとして
    解釈される（表現力強化「手動レイアウトの階層整合性」案B）。"""
    text = "package P { part def A; }"
    response = client.post(
        "/api/model",
        json={"text": text, "pinned_positions": {"$root::A": {"x": 123, "y": 456}}},
    )
    data = response.json()
    root = next(n for n in data["view_ir"]["nodes"] if n["id"] == "$root")
    node = next(n for n in data["view_ir"]["nodes"] if n["id"] == "$root::A")
    assert (node["x"], node["y"]) == (root["x"] + _PADDING + 123, root["y"] + _LABEL_HEIGHT + _PADDING + 456)


async def test_related_concepts_endpoint_queries_graphrag_when_available():
    """Group4 b16(R1-2): 実際にGraphRAG MCPサーバーをサブプロセス起動して検証する
    （tests/test_mcp_integration_graph.pyと同じ方針）。事前構築済みグラフ
    GraphRAG/data/graphs/SysML_Language_Specification_v2.pklには"requirement"
    ノードが実在する（test_mcp_integration_graph.pyのtest_find_path_uses_...で
    確認済み）ため、type由来の検索語"requirement"で実マッチが期待できる。
    ただしCI等データが無い環境でもクラッシュしないことを優先し、空でも許容する。
    """
    response = client.get(
        "/api/related-concepts", params={"element_type": "requirement_usage", "label": "req1"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert isinstance(data["concepts"], list)
    if data["concepts"]:
        assert any("requirement" in (c["concept"] or "").lower() for c in data["concepts"])


def test_explain_endpoint_reports_unavailable_without_api_key(monkeypatch):
    """Group4 b17(R2): OPENAI_API_KEY未設定時は実API呼び出しをせず、
    Viewer本体の表示を妨げないavailable:Falseで応答する
    （実際のOpenAI課金APIを毎回のpytest実行で呼ばないための設計）。
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post(
        "/api/explain",
        json={
            "element": {"id": "$root::A", "type": "part_def", "label": "A"},
            "related_edges": [],
            "findings": [],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is False


def test_model_endpoint_reports_unknown_view_type_without_crashing():
    response = client.post("/api/model", json={"text": "package P { part def A; }", "view_type": "no_such_view"})
    assert response.status_code == 200
    data = response.json()
    assert data["view_type_error"] is not None
    assert data["graph_ir"] is None

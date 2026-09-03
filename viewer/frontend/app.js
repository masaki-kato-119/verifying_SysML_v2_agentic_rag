// SysML v2 Viewer フロントエンド（SysMLv2_Viewer_実装仕様書.md 8章）。
// 素のHTML+JS+Monaco Editor（CDN）構成。ビルドツールを使わない
// （2026-09-03、va11でユーザー確認の上決定）。

const DEFAULT_TEXT = `package Vehicle {
    part def Machine {
        attribute mass : Real;
    }
    part def Engine :> Machine {
        attribute power : Real;
    }
    part myEngine : Engine;
}
`;

const DEBOUNCE_MS = 400;

// Findingの状態遷移（Group1 b4, I4）。ブラウザのlocalStorageに保存する
// （複数人でのレビュー共有が必要になった時点でサーバー側永続化を再検討する。
// 作業計画書8章のリスク欄に明記済みの割り切り）。
const FINDING_STATUS_STORAGE_KEY = "sysmlViewerFindingStatus";
const FINDING_STATUSES = ["Open", "Accepted", "Resolved", "False Positive"];

// 1つの要素が複数のFindingを持ちうるため、element_id単体ではキーにならない。
// rule+messageを組み合わせた複合キーで「同じ場所の同じ種類の指摘」を識別する
// （テキスト編集で多少内容が変わると別のFinding扱いになる既知の簡易割り切り）。
function findingStatusKey(finding) {
  return `${finding.element_id}::${finding.rule}::${finding.message}`;
}

function loadFindingStatuses() {
  try {
    return JSON.parse(localStorage.getItem(FINDING_STATUS_STORAGE_KEY) || "{}");
  } catch (e) {
    return {};
  }
}

// Group1 b5(I5): 状態変更のたびに履歴を追記する。既存のstatus/updated_atは
// 「現在値」として引き続き提供し、historyは追加のみ（削除・上書きしない）。
function saveFindingStatus(key, status) {
  const all = loadFindingStatuses();
  const previous = all[key] || { history: [] };
  const entry = { status, timestamp: new Date().toISOString() };
  all[key] = {
    status,
    updated_at: entry.timestamp,
    history: [...(previous.history || []), entry],
  };
  localStorage.setItem(FINDING_STATUS_STORAGE_KEY, JSON.stringify(all));
}

let editor = null;
let latestModel = null; // 直近成功時のAPIレスポンス（構文エラー時もこれを表示し続ける。8.4節）
let latestFindings = [];
let debounceTimer = null;
let selectedElementId = null;
let currentViewType = "structure"; // Group2 b7(V1-2)

// Group2 b9(V3): 型/重要度フィルタ。Graph IR/View IR自体は変更せず、描画済み
// SVGノードをdisplay:noneで隠すだけの低リスクな実装（作業計画書Group2(b9)の
// 方針通り）。未登録の型/重要度は「表示」を既定値とする。
const typeFilterState = {};
const severityFilterState = { error: true, warning: true, info: true };

// Group2 b10(V4): 階層の折りたたみ。ノードidの集合をリクエストごとに
// /api/modelへ送り、View IR側でその子孫をレイアウトから除外してもらう
// （Graph IR/Explorerは常に全要素を保持し、折りたたみの影響を受けない）。
const collapsedIds = new Set();

// Group3 b12(L1-2): 手動レイアウト。ドラッグで確定した座標をノードidごとに
// 保持し、リクエストごとに/api/modelへpinned_positionsとして送る
// （viewer/view_ir.pyのbuild_view_irのpinned_positions引数、b11で追加済み）。
const pinnedPositions = {};

// Group3 b13(L2): View定義の保存。b9(フィルタ)・b10(折りたたみ)・
// b12(手動レイアウト)の状態をlocalStorageへ保存し、次回読み込み時に復元する
// （Group1 b4と同じ「複数人でのレビュー共有が必要になった時点でサーバー側
// 永続化を再検討する」割り切り、作業計画書8章のリスク欄）。
const VIEW_STATE_STORAGE_KEY = "sysmlViewerViewState";

function saveViewState() {
  try {
    localStorage.setItem(
      VIEW_STATE_STORAGE_KEY,
      JSON.stringify({
        typeFilterState,
        severityFilterState,
        collapsedIds: [...collapsedIds],
        pinnedPositions,
      })
    );
  } catch (e) {
    // localStorageが使えない環境（プライベートモード等）では永続化を諦める。
  }
}

// typeFilterStateはGraph IRの型集合に応じてrenderFilterControlsが動的に
// 補完する（既存の型は復元値を維持、新規の型のみ既定trueで追加）ため、
// ここでは保存済みの値をそのまま上書きコピーするだけでよい。
function loadViewState() {
  try {
    const stored = JSON.parse(localStorage.getItem(VIEW_STATE_STORAGE_KEY) || "{}");
    Object.assign(typeFilterState, stored.typeFilterState || {});
    Object.assign(severityFilterState, stored.severityFilterState || {});
    for (const id of stored.collapsedIds || []) collapsedIds.add(id);
    Object.assign(pinnedPositions, stored.pinnedPositions || {});
  } catch (e) {
    // 壊れた保存データは無視し、既定状態のまま続行する。
  }
}

async function fetchModel(text) {
  const response = await fetch("/api/model", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      view_type: currentViewType,
      collapsed_ids: [...collapsedIds],
      pinned_positions: pinnedPositions,
    }),
  });
  return response.json();
}

// SVGノードのドラッグで手動レイアウトを確定させる（Group3 b12, L1-2）。
// ドラッグ中は<g>にtransformを当てて追従させるだけの軽量なプレビューとし、
// mouseup時点の座標をpinnedPositionsへ確定してモデルを再取得する
// （再取得後はView IR側の計算結果に基づく描画に置き換わり、transformは
// 使われなくなる）。移動量が閾値未満なら「クリック」とみなしピン留めせず、
// 既存のclick(選択)/dblclick(折りたたみ)ハンドラの動作を妨げない。
const DRAG_THRESHOLD_PX = 3;

function startNodeDrag(startEvent, g, elementId) {
  const rect = g.querySelector("rect");
  if (!rect) return;
  const startX = parseFloat(rect.getAttribute("x"));
  const startY = parseFloat(rect.getAttribute("y"));
  const startClientX = startEvent.clientX;
  const startClientY = startEvent.clientY;
  let moved = false;

  function onMouseMove(moveEvent) {
    const dx = moveEvent.clientX - startClientX;
    const dy = moveEvent.clientY - startClientY;
    if (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX) moved = true;
    if (moved) g.setAttribute("transform", `translate(${dx}, ${dy})`);
  }

  function onMouseUp(upEvent) {
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);
    g.removeAttribute("transform");
    if (!moved) return;
    const dx = upEvent.clientX - startClientX;
    const dy = upEvent.clientY - startClientY;
    pinnedPositions[elementId] = { x: startX + dx, y: startY + dy };
    saveViewState();
    updateModelNow();
  }

  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup", onMouseUp);
}

function renderDiagram(svg) {
  document.getElementById("diagram-container").innerHTML = svg;
  document.querySelectorAll("#diagram-container .sysml-node").forEach((g) => {
    const elementId = g.getAttribute("data-element-id");
    g.classList.toggle("collapsed", collapsedIds.has(elementId));
    g.addEventListener("click", (event) => {
      // ノードは入れ子（親の中に子のSVG<g>がある）のため、stopPropagation()が
      // 無いとクリックイベントが祖先の.sysml-nodeまでバブルし、祖先側の
      // リスナーが後から発火して子の選択を上書きしてしまう（Phase A由来の
      // 既存バグ。Group1 b4の動作確認中に発見し、影響が大きく修正も
      // 一行で済むためその場で修正した）。
      event.stopPropagation();
      selectElement(elementId);
    });
    // ドラッグで手動レイアウトを確定する（Group3 b12, L1-2）。
    g.addEventListener("mousedown", (event) => {
      if (event.button !== 0) return; // 左クリックのみ
      event.stopPropagation();
      startNodeDrag(event, g, elementId);
    });
    // ダブルクリックで折りたたみ/展開をトグルする（Group2 b10, V4）。
    // 子を持たない葉ノードでも実害はない（送るcollapsed_idsが1件増えるだけ）。
    g.addEventListener("dblclick", (event) => {
      event.stopPropagation();
      if (collapsedIds.has(elementId)) {
        collapsedIds.delete(elementId);
      } else {
        collapsedIds.add(elementId);
      }
      saveViewState();
      updateModelNow();
    });
  });
}

// lint findings（severity別）をSVGノードへ重畳表示する（6章、実装仕様書6.2節）。
// severityは一次シグナル（枠線色）に留め、詳細はInspectorで確認させる方針
// （構想書§9「重要度だけで色分けするのではなく」を踏まえた設計）。
const SEVERITY_RANK = { error: 3, warning: 2, info: 1 };
const RANK_TO_CLASS = { 3: "finding-error", 2: "finding-warning", 1: "finding-info" };

function applyFindingsOverlay(findings) {
  document.querySelectorAll("#diagram-container .sysml-node").forEach((el) => {
    el.classList.remove("finding-error", "finding-warning", "finding-info");
  });

  const worstRankByElement = new Map();
  for (const finding of findings) {
    if (!finding.element_id) continue; // 対象外ノード種別を指すfindingは図上には出さない（6.2節）
    const rank = SEVERITY_RANK[finding.severity] || 0;
    const current = worstRankByElement.get(finding.element_id) || 0;
    if (rank > current) worstRankByElement.set(finding.element_id, rank);
  }

  for (const [elementId, rank] of worstRankByElement) {
    const el = document.querySelector(`.sysml-node[data-element-id="${CSS.escape(elementId)}"]`);
    if (el) el.classList.add(RANK_TO_CLASS[rank]);
  }
}

// 現在のGraph IRノードが持つ型・現在のFindingsが持つ重要度から、SVGノードを
// 非表示にする（Graph IR/View IR自体は変更しない、b9の完了基準）。
function applyNodeFilters() {
  const severitiesByElement = new Map();
  for (const finding of latestFindings) {
    if (!finding.element_id) continue;
    if (!severitiesByElement.has(finding.element_id)) severitiesByElement.set(finding.element_id, new Set());
    severitiesByElement.get(finding.element_id).add(finding.severity);
  }

  document.querySelectorAll("#diagram-container .sysml-node").forEach((el) => {
    const type = el.getAttribute("data-type");
    const typeVisible = typeFilterState[type] !== false;

    const severities = severitiesByElement.get(el.getAttribute("data-element-id"));
    // Findingを持たない要素は重要度フィルタの対象外（常に表示）。
    const severityVisible = !severities || [...severities].some((s) => severityFilterState[s] !== false);

    el.classList.toggle("filtered-out", !(typeVisible && severityVisible));
  });
}

// フィルタパネルを現在のGraph IRの型集合から再構築する（b9）。チェック状態は
// typeFilterState/severityFilterStateに保持されるため、再描画をまたいで保持される。
function renderFilterControls(graphIr) {
  const container = document.getElementById("filter-controls");
  if (!container) return;

  const types = [...new Set(graphIr.nodes.map((n) => n.type))].sort();
  for (const type of types) {
    if (!(type in typeFilterState)) typeFilterState[type] = true; // 新規の型は既定で表示
  }

  container.innerHTML = "";

  const typeGroup = document.createElement("div");
  typeGroup.className = "filter-group";
  typeGroup.innerHTML = "<strong>型:</strong>";
  for (const type of types) {
    typeGroup.appendChild(makeFilterCheckbox(type, typeFilterState[type], (checked) => {
      typeFilterState[type] = checked;
      saveViewState();
      applyNodeFilters();
    }));
  }
  container.appendChild(typeGroup);

  const severityGroup = document.createElement("div");
  severityGroup.className = "filter-group";
  severityGroup.innerHTML = "<strong>重要度:</strong>";
  for (const severity of ["error", "warning", "info"]) {
    severityGroup.appendChild(makeFilterCheckbox(severity, severityFilterState[severity], (checked) => {
      severityFilterState[severity] = checked;
      saveViewState();
      applyNodeFilters();
    }));
  }
  container.appendChild(severityGroup);
}

function makeFilterCheckbox(labelText, checked, onChange) {
  const label = document.createElement("label");
  label.className = "filter-checkbox";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", () => onChange(input.checked));
  label.appendChild(input);
  label.appendChild(document.createTextNode(labelText));
  return label;
}

// Graph IRのnodesを group_id からツリー化してExplorerへ表示する（6.3, 8.2節）。
function renderExplorer(graphIr) {
  const childrenByParent = new Map();
  const byId = new Map();
  for (const node of graphIr.nodes) {
    byId.set(node.id, node);
    const key = node.group_id === null ? "__root__" : node.group_id;
    if (!childrenByParent.has(key)) childrenByParent.set(key, []);
    childrenByParent.get(key).push(node.id);
  }
  for (const ids of childrenByParent.values()) {
    ids.sort();
  }

  function buildList(parentKey) {
    const ids = childrenByParent.get(parentKey) || [];
    if (ids.length === 0) return null;
    const ul = document.createElement("ul");
    for (const id of ids) {
      const node = byId.get(id);
      const li = document.createElement("li");
      const label = document.createElement("div");
      label.className = "explorer-node";
      label.textContent = `${node.label} (${node.type})`;
      label.dataset.elementId = id;
      label.addEventListener("click", () => selectElement(id));
      li.appendChild(label);
      const childList = buildList(id);
      if (childList) li.appendChild(childList);
      ul.appendChild(li);
    }
    return ul;
  }

  const container = document.getElementById("explorer-tree");
  container.innerHTML = "";
  const tree = buildList("__root__");
  if (tree) container.appendChild(tree);
}

// 選択要素がfrom/toになっているGraph IRエッジを一覧表示する（Group1 b1,
// 実装仕様書6.3節「関連エッジ」。Phase Aでは未実装だった項目）。
// クリックで相手要素へselectElementでジャンプする。
function renderRelatedEdges(node, container) {
  if (!latestModel) return;
  const byId = new Map(latestModel.graph_ir.nodes.map((n) => [n.id, n]));
  const related = latestModel.graph_ir.edges.filter((e) => e.from === node.id || e.to === node.id);
  if (related.length === 0) return;

  const heading = document.createElement("div");
  heading.innerHTML = "<strong>関連エッジ:</strong>";
  container.appendChild(heading);

  for (const edge of related) {
    const outgoing = edge.from === node.id;
    const otherId = outgoing ? edge.to : edge.from;
    const other = byId.get(otherId);
    const otherLabel = other ? `${other.label} (${other.type})` : otherId;
    const arrow = outgoing ? "→" : "←";

    const row = document.createElement("div");
    row.className = "edge-row";
    row.textContent = `${arrow} ${edge.kind} ${arrow} ${otherLabel}`;
    row.addEventListener("click", () => selectElement(otherId));
    container.appendChild(row);
  }
}

function renderInspector(node) {
  const container = document.getElementById("inspector-content");
  if (!node) {
    container.textContent = "要素を選択してください";
    return;
  }
  const range = node.source_range;
  const rangeText = range
    ? `${range.start_line}:${range.start_column} - ${range.end_line}:${range.end_column}`
    : "(不明)";
  container.innerHTML = "";
  const rows = [
    ["stable_id", node.id],
    ["type", node.type],
    ["name", node.label],
    ["source_range", rangeText],
  ];
  for (const [key, value] of rows) {
    const row = document.createElement("div");
    row.innerHTML = `<strong>${key}:</strong> ${value}`;
    container.appendChild(row);
  }

  renderRelatedEdges(node, container);

  const relatedFindings = latestFindings.filter((f) => f.element_id === node.id);
  if (relatedFindings.length > 0) {
    const heading = document.createElement("div");
    heading.innerHTML = "<strong>Findings:</strong>";
    container.appendChild(heading);
    for (const finding of relatedFindings) {
      const row = document.createElement("div");
      row.className = `finding-row finding-${finding.severity}`;
      // Group1 b3b(I3-2): ruleはLintIssueが呼び出し元フレームから自動取得した
      // チェックメソッド名（例: "_check_attribute_def"）。省略時（古いAPI等）は表示しない。
      const rulePrefix = finding.rule ? `(${finding.rule}) ` : "";
      row.textContent = `[${finding.severity}] ${rulePrefix}${finding.message}`;
      container.appendChild(row);

      // Group1 b3(I3-1): このFindingの対象要素が持つ参照（reference_text/
      // resolution_status）をsemantic_model.edgesから引いて併記する。
      // Graph IRのedgesはresolved=trueのみ（3.3節の設計判断）のため、
      // unresolvedな（＝多くのFindingの原因そのものである）参照を見るには
      // semantic_model.edges（解決可否を問わず全件持つ）を使う必要がある。
      const evidenceEdges = latestModel.semantic_model.edges.filter((e) => e.from_id === finding.element_id);
      for (const edge of evidenceEdges) {
        const evidenceRow = document.createElement("div");
        evidenceRow.className = "evidence-row";
        evidenceRow.textContent = `　根拠: ${edge.kind} → "${edge.reference_text}" (${edge.resolution_status})`;
        container.appendChild(evidenceRow);
      }

      container.appendChild(renderFindingStatusControl(finding));
    }
  }

  // Group4 b16(R1-2): 関連概念。GraphRAG検索は遅い/未起動の可能性があるため
  // Inspector本体の描画はブロックせず、非同期に取得できたら追記する。
  const relatedConceptsContainer = document.createElement("div");
  container.appendChild(relatedConceptsContainer);
  loadRelatedConcepts(node, relatedConceptsContainer);

  // Group4 b17(R2): 自然文での説明生成。実際のLLM API呼び出し（課金対象）が
  // 発生するため、b16と異なり選択のたびに自動実行はせず、ボタンで明示的に
  // ユーザーが起動する。
  const explainButton = document.createElement("button");
  explainButton.type = "button";
  explainButton.className = "explain-button";
  explainButton.textContent = "AIによる説明を生成（推論・要確認）";
  const explainResult = document.createElement("div");
  explainButton.addEventListener("click", () => {
    explainButton.disabled = true;
    explainButton.textContent = "生成中...";
    loadExplanation(node, relatedFindings, explainButton, explainResult);
  });
  container.appendChild(explainButton);
  container.appendChild(explainResult);
}

// 選択要素からGraph IRのエッジをたどり、/api/explainへ送る形（kind/方向/相手の
// ラベル・型）に整形する（renderRelatedEdgesと同じ辿り方）。
function relatedEdgesPayload(node) {
  if (!latestModel) return [];
  const byId = new Map(latestModel.graph_ir.nodes.map((n) => [n.id, n]));
  return latestModel.graph_ir.edges
    .filter((e) => e.from === node.id || e.to === node.id)
    .map((e) => {
      const outgoing = e.from === node.id;
      const other = byId.get(outgoing ? e.to : e.from);
      return {
        kind: e.kind,
        direction: outgoing ? "outgoing" : "incoming",
        other_label: other ? other.label : (outgoing ? e.to : e.from),
        other_type: other ? other.type : null,
      };
    });
}

async function loadExplanation(node, findings, button, resultContainer) {
  const payload = {
    element: { id: node.id, type: node.type, label: node.label },
    related_edges: relatedEdgesPayload(node),
    findings: findings.map((f) => ({ severity: f.severity, rule: f.rule, message: f.message })),
  };
  let data;
  try {
    const response = await fetch("/api/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    data = await response.json();
  } catch (e) {
    data = { available: false, error: String(e) };
  }
  // 応答が届くまでの間に別の要素が選択されていたら、古いボタン/結果欄への
  // 反映はしない（loadRelatedConceptsと同じ競合ガード）。
  if (selectedElementId !== node.id) return;
  button.disabled = false;
  button.textContent = "AIによる説明を生成（推論・要確認）";
  renderExplanationCard(data, resultContainer);
}

// モデル事実とは明確に区別し、「推論であること」を見出しで常に明示する
// （構想書8.2節、b17完了基準）。根拠(basis)はLLMの自由記述ではなく、
// リクエストにそのまま含めた関連エッジ・Findingを機械的に列挙する。
function renderExplanationCard(data, container) {
  container.innerHTML = "";
  if (!data.available) {
    const errorRow = document.createElement("div");
    errorRow.className = "explanation-error";
    errorRow.textContent = `説明を生成できませんでした（${data.error || "不明なエラー"}）`;
    container.appendChild(errorRow);
    return;
  }

  const card = document.createElement("div");
  card.className = "explanation-card";

  const heading = document.createElement("div");
  heading.className = "explanation-heading";
  heading.textContent = "AIによる説明（推論であり、モデルの正式な仕様ではありません）";
  card.appendChild(heading);

  const text = document.createElement("div");
  text.className = "explanation-text";
  text.textContent = data.explanation;
  card.appendChild(text);

  const basis = data.basis || {};
  const basisEdges = basis.related_edges || [];
  const basisFindings = basis.findings || [];

  const basisHeading = document.createElement("div");
  basisHeading.className = "explanation-basis-heading";
  basisHeading.textContent = "根拠として使用した情報:";
  card.appendChild(basisHeading);

  if (basisEdges.length === 0 && basisFindings.length === 0) {
    const none = document.createElement("div");
    none.className = "explanation-basis-row";
    none.textContent = "（関連エッジ・Findingなし。要素の型・名前のみから推測）";
    card.appendChild(none);
  }
  for (const edge of basisEdges) {
    const row = document.createElement("div");
    row.className = "explanation-basis-row";
    const arrow = edge.direction === "outgoing" ? "→" : "←";
    row.textContent = `${arrow} ${edge.kind} ${arrow} ${edge.other_label} (${edge.other_type})`;
    card.appendChild(row);
  }
  for (const finding of basisFindings) {
    const row = document.createElement("div");
    row.className = "explanation-basis-row";
    row.textContent = `[${finding.severity}] ${finding.message}`;
    card.appendChild(row);
  }

  container.appendChild(card);
}

async function loadRelatedConcepts(node, container) {
  let data;
  try {
    const response = await fetch(
      `/api/related-concepts?element_type=${encodeURIComponent(node.type)}&label=${encodeURIComponent(node.label)}`
    );
    data = await response.json();
  } catch (e) {
    return; // GraphRAG呼び出し自体の失敗はViewer本体の利用を妨げない（静かに諦める）
  }
  // 応答が届くまでの間に別の要素が選択されていたら、古い結果は破棄する
  // （updateModelNowのrequestSequenceガードと同じ考え方）。
  if (selectedElementId !== node.id) return;
  renderRelatedConceptsCard(data, container);
}

// モデル事実（実線・source_range由来）とは視覚的に区別する
// （構想書8.2節：外部知識ベースからの参考情報であることを明示する）。
function renderRelatedConceptsCard(data, container) {
  container.innerHTML = "";
  if (!data.available || !data.concepts || data.concepts.length === 0) return;

  const card = document.createElement("div");
  card.className = "related-concepts-card";

  const heading = document.createElement("div");
  heading.className = "related-concepts-heading";
  heading.textContent = "関連概念（外部知識ベースより、参考情報）";
  card.appendChild(heading);

  for (const concept of data.concepts) {
    const row = document.createElement("div");
    row.className = "related-concept-row";
    const score = typeof concept.score === "number" ? concept.score.toFixed(2) : "?";
    row.textContent = `${concept.concept}（${concept.match_type}, score=${score}）`;
    card.appendChild(row);

    for (const text of concept.source_texts || []) {
      const citation = document.createElement("div");
      citation.className = "related-concept-citation";
      citation.textContent = `出典: ${text}`;
      card.appendChild(citation);
    }
  }

  container.appendChild(card);
}

// Findingの状態変更UI（Group1 b4, I4）+ レビュー履歴（Group1 b5, I5）。
// <select>でOpen/Accepted/Resolved/False Positiveを切り替え、
// localStorageに保存する。変更のたびに履歴（b5）ごと再描画する。
function renderFindingStatusControl(finding) {
  const key = findingStatusKey(finding);
  const stored = loadFindingStatuses()[key];
  const currentStatus = stored ? stored.status : "Open";

  const wrapper = document.createElement("div");
  wrapper.className = "finding-status-control";

  const select = document.createElement("select");
  for (const status of FINDING_STATUSES) {
    const option = document.createElement("option");
    option.value = status;
    option.textContent = status;
    if (status === currentStatus) option.selected = true;
    select.appendChild(option);
  }
  select.addEventListener("change", () => {
    saveFindingStatus(key, select.value);
    // 履歴（b5）を含め状態全体が変わるため、コントロール自体を作り直す。
    const refreshed = renderFindingStatusControl(finding);
    wrapper.replaceWith(refreshed);
  });
  wrapper.appendChild(select);

  if (stored) {
    const updatedLabel = document.createElement("span");
    updatedLabel.className = "finding-status-updated";
    updatedLabel.textContent = ` (${new Date(stored.updated_at).toLocaleString()}時点)`;
    wrapper.appendChild(updatedLabel);
  }

  const history = (stored && stored.history) || [];
  if (history.length > 0) {
    const historyList = document.createElement("ul");
    historyList.className = "finding-history";
    // 新しいものを上に（時系列を辿りやすいよう降順）。
    for (const entry of [...history].reverse()) {
      const item = document.createElement("li");
      item.textContent = `${new Date(entry.timestamp).toLocaleString()} → ${entry.status}`;
      historyList.appendChild(item);
    }
    wrapper.appendChild(historyList);
  }

  return wrapper;
}

// プログラムでMonacoの選択範囲を動かしている最中はonDidChangeCursorPosition
// の逆方向同期(va15)を止めるためのガード。
let isProgrammaticEditorUpdate = false;

// Diagram(SVGの<g data-start-offset data-end-offset>)クリック時、そのノードの
// source_rangeからMonacoの選択範囲を設定しスクロールする（8.3節、Diagram→Text）。
function revealInEditor(node) {
  if (!editor || !node.source_range) return;
  const model = editor.getModel();
  const startPos = model.getPositionAt(node.source_range.start_offset);
  const endPos = model.getPositionAt(node.source_range.end_offset);
  const range = new monaco.Range(startPos.lineNumber, startPos.column, endPos.lineNumber, endPos.column);

  isProgrammaticEditorUpdate = true;
  editor.setSelection(range);
  editor.revealRangeInCenter(range);
  isProgrammaticEditorUpdate = false;
}

// 選択要素からGraph IRのエッジ（specialization/feature_typing/connection等、
// 向きを問わない）をBFSで辿り、IMPACT_DEPTH次までの関連要素idを集める
// （Group1 b2）。数千要素規模までは毎回の隣接表構築で十分という判断
// （8.3節のText→Diagram同期の線形探索と同じ考え方）。
const IMPACT_DEPTH = 2;

function findImpactedElementIds(elementId, depth) {
  if (!latestModel) return new Set();
  const adjacency = new Map();
  const link = (a, b) => {
    if (!adjacency.has(a)) adjacency.set(a, new Set());
    adjacency.get(a).add(b);
  };
  for (const edge of latestModel.graph_ir.edges) {
    link(edge.from, edge.to);
    link(edge.to, edge.from);
  }

  const visited = new Set([elementId]);
  let frontier = [elementId];
  for (let i = 0; i < depth && frontier.length > 0; i++) {
    const next = [];
    for (const id of frontier) {
      for (const neighbor of adjacency.get(id) || []) {
        if (!visited.has(neighbor)) {
          visited.add(neighbor);
          next.push(neighbor);
        }
      }
    }
    frontier = next;
  }
  visited.delete(elementId);
  return visited;
}

// Explorer・Diagram・Text双方からの選択を一箇所に集約する。
// fromEditor=true の場合はva15（カーソル位置からの逆引き）由来のため、
// Monacoへの書き戻し（revealInEditor）はスキップする（無限ループ防止）。
function selectElement(elementId, { fromEditor = false } = {}) {
  selectedElementId = elementId;

  document.querySelectorAll(".explorer-node.selected").forEach((el) => el.classList.remove("selected"));
  document.querySelectorAll(".sysml-node.selected").forEach((el) => el.classList.remove("selected"));
  document.querySelectorAll(".sysml-node.impacted").forEach((el) => el.classList.remove("impacted"));

  const explorerEl = document.querySelector(`.explorer-node[data-element-id="${CSS.escape(elementId)}"]`);
  if (explorerEl) explorerEl.classList.add("selected");
  const diagramEl = document.querySelector(`.sysml-node[data-element-id="${CSS.escape(elementId)}"]`);
  if (diagramEl) diagramEl.classList.add("selected");

  for (const impactedId of findImpactedElementIds(elementId, IMPACT_DEPTH)) {
    const el = document.querySelector(`.sysml-node[data-element-id="${CSS.escape(impactedId)}"]`);
    if (el) el.classList.add("impacted");
  }

  const node = latestModel && latestModel.graph_ir.nodes.find((n) => n.id === elementId);
  renderInspector(node);

  if (node && !fromEditor) {
    revealInEditor(node);
  }
}

// 構文エラーメッセージから "(line X, column Y)" を抜き出し、Monacoの
// エラーマーカーとして表示する（8.4節）。sysml_v2_checker_advancedの
// _CollectingErrorListener（antlr_transformer.py）がこの形式で複数件を
// "; "連結して返す（parse_sysml_antlrのdocstring・実装参照）ため、
// 全件分マーカーを立てる。
const ERROR_LOCATION_RE = /\(line (\d+), column (\d+)\)/g;

function updateErrorMarkers(message) {
  if (!editor) return;
  const model = editor.getModel();
  if (!message) {
    monaco.editor.setModelMarkers(model, "sysml", []);
    return;
  }
  const markers = [];
  let match;
  ERROR_LOCATION_RE.lastIndex = 0;
  while ((match = ERROR_LOCATION_RE.exec(message)) !== null) {
    const line = parseInt(match[1], 10);
    const column = parseInt(match[2], 10) + 1; // ANTLRのcolumnは0始まり、Monacoは1始まり
    markers.push({
      severity: monaco.MarkerSeverity.Error,
      message,
      startLineNumber: line,
      startColumn: column,
      endLineNumber: line,
      endColumn: column + 1,
    });
  }
  monaco.editor.setModelMarkers(model, "sysml", markers);
}

function onModelUpdated(data) {
  if (data.ast_error) {
    // 8.4節: 構文エラー時は直前成功時のgraph_ir/view_ir/svg表示を維持する
    // （latestModelを更新しない）。latestModelがまだ無い（初回から構文
    // エラー）場合のみ空表示にする。エラー位置だけはText Editor側に
    // 常にマーカー表示する。
    if (!latestModel) {
      renderDiagram("");
    }
    updateErrorMarkers(data.ast_error);
    console.warn("パースエラー:", data.ast_error);
    return;
  }
  latestModel = data;
  latestFindings = data.findings || [];
  updateErrorMarkers(null);
  renderDiagram(data.svg);
  applyFindingsOverlay(latestFindings);
  renderFilterControls(data.graph_ir);
  applyNodeFilters();
  renderExplorer(data.graph_ir);
  // 選択中の要素があれば、新しいfindingsを反映してInspectorを再描画する。
  if (selectedElementId) {
    const node = latestModel.graph_ir.nodes.find((n) => n.id === selectedElementId);
    renderInspector(node || null);
  }
}

function scheduleModelUpdate() {
  if (debounceTimer !== null) {
    clearTimeout(debounceTimer);
  }
  debounceTimer = setTimeout(updateModelNow, DEBOUNCE_MS);
}

// ビュー切り替え（Group2 b7）等、デバウンスを待たず即座に反映したい場合に使う。
//
// レスポンスの到着順はリクエスト送出順と一致するとは限らない（例:
// 連続編集で複数回スケジュールされた更新が、ビュー切り替えの直後の更新より
// 後に返ってくる）。requestSequenceで「自分が最新のリクエストか」を確認し、
// 古い応答が新しい表示を上書きしないようにする（b7動作確認中に発見した
// 実害のある競合状態のため、その場で修正した）。
let requestSequence = 0;

async function updateModelNow() {
  const text = editor.getValue();
  const sequence = ++requestSequence;
  const data = await fetchModel(text);
  if (sequence !== requestSequence) return; // より新しいリクエストが発行済みなら古い応答は破棄
  onModelUpdated(data);
}

// Group2 b7(V1-2): ビュー切り替えタブ。
function setupViewTypeTabs() {
  const buttons = document.querySelectorAll(".view-type-tab");
  function refreshActiveState() {
    buttons.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.viewType === currentViewType);
    });
  }
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.viewType === currentViewType) return;
      currentViewType = btn.dataset.viewType;
      refreshActiveState();
      selectedElementId = null; // 別ビューでは同じidが存在しないことがあるため選択を解除
      renderInspector(null);
      updateModelNow();
    });
  });
  refreshActiveState();
}

// Monacoのカーソル位置(絶対offset)を含むノードのうち、source_rangeが最も
// 狭い（＝最も深くネストした）ものを探す（8.3節、Text→Diagram/Explorer）。
// 数千要素規模までは全ノード線形走査で十分という判断（8.3節に明記の既知の
// 制約。実測で問題になったら区間木等へ最適化する）。
function findNarrowestNodeAtOffset(offset) {
  if (!latestModel) return null;
  let best = null;
  let bestSpan = Infinity;
  for (const node of latestModel.graph_ir.nodes) {
    const range = node.source_range;
    if (!range) continue;
    if (range.start_offset <= offset && offset <= range.end_offset) {
      const span = range.end_offset - range.start_offset;
      if (span < bestSpan) {
        best = node;
        bestSpan = span;
      }
    }
  }
  return best;
}

loadViewState(); // Group3 b13(L2): 初回モデル取得より前に、保存済みのフィルタ・折りたたみ・レイアウト状態を復元しておく。

require.config({
  paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.0/min/vs" },
});
require(["vs/editor/editor.main"], function () {
  editor = monaco.editor.create(document.getElementById("monaco-container"), {
    value: DEFAULT_TEXT,
    language: "plaintext",
    minimap: { enabled: false },
    automaticLayout: true,
  });

  editor.onDidChangeCursorPosition((e) => {
    if (isProgrammaticEditorUpdate) return; // va14由来の書き戻しによる無限ループを防止
    const offset = editor.getModel().getOffsetAt(e.position);
    const node = findNarrowestNodeAtOffset(offset);
    if (node) {
      selectElement(node.id, { fromEditor: true });
    }
  });

  editor.onDidChangeModelContent(scheduleModelUpdate);

  setupViewTypeTabs();

  // 初回表示。
  scheduleModelUpdate();
});

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

let editor = null;
let latestModel = null; // 直近成功時のAPIレスポンス（構文エラー時もこれを表示し続ける。8.4節）
let latestFindings = [];
let debounceTimer = null;
let selectedElementId = null;

async function fetchModel(text) {
  const response = await fetch("/api/model", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return response.json();
}

function renderDiagram(svg) {
  document.getElementById("diagram-container").innerHTML = svg;
  document.querySelectorAll("#diagram-container .sysml-node").forEach((g) => {
    g.addEventListener("click", () => selectElement(g.getAttribute("data-element-id")));
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

  const relatedFindings = latestFindings.filter((f) => f.element_id === node.id);
  if (relatedFindings.length > 0) {
    const heading = document.createElement("div");
    heading.innerHTML = "<strong>Findings:</strong>";
    container.appendChild(heading);
    for (const finding of relatedFindings) {
      const row = document.createElement("div");
      row.className = `finding-row finding-${finding.severity}`;
      row.textContent = `[${finding.severity}] ${finding.message}`;
      container.appendChild(row);
    }
  }
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

// Explorer・Diagram・Text双方からの選択を一箇所に集約する。
// fromEditor=true の場合はva15（カーソル位置からの逆引き）由来のため、
// Monacoへの書き戻し（revealInEditor）はスキップする（無限ループ防止）。
function selectElement(elementId, { fromEditor = false } = {}) {
  selectedElementId = elementId;

  document.querySelectorAll(".explorer-node.selected").forEach((el) => el.classList.remove("selected"));
  document.querySelectorAll(".sysml-node.selected").forEach((el) => el.classList.remove("selected"));

  const explorerEl = document.querySelector(`.explorer-node[data-element-id="${CSS.escape(elementId)}"]`);
  if (explorerEl) explorerEl.classList.add("selected");
  const diagramEl = document.querySelector(`.sysml-node[data-element-id="${CSS.escape(elementId)}"]`);
  if (diagramEl) diagramEl.classList.add("selected");

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
  debounceTimer = setTimeout(async () => {
    const text = editor.getValue();
    const data = await fetchModel(text);
    onModelUpdated(data);
  }, DEBOUNCE_MS);
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

  // 初回表示。
  scheduleModelUpdate();
});

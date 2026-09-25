// SysML v2 Viewer フロントエンド（SysMLv2_Viewer_実装仕様書.md 8章）。
// 素のHTML+JS+Monaco Editor（CDN）構成。ビルドツールを使わない
// （2026-09-03、va11でユーザー確認の上決定）。

// Real は ScalarValues の型で、import しないと参照実装でもリンターでもエラーになる
// （2026-09-24 からリンターも参照実装に合わせて報告する）。
const DEFAULT_TEXT = `package Vehicle {
    private import ScalarValues::*;
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
// ビュー種別ごとに独立させて保持する（構造/要求トレーサビリティ/検証/
// 状態遷移/アクティビティの間では、同じ要素idでも「オフセットの基準となる
// 親」が全く異なる――状態遷移/アクティビティが使うbuild_flow_view_irは
// pinned_positions自体を受け付けない。1つのオブジェクトを共有したままだと、
// あるビューでのドラッグが別のビューのレイアウトを汚染してしまう不具合が
// あったため、この設計にした。ユーザー報告により発見・修正）。
const pinnedPositionsByView = {};

function getPinnedPositionsForView(viewType) {
  if (!pinnedPositionsByView[viewType]) pinnedPositionsByView[viewType] = {};
  return pinnedPositionsByView[viewType];
}

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
        pinnedPositionsByView,
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
    Object.assign(pinnedPositionsByView, stored.pinnedPositionsByView || {});
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
      pinned_positions: getPinnedPositionsForView(currentViewType),
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
    // 移動量は画面上のpx。拡大/縮小中はSVGの座標系と倍率分ずれるので戻す。
    if (moved) g.setAttribute("transform", `translate(${dx / diagramZoom}, ${dy / diagramZoom})`);
  }

  function onMouseUp(upEvent) {
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);
    g.removeAttribute("transform");
    if (!moved) return;
    const dx = (upEvent.clientX - startClientX) / diagramZoom;
    const dy = (upEvent.clientY - startClientY) / diagramZoom;
    getPinnedPositionsForView(currentViewType)[elementId] = toPinnedPosition(elementId, startX + dx, startY + dy);
    saveViewState();
    updateModelNow();
  }

  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup", onMouseUp);
}

// viewer/view_ir.pyの_PADDING/_LABEL_HEIGHTと一致させる（表現力強化「手動
// レイアウトの階層整合性」案B）。バックエンドはpinned_positionsを、親を持つ
// 要素については「親の内容領域の起点（親の描画位置 + パディング/ラベル高さ）
// からの相対オフセット」として解釈し、親要素はその分だけ自身のサイズを
// 拡張して子を包含する（子が親の矩形からはみ出す不整合を解消するため）。
// ここでは、既に他のピン留め要素がある場合に親自身がさらに広がっている
// 可能性までは追跡せず、親の直近の描画位置を基準に近似する（同じ親を持つ
// 複数要素を同時にはみ出す方向へピン留めする場合にのみ生じる既知の簡易化。
// 手動調整の重なり自体を解消しないという既存の割り切りの範囲内とみなす）。
const FLOW_PADDING = 8;
const FLOW_LABEL_HEIGHT = 24;

// 層状（フロー）レイアウトを使うビュー。入れ子矩形ではなく全ノードが同じ
// 平面に並ぶので、手動配置の座標の扱いが構造ビューと違う（下記参照）。
const FLOW_LAYOUT_VIEW_TYPES = new Set(["state_machine", "activity"]);

function toPinnedPosition(elementId, absoluteX, absoluteY) {
  // フローレイアウトのビューは入れ子を作らない。`$root::S`とその子の`idle`が
  // 親子ではなく同じ層配置に並ぶ兄弟として描かれるため、相対化の基準になる
  // 「親の内容領域」が存在しない。group_idを見て相対化すると、描画上どこにも
  // 対応しない原点からのオフセットを送ることになる（2026-09-18、この2ビューへ
  // 手動配置を通したときに顕在化した）。
  if (FLOW_LAYOUT_VIEW_TYPES.has(currentViewType)) {
    return { x: absoluteX, y: absoluteY };
  }
  const node = latestModel && latestModel.graph_ir.nodes.find((n) => n.id === elementId);
  if (!node || !node.group_id) {
    return { x: absoluteX, y: absoluteY }; // ルート直下は相対化の基準となる親が無いため絶対座標のまま
  }
  const parent = latestModel.view_ir.nodes.find((n) => n.id === node.group_id);
  if (!parent) {
    return { x: absoluteX, y: absoluteY };
  }
  return {
    x: absoluteX - (parent.x + FLOW_PADDING),
    y: absoluteY - (parent.y + FLOW_LABEL_HEIGHT + FLOW_PADDING),
  };
}

// Diagramの表示倍率（2026-09-25）。SVGのviewBoxはそのままにwidth/height属性
// だけを倍率分変えるので、コンテナのスクロールも拡大後の大きさに追従する。
// 図は編集のたびに描き直されるため、倍率はrenderDiagramのたびに当て直す。
const ZOOM_STEPS = [0.25, 0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];
let diagramZoom = 1;

function applyDiagramZoom() {
  const svgEl = document.querySelector("#diagram-container > svg");
  if (svgEl) {
    if (!svgEl.dataset.baseWidth) {
      svgEl.dataset.baseWidth = svgEl.getAttribute("width");
      svgEl.dataset.baseHeight = svgEl.getAttribute("height");
    }
    svgEl.setAttribute("width", parseFloat(svgEl.dataset.baseWidth) * diagramZoom);
    svgEl.setAttribute("height", parseFloat(svgEl.dataset.baseHeight) * diagramZoom);
  }
  document.getElementById("zoom-level").textContent = `${Math.round(diagramZoom * 100)}%`;
  document.getElementById("zoom-in").disabled = diagramZoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1];
  document.getElementById("zoom-out").disabled = diagramZoom <= ZOOM_STEPS[0];
}

function stepDiagramZoom(direction) {
  const next =
    direction > 0
      ? ZOOM_STEPS.find((z) => z > diagramZoom + 1e-9)
      : [...ZOOM_STEPS].reverse().find((z) => z < diagramZoom - 1e-9);
  if (next !== undefined) setDiagramZoom(next);
}

// 倍率を変えても、コンテナ中央に見えていた点が中央に残るようにスクロールを補正する。
function setDiagramZoom(zoom) {
  const container = document.getElementById("diagram-container");
  const ratio = zoom / diagramZoom;
  const centerX = container.scrollLeft + container.clientWidth / 2;
  const centerY = container.scrollTop + container.clientHeight / 2;
  diagramZoom = zoom;
  applyDiagramZoom();
  container.scrollLeft = centerX * ratio - container.clientWidth / 2;
  container.scrollTop = centerY * ratio - container.clientHeight / 2;
}

function setupZoomControls() {
  document.getElementById("zoom-in").addEventListener("click", () => stepDiagramZoom(1));
  document.getElementById("zoom-out").addEventListener("click", () => stepDiagramZoom(-1));
  document.getElementById("zoom-level").addEventListener("click", () => setDiagramZoom(1));
  // Ctrl+ホイールはブラウザ全体のズームになってしまうので、Diagram上では奪う。
  document.getElementById("diagram-container").addEventListener(
    "wheel",
    (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      stepDiagramZoom(event.deltaY < 0 ? 1 : -1);
    },
    { passive: false }
  );
  applyDiagramZoom();
}

function renderDiagram(svg) {
  document.getElementById("diagram-container").innerHTML = svg;
  applyDiagramZoom();
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

// Findingを図上のノードidへ寄せる。バックエンドが解決した`owner_element_id`を
// 使い、無い場合（古い応答など）だけ生のelement_idへ落とす。
function findingOwnerId(finding) {
  return finding.owner_element_id || finding.element_id || null;
}

function applyFindingsOverlay(findings) {
  document.querySelectorAll("#diagram-container .sysml-node").forEach((el) => {
    el.classList.remove("finding-error", "finding-warning", "finding-info");
  });

  const worstRankByElement = new Map();
  for (const finding of findings) {
    // `owner_element_id`はバックエンドが解決済みの「図上のどのノードのものか」
    // （viewer/impact.pyのattach_owner_element_ids）。element_idは要素そのもの
    // ではなく**その中の参照**を指すことがあり、その値はどのノードにも一致しない。
    // ここで生のelement_idを使っていたため、参照ノードに付いた指摘（実測で
    // 全体の16.3%）は図上に色が付いていなかった。
    const elementId = findingOwnerId(finding);
    if (!elementId) continue; // どのノードにも結び付かないfindingは図上には出さない（6.2節）
    const rank = SEVERITY_RANK[finding.severity] || 0;
    const current = worstRankByElement.get(elementId) || 0;
    if (rank > current) worstRankByElement.set(elementId, rank);
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
    // オーバーレイと同じ寄せを使う（findingOwnerId）。生のelement_idで
    // 突き合わせていたため、参照ノードに付いた指摘に対して重要度フィルタが
    // 黙って効いていなかった。
    const elementId = findingOwnerId(finding);
    if (!elementId) continue;
    if (!severitiesByElement.has(elementId)) severitiesByElement.set(elementId, new Set());
    severitiesByElement.get(elementId).add(finding.severity);
  }

  document.querySelectorAll("#diagram-container .sysml-node").forEach((el) => {
    const type = el.getAttribute("data-type");
    const typeVisible = typeFilterState[type] !== false;

    const severities = severitiesByElement.get(el.getAttribute("data-element-id"));
    // Findingを持たない要素は重要度フィルタの対象外（常に表示）。
    const severityVisible = !severities || [...severities].some((s) => severityFilterState[s] !== false);

    el.classList.toggle("filtered-out", !(typeVisible && severityVisible));
  });

  applyEdgeFilters();
}

// ノードを隠したら、そこへ繋がる線も隠す（2026-09-18）。
//
// b9のフィルタは`.sysml-node`の表示/非表示だけを切り替えていたため、端点の
// 片方が消えた線が宙に浮いたまま残っていた（ユーザー報告）。行き先の無い矢印は
// 「関連はあるが相手が描かれていない」のか「相手がフィルタで消えている」のかを
// 区別できず、§1が未解決エッジを描かない理由（宙に浮いた矢印を避ける）と
// 同じ問題を、フィルタ経由で作り出していた。
//
// **片端でも隠れていれば隠す。** 両端が隠れたときだけ消す案もあり得るが、
// それでは片端だけ隠れた線が残り、症状が半分残る。
//
// 端点の対応付けはGraph IRのedges（`from`/`to`を持つ）から引く。SVGの<line>は
// `data-edge-id`しか持たないので、idを文字列解析して端点を復元しようとしない
// こと（idは`<from>-><kind>-><to>#<連番>`という形だが、要素名に`->`を含み得る）。
function applyEdgeFilters() {
  const container = document.getElementById("diagram-container");
  if (!container) return;

  const hiddenNodeIds = new Set(
    [...container.querySelectorAll(".sysml-node.filtered-out")].map((el) =>
      el.getAttribute("data-element-id")
    )
  );
  const endpointsByEdgeId = new Map(
    ((latestModel && latestModel.graph_ir && latestModel.graph_ir.edges) || []).map((e) => [
      e.id,
      [e.from, e.to],
    ])
  );

  for (const el of container.querySelectorAll(".sysml-edge, .sysml-edge-label")) {
    const endpoints = endpointsByEdgeId.get(el.getAttribute("data-edge-id"));
    // Graph IRに無いエッジ（想定外）は触らない。消すより残す方が安全側。
    const hidden = endpoints ? endpoints.some((id) => hiddenNodeIds.has(id)) : false;
    el.classList.toggle("filtered-out", hidden);
  }
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

  // Findingのelement_idは、要素そのものではなく**その中の参照**（無名ノード）を
  // 指すことがある。無名ノードのstable_idは`<親のid>/<型>#<連番>`という形
  // （antlr_transformer.py）なので、選択要素配下の無名ノードに付いたFindingも
  // ここで拾う。名前付きの子は`::`で繋がるため、この前方一致に混ざらない。
  //
  // これを拾わないと、指摘が参照ノードに付くルール（accessible feature path、
  // import解決など）は、Explorerでどの要素を選んでもInspectorに現れない
  // （2026-09-07、c4の修正候補が表示されないことから発見）。
  const relatedFindings = latestFindings.filter(
    (f) => f.element_id === node.id || (f.element_id || "").startsWith(`${node.id}/`)
  );
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

      container.appendChild(renderFindingConfidence(finding));
      const suggestionRow = renderFindingSuggestion(finding);
      if (suggestionRow) container.appendChild(suggestionRow);
      const impactRow = renderFindingImpact(finding);
      if (impactRow) container.appendChild(impactRow);

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

// Findingの確信度（Phase C c2）。値は`LintIssue.confidence()`が返す実測値で、
// 730件コーパスでの参照実装との一致率。
//
// 見た目をどちらに寄せるかの判断: confidenceは「実測に基づく統計」であり、
// モデル事実（実線・source_range由来）でもLLM推定（b16の関連概念カード・
// b17の説明文の破線枠）でもない第三のカテゴリである。どちらへ寄せても
// 誤解を招くので、専用のクラスで「計測値」と分かる見た目にする。
//
// 数値だけを出さないのが要点。`value`は「参照実装も同じファイルを不正と
// 判定した割合」であって「同じ箇所を同じ理由で指摘した割合」ではないため、
// 件数を併記し、但し書きをtitle属性で必ず読めるようにする。
function renderFindingConfidence(finding) {
  const row = document.createElement("div");
  row.className = "finding-confidence";
  const confidence = finding.confidence;

  if (!confidence) {
    // 「未測定」と「測ったが低い」は別物なので、空欄にせず明示する。
    row.classList.add("finding-confidence-unmeasured");
    row.textContent = "　確信度: 未測定";
    row.title =
      "このルールは、参照実装との一致率を算出できる件数（そのルールだけが" +
      "発火したファイルが3件以上）に達していないため確信度を出していません。" +
      "推定値で埋めることはしません。";
    return row;
  }

  const decided = confidence.sole_agree + confidence.sole_disagree;
  row.textContent =
    `　確信度: ${confidence.value.toFixed(3)}` +
    `（このルールだけが指摘した${decided}件中${confidence.sole_agree}件で参照実装と一致）`;
  row.title = `${confidence.caveat}\n算出日: ${confidence.measured_at} / 基準: ${confidence.basis}`;
  return row;
}

// Findingの影響範囲（Phase C c3）。
//
// 起点はFindingそのもの。ただしFindingのelement_idは要素内の参照（無名ノード）
// を指すことがあり、その種のidはGraph IRに存在しない（graph_ir.pyの
// `_is_graph_node_type`が式・参照等の構造補助ノードを描画対象から外している）。
// 影響範囲の起点には、その参照を所有する名前付き要素を使う。無名ノードの
// stable_idは`<所有者のid>/<型>#<連番>`という形（antlr_transformer.py）なので、
// 最初の`/`より前を取れば所有者になる。
function impactOriginId(finding) {
  const elementId = finding.element_id;
  if (!elementId) return null;
  const separator = elementId.indexOf("/");
  return separator === -1 ? elementId : elementId.slice(0, separator);
}

function renderFindingImpact(finding) {
  if (!latestModel) return null;
  const originId = impactOriginId(finding);
  if (!originId) return null;

  const wrapper = document.createElement("div");
  wrapper.className = "finding-impact";

  const impacted = impactedFor(originId);
  if (impacted.length === 0) {
    // 「辿れる先が無い」ことも判断材料なので、黙って何も出さない選択はしない。
    const empty = document.createElement("div");
    empty.className = "finding-impact-empty";
    empty.textContent = "　影響範囲: 辿れる要素はありません";
    wrapper.appendChild(empty);
    return wrapper;
  }

  const heading = document.createElement("div");
  heading.className = "finding-impact-title";
  heading.textContent = `　影響範囲: ${impacted.length}件`;
  // 向きの意味を読み手が確認できるようにする。無向で扱っている種別が
  // 混ざっていることを隠さない。
  heading.title =
    "この指摘の対象が変わったときに影響を受けうる要素。エッジ種別ごとに" +
    "伝播の向きを決めている（型付け・継承・satisfy/verifyは参照先から" +
    "参照元へ、transition/succession/flowは流れの向きへ、connectionは" +
    "上下が決まらないため無向）。";
  wrapper.appendChild(heading);

  const byId = new Map(latestModel.graph_ir.nodes.map((n) => [n.id, n]));
  for (const item of impacted) {
    const node = byId.get(item.id);
    const label = node ? `${node.label} (${node.type})` : item.id;
    const row = document.createElement("div");
    row.className = "finding-impact-row";
    row.textContent = `　　${item.distance}次: ${label} [${item.kinds.join(", ")}]`;
    row.addEventListener("click", () => selectElement(item.id));
    wrapper.appendChild(row);
  }
  return wrapper;
}

// Findingの修正候補（Phase C c4）。構想書§14の成功条件「対象・根拠・影響範囲・
// 修正候補を同一画面で判断できる」の最後の1つ。
//
// **提示のみで、適用ボタンは置かない。** 適用・再パース・再検証は構想書§11の
// Phase Dの範囲であり、人が読んで判断する段階を飛ばさないため、ここでは
// 「こう書き換える案がある」までを見せる。
//
// 候補を持たないFindingでは何も描かない（nullを返す）。「候補なし」の行を
// 毎回出すと、候補が付いているFindingの方が埋もれる。
function renderFindingSuggestion(finding) {
  const suggestion = finding.suggestion;
  if (!suggestion) return null;

  const wrapper = document.createElement("div");
  wrapper.className = "finding-suggestion";

  const title = document.createElement("div");
  title.className = "finding-suggestion-title";
  title.textContent = `　修正候補: ${suggestion.title}`;
  // 但し書きはリンター側が候補と同じ辞書へ入れて返す。UI側の文言にせず
  // そのまま出すことで、表示経路が増えても但し書きが落ちないようにする。
  title.title = suggestion.caveat;
  wrapper.appendChild(title);

  const detail = document.createElement("div");
  detail.className = "finding-suggestion-detail";
  detail.textContent = `　　${suggestion.detail}`;
  wrapper.appendChild(detail);

  if (suggestion.edit) {
    const edit = document.createElement("div");
    edit.className = "finding-suggestion-edit";
    edit.textContent = `　　${suggestion.edit.find} → ${suggestion.edit.replace}`;
    wrapper.appendChild(edit);
  }

  const caveat = document.createElement("div");
  caveat.className = "finding-suggestion-caveat";
  caveat.textContent = `　　${suggestion.caveat}`;
  wrapper.appendChild(caveat);

  // Phase D（構想書§11）: 候補を当てた結果を**確定前に**見せる。
  // c4では意図的に適用ボタンを置かなかった。ここはその境界を越えるので、
  // 「プレビュー」と「適用」を必ず2段に分ける。差分と再検証を見ないまま
  // エディタを書き換えられる導線は作らない（§12-5 Human authority）。
  if (suggestion.edit) {
    wrapper.appendChild(renderFixPreviewControls(finding, suggestion));
  }

  return wrapper;
}

// 候補のプレビュー→適用。プレビューはバックエンド（/api/apply-fix）が
// 再パース・再検証まで済ませて返すので、ここは結果を見せるだけ。
function renderFixPreviewControls(finding, suggestion) {
  const box = document.createElement("div");
  box.className = "fix-preview";

  const previewButton = document.createElement("button");
  previewButton.type = "button";
  previewButton.className = "fix-preview-button";
  previewButton.textContent = "適用した場合を確認";
  const result = document.createElement("div");
  result.className = "fix-preview-result";

  previewButton.addEventListener("click", async () => {
    previewButton.disabled = true;
    result.textContent = "確認中...";
    try {
      const response = await fetch("/api/apply-fix", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: editor.getValue(),
          source_range: finding.source_range,
          edit: suggestion.edit,
        }),
      });
      const data = await response.json();
      renderFixPreviewResult(data, result, finding);
    } catch (e) {
      result.textContent = `確認に失敗しました: ${e}`;
    } finally {
      previewButton.disabled = false;
    }
  });

  box.appendChild(previewButton);
  box.appendChild(result);
  return box;
}

function renderFixPreviewResult(data, container, finding) {
  container.textContent = "";
  if (!data.applied) {
    container.textContent = `適用できません: ${data.error}`;
    return;
  }

  const before = latestFindings.length;
  const summary = document.createElement("div");
  if (data.ast_error) {
    // 適用するとパースできなくなる候補。**これも見せる**（確定前に分かる）。
    summary.className = "fix-preview-broken";
    summary.textContent = `この候補を当てるとパースできなくなります: ${data.ast_error}`;
  } else {
    const after = data.findings.length;
    summary.className = "fix-preview-summary";
    summary.textContent = `再検証: 指摘 ${before}件 → ${after}件`;
    const stillThere = data.findings.some(
      (f) => f.rule === finding.rule && f.message === finding.message
    );
    if (stillThere) {
      summary.textContent += "（この指摘は残ります）";
    }
  }
  container.appendChild(summary);

  if (!data.ast_error) {
    const applyButton = document.createElement("button");
    applyButton.type = "button";
    applyButton.className = "fix-apply-button";
    applyButton.textContent = "エディタへ適用";
    applyButton.addEventListener("click", () => {
      editor.setValue(data.text);
      container.textContent = "適用しました（Ctrl+Z で戻せます）";
    });
    container.appendChild(applyButton);
  }
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

// 影響範囲の走査は2026-09-14にバックエンド（viewer/impact.py）へ移した。
// 伝播方向・深さ・BFSはすべて向こうが持ち、`/api/model`が要素idごとの影響先を
// `impact`として返す。ここは描画だけを行う。
//
// 移した理由: 走査の意味論（エッジ種別ごとの伝播方向）はこのプロジェクトで最も
// 回帰が分かりにくい部分なのに、JS側には自動テストが無くブラウザのDOM確認でしか
// 触れていなかった。Python側なら既存のpytestでそのまま固定できる。加えて、
// ここの走査はFinding一覧とSVGハイライトの2箇所から呼ばれており、片方だけ
// 移すと二重実装になるため両方をまとめて移した。

function impactedFor(elementId) {
  if (!latestModel || !latestModel.impact) return [];
  return latestModel.impact[elementId] || [];
}

function findImpactedElementIds(elementId) {
  return new Set(impactedFor(elementId).map((item) => item.id));
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

  for (const impactedId of findImpactedElementIds(elementId)) {
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

// 構文エラー中であることを図の側にも出す（2026-09-18）。
//
// 8.4節の「直前に成功した図を維持する」挙動そのものは正しいが、**黙って**
// 維持していたため、ビュータブを押しても図が変わらないのが「タブが壊れて
// いる」ようにしか見えなかった（ユーザー報告）。唯一の手がかりは
// console.warn とエディタ側の赤い波線だけで、Diagramペインには何も出ない。
// 構想書§12-6 Graceful incompleteness は「何が最新の確定モデルで何が未確定か
// を区別して扱う」ことを求めているので、その区別を図の側にも表示する。
function renderStaleBanner(astError) {
  const banner = document.getElementById("stale-banner");
  if (!banner) return;
  if (!astError) {
    banner.hidden = true;
    banner.textContent = "";
    return;
  }
  banner.textContent = latestModel
    ? "⚠ テキストをパースできないため、図は直前に成功した内容のままです。ビューを切り替えても変わりません。"
    : "⚠ テキストをパースできないため、まだ図を描けません。";
  // エラー本文は長く、`; `区切りで複数のエラーが連なることがある
  // （parse_sysmlの契約）。先頭の1件だけ出し、全文はエディタ側の
  // マーカーに任せる。
  const detail = document.createElement("div");
  detail.className = "stale-detail";
  detail.textContent = String(astError).split("; ")[0];
  banner.appendChild(detail);
  banner.hidden = false;
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
    renderStaleBanner(data.ast_error);
    console.warn("パースエラー:", data.ast_error);
    return;
  }
  renderStaleBanner(null);
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
      const selected = btn.dataset.viewType === currentViewType;
      btn.classList.toggle("active", selected);
      // 見た目（class）だけでなくaria-selectedも動かす。振る舞いは元から
      // 排他選択なので、支援技術にも独立したボタン5個ではなくタブとして
      // 伝わるようにする（2026-09-18）。
      btn.setAttribute("aria-selected", String(selected));
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

// 3ペイン(Explorer/Text/Diagram)＋Inspectorのレイアウトをドラッグで可変にする。
// grid-template-columns/rowsは普段はCSSの1fr指定のままにしておき、実際に
// ドラッグを開始した瞬間（=ページのレイアウトが確定済みであることが保証される
// タイミング）にだけ、その時点の実測pxへ切り替える。ページ読み込み直後の
// スクリプト実行時点でgetComputedStyleを読んで先に固定してしまうと、
// このプレビュー環境ではまだビューポートが0×0を報告する瞬間があり、
// 極端に小さいpx値でレイアウトが壊れる不具合があったため、この設計にした。
function setupSplitters() {
  const layout = document.getElementById("layout");

  function currentColumns() {
    return getComputedStyle(layout).gridTemplateColumns.split(" ").map(parseFloat);
  }
  function currentRows() {
    return getComputedStyle(layout).gridTemplateRows.split(" ").map(parseFloat);
  }

  const MIN_TRACK_PX = 80;

  function setupColumnSplitter(splitterEl) {
    const leftIndex = Number(splitterEl.dataset.leftIndex); // 0始まり: 0=explorer, 2=text-editor
    splitterEl.addEventListener("mousedown", (startEvent) => {
      startEvent.preventDefault();
      splitterEl.classList.add("dragging");
      const startX = startEvent.clientX;
      const columns = currentColumns(); // ドラッグ開始時点で初めてpxへ固定する
      const startLeftWidth = columns[leftIndex];
      const startRightWidth = columns[leftIndex + 2]; // splitter自身(leftIndex+1)を挟んだ次のトラック

      function onMove(moveEvent) {
        const dx = moveEvent.clientX - startX;
        const leftWidth = Math.max(MIN_TRACK_PX, startLeftWidth + dx);
        const rightWidth = Math.max(MIN_TRACK_PX, startRightWidth - dx);
        columns[leftIndex] = leftWidth;
        columns[leftIndex + 2] = rightWidth;
        layout.style.gridTemplateColumns = columns.map((w) => `${w}px`).join(" ");
      }
      function onUp() {
        splitterEl.classList.remove("dragging");
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  function setupRowSplitter(splitterEl) {
    splitterEl.addEventListener("mousedown", (startEvent) => {
      startEvent.preventDefault();
      splitterEl.classList.add("dragging");
      const startY = startEvent.clientY;
      const rows = currentRows(); // ドラッグ開始時点で初めてpxへ固定する
      const startTopHeight = rows[0];
      const startBottomHeight = rows[2];

      function onMove(moveEvent) {
        const dy = moveEvent.clientY - startY;
        rows[0] = Math.max(MIN_TRACK_PX, startTopHeight + dy);
        rows[2] = Math.max(MIN_TRACK_PX, startBottomHeight - dy);
        layout.style.gridTemplateRows = rows.map((h) => `${h}px`).join(" ");
      }
      function onUp() {
        splitterEl.classList.remove("dragging");
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      }
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  document.querySelectorAll(".col-splitter").forEach(setupColumnSplitter);
  document.querySelectorAll(".row-splitter").forEach(setupRowSplitter);
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
setupSplitters(); // Monacoの読み込みを待たずに使える（editor自体には依存しない）。

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
  setupZoomControls();

  // 初回表示。
  scheduleModelUpdate();
});

# SysML v2 Viewer 対応状況

このドキュメントは、`viewer/` のSysML v2ビュアーが現時点（2026-09-03、Phase B/C完了時点）で
「何を表示し、何を表示しないか」を示す。実装（`viewer/graph_ir.py`・`viewer/view_ir.py`・
`viewer/svg_renderer.py`）を根拠に記載しており、企画段階の仕様書（`SysMLv2_Viewer_構想書.md`等、
gitignore対象の内部ドキュメント）とは表記が食い違う箇所があるため、実装の実態を優先して書いている。

## 1. 要素間の関連（エッジ）は表示されるか

**結論: 表示される。** ただし関連の種類は視覚的に区別されない。

- `sysml_v2_checker_advanced/semantic_model.py`の`build_relation_edges`が生成するエッジは
  6種類のみ: `specialization`／`subsetting`／`redefinition`（`:>`等の継承系記法）、
  `feature_typing`（型指定）、`connection`（`connect`/`bind`）、`satisfy`／`verify`
  （`satisfy requirement`／`verify`）。
- 既定の「構造」ビュー（`view_type="structure"`）では、これら6種のエッジのうち
  **解決済み（`resolved=True`）のもの全て**が描画対象になる（`viewer/graph_ir.py`の
  `_select_structure_view`は`semantic_model["edges"]`を無フィルタで渡し、`build_graph_ir`が
  `resolved`かつ両端が図中の要素であるものだけを残す）。
- しかし`viewer/svg_renderer.py`の`_render_edge`は、どのエッジも同じ`<line>`・同じ色・
  矢印なしで描画する。`viewer/view_ir.py`はView IRを作る際に`kind`（種別）自体を
  捨てており（座標`points`しか持たない）、種別情報はSVGの`data-edge-id`という属性の
  一部文字列としてしか残らない。**「AとBに関連がある」ことは線として見えるが、
  それがspecializationなのかconnectionなのかsatisfyなのかは、線を見ただけでは
  区別できない**（インスペクタでその要素を選択すれば「関連エッジ」欄にkind付きで
  一覧表示される。Group1 b1）。
- 未解決（typoや外部型など解決できない参照）のエッジは、宙に浮いた矢印を避けるため
  意図的に描画しない（`sysml_v2_checker_advanced`側で参照解決できないケースが多い場合、
  図には現れない関連が実はある、という状態になりうる）。

## 2. 対応している要素種別

`viewer/graph_ir.py`の`_is_graph_node_type`は、要素の型名が`_def`／`_usage`／`_instance`で
終わるか（`_GRAPH_NODE_SUFFIXES`）、`package`か、明示的な例外（`binding_connector`）かで
判定する。この判定はSysML v2要素の種類を限定しない汎用ルールのため、パーサー
（`sysml_v2_checker_advanced/antlr_transformer.py`）が認識するほぼ全ての定義/使用系要素が
対象になる。**「package/partしか対応していない」ということはなく**、以下も含め
確認できているだけで35種類以上が同じ「矩形＋ラベル」として描画される:

- `part_def`/`part`, `item_def`/`item`, `attribute_def`/`attribute`, `port_def`/`port`,
  `interface_def`/`interface`, `connection_def`, `connect`/`connection`（`connection_usage`）,
  `flow_def`/`flow`
- `action_def`/`action`, `state_def`/`state`, `calculation_def`/`calculation`,
  `constraint_def`/`constraint`
- `requirement_def`, `satisfy_requirement_usage`, `verify_requirement_usage`,
  `concern_def`/`concern`
- `case_def`, `analysis_case_def`, `verification_case_def`, `use_case_def`
- `view_def`, `viewpoint_def`, `rendering_def`, `metadata_def`, `allocation_def`,
  `occurrence_def`, `individual_def`, `interaction_def`, `enum_def`, `type_def`, `feature_def`
- `message_usage`, `event_occurrence_usage`, `exhibit_state_usage`, `portion_usage`,
  `subject_usage`, `actor_usage`, `stakeholder_usage`, `objective_usage`
- `package`

**対象外**（矩形として描画されない）: 式（`binary_expr`等）・文（`if_stmt`/`assignment_stmt`等）・
`connector_end`。これらはモデル構造そのものではなく式/制御構文なので、実装仕様書3.2節の
判断により最初から除外されている。

## 3. 対応しているビュー（`view_type`）

| view_type | 表示対象 |
|---|---|
| `structure`（既定） | 上記の全要素種別＋解決済みエッジ全種 |
| `requirement_traceability` | `requirement_def`/`satisfy_requirement_usage`/`verify_requirement_usage`と、そのsatisfy/verify先の要素のみ |
| `verification` | Findingが付いた要素を起点に、解決済みエッジをBFSで2次まで辿った範囲のみ |

型/重要度でのチェックボックスフィルタ（Group2 b9）や階層の折りたたみ（b10）、
手動ドラッグ配置（b11/b12）はこの3ビューいずれにも横断的に使える表示制御であり、
新しい`view_type`ではない。

## 4. 対応していないもの（ダイアグラム種別ごとの専用記法）

Viewerは**「入れ子矩形＋直線」という単一の描画スタイルのみ**を持つ
（`viewer/view_ir.py`：決定的な再帰入れ子ボックスレイアウト、`viewer/svg_renderer.py`：
矩形＋テキスト＋直線のみ）。SysML v2（およびv1由来の慣習的な図種）が想定する
ダイアグラム種別ごとの専用記法には**一切対応していない**:

- **状態遷移図**: 状態同士を結ぶ遷移矢印・ガード条件・イベントラベルの専用表記なし
  （`state_def`/`state_usage`は他の要素と同じ矩形として並ぶだけ）
- **アクティビティ図**: フロー方向の矢印、fork/join、decision/mergeノードの専用記法なし
- **シーケンス図（相互作用図）**: ライフライン、メッセージ矢印、活性区間の表記なし
- **ユースケース図**: 楕円・アクター（棒人間）等の専用アイコンなし
- **パラメトリック/計算図**: 拘束パラメータのバインディング表記なし（`connection`エッジとして
  他の関連と同じ直線で描かれるのみ）
- 一般に、矢印の向き・線種（実線/破線）・端点記号（三角/菱形等）によるUML/SysML標準の
  関係表記（継承の白抜き三角矢印、コンポジションの塗り菱形等）は無く、全ての関連が
  同じ無方向の直線として描かれる

要求トレーサビリティビュー（b6/b7）と検証ビュー（b8）のみが「特定の要素種別・関連に
絞り込む」という意味でのビュー切り替えであり、専用の描画記法を持つわけではない
（絞り込んだ後もやはり矩形＋直線で描く）。

## 5. 企画段階の記述との差異

企画書（`SysMLv2_Viewer_構想書.md`§3.3・§10-2/3）は非包含エッジを「矢印」と表現している
箇所があるが、実装（`svg_renderer.py`の`_render_edge`）は矢印マーカーを持たない無方向の
直線を描画する。同構想書§13（非目標）は「SysML v2のすべての表記・図法を一度に完全再現
すること」を明示的に初期段階の非目標としており、本ドキュメントの§4はその非目標が
実際どこまで実装されず残っているかの棚卸しにあたる。

## 6. 拡張する場合の入り口

- 矢印・線種など関連ごとの視覚表現を追加する場合: `viewer/view_ir.py`のedge構築部で
  `kind`を`points`と一緒に持ち越すよう変更し、`viewer/svg_renderer.py`の`_render_edge`が
  `kind`別にSVG属性（`marker-end`・`stroke-dasharray`・CSSクラス等）を出し分けるようにする。
- ダイアグラム種別ごとの専用記法（状態遷移図の遷移矢印等）を追加する場合: 新しい
  `view_type`を追加する既存の拡張ポイント（`viewer/graph_ir.py`の`_VIEW_SELECTORS`）に
  加え、View IR/SVGレンダラー側にもその種別専用のレイアウト・描画ロジックを新設する
  必要がある（現状の「入れ子矩形」レイアウトは全ビュー共通の1アルゴリズムしか持たない）。

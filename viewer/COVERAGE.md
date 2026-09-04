# SysML v2 Viewer 対応状況

このドキュメントは、`viewer/` のSysML v2ビュアーが現時点（2026-09-04、表現力強化
Stage 0〜3 ＋ h1〜h7 完了時点）で「何を表示し、何を表示しないか」を示す。
実装（`viewer/graph_ir.py`・`viewer/view_ir.py`・`viewer/svg_renderer.py`、および
関連抽出元の `sysml_v2_checker_advanced/semantic_model.py`）を根拠に記載しており、
企画段階の仕様書（`SysMLv2_Viewer_構想書.md`等、gitignore対象の内部ドキュメント）とは
表記が食い違う箇所があるため、実装の実態を優先して書いている。

## 1. 要素間の関連（エッジ）は表示されるか

**結論: 表示される。関連の種類も線種・矢印の形で区別される。**

- `sysml_v2_checker_advanced/semantic_model.py`の`build_relation_edges`が生成する
  エッジは10種類:
  - 継承系: `specialization`／`subsetting`／`redefinition`（`:>` 等）
  - 型付け: `feature_typing`（`:` による型指定。`::>` References も含む）
  - 接続: `connection`（`connect`／`bind`／`connection`）
  - 要求適合: `satisfy`／`verify`
  - 振る舞い: `transition`（状態遷移）／`succession`／`flow`（制御・アイテムフロー）
- 既定の「構造」ビュー（`view_type="structure"`）では、これらのエッジのうち
  **解決済み（`resolved=True`）のもの全て**が描画対象になる。
- 描画順序は**ノード → エッジ**（Stage 0で反転）。エッジの端点はノード矩形の
  **外周（境界）**で止まる（`view_ir.py`の`_rect_boundary_point`）。以前のように
  不透明な矩形にエッジが隠れることはない。
- 関連種別ごとの視覚表現（`svg_renderer.py`の`_KIND_MARKER`／`_KIND_DASH`）:

  | kind | 矢印 | 線種 |
  |---|---|---|
  | `specialization`／`subsetting`／`redefinition` | 白抜き三角 | 実線 |
  | `feature_typing` | 塗り三角 | 破線 |
  | `satisfy`／`verify` | 開いた矢印 | 破線 |
  | `connection` | なし（無方向） | 実線 |
  | `transition`／`succession`／`flow` | 塗り三角（既定へフォールバック） | 実線 |

  未知の種別（将来追加分）は塗り三角＋実線にフォールバックする。
- 未解決（typoや外部型など解決できない参照）のエッジは、宙に浮いた矢印を避けるため
  意図的に描画しない（`sysml_v2_checker_advanced`側で参照解決できないケースが多い場合、
  図には現れない関連が実はある、という状態になりうる）。インスペクタでは要素を選択すると
  「関連エッジ」欄にkind付きで一覧表示される（Group1 b1）。

## 2. 対応している要素種別

`viewer/graph_ir.py`の`_is_graph_node_type`は、要素の型名が`_def`／`_usage`／`_instance`で
終わるか（`_GRAPH_NODE_SUFFIXES`）、`package`か、明示的な例外（`binding_connector`）かで
判定する。この判定はSysML v2要素の種類を限定しない汎用ルールのため、パーサー
（`sysml_v2_checker_advanced/antlr_transformer.py`）が認識するほぼ全ての定義/使用系要素が
対象になる。**「package/partしか対応していない」ということはなく**、以下も含め
確認できているだけで35種類以上が描画される:

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

加えて、**2項かつ本体を持たない単純なconnector**（`connect_usage`／`connection_usage`／
`binding_connector`）は、h7により**矩形として描画されない**。両端を直接結ぶ1本の
`connection`エッジに畳まれ、名前/型名と両端の多重度がそのエッジのラベルになる
（例: `[1] Powers [1..*]`）。3項以上（n-ary）や本体`{ ... }`を持つconnectorは、
1本の線で表せないため従来通り矩形＋複数エッジで描く。

## 3. 対応しているビュー（`view_type`）

| view_type | 表示対象 | レイアウト |
|---|---|---|
| `structure`（既定） | 上記の全要素種別＋解決済みエッジ全種 | 入れ子矩形 |
| `requirement_traceability` | `requirement_def`/`satisfy_requirement_usage`/`verify_requirement_usage`と、そのsatisfy/verify先の要素のみ | 入れ子矩形 |
| `verification` | Findingが付いた要素を起点に、解決済みエッジをBFSで2次まで辿った範囲のみ | 入れ子矩形 |
| `state_machine` | `state_def`/`state_usage`ノードと`transition`エッジのみ | **層別フローレイアウト** |
| `activity` | `action_def`/`action_usage`ノードと`succession`/`flow`エッジのみ | **層別フローレイアウト** |

`state_machine`／`activity`の2ビューは、入れ子矩形ではなく`view_ir.py`の
`build_flow_view_ir`（`_assign_layers`によるエッジ方向に沿った層割り当て＋層ごとの
横並び配置）を使う。フロー方向に流れる配置になる。

型/重要度でのチェックボックスフィルタ（Group2 b9）や階層の折りたたみ（b10）、
手動ドラッグ配置（b11/b12、`pinned_positions`はview_typeごとにスコープされる）は
全ビューに横断的に使える表示制御であり、新しい`view_type`ではない。

## 4. 記法として対応しているもの（表現力強化 h1〜h7）

- **種別キーワードのステレオタイプ表示（h1）**: 各ノードに`«part def»`のように
  ギユメで囲んだ型キーワードを名前とは別の行で表示する。`_def`は`"part def"`、
  `_usage`/`_instance`は接尾辞を落として`"part"`と表示し、**定義と使用を区別**できる。
- **状態遷移のラベル（h2）**: `transition`エッジに`trigger [guard] / effect`形式の
  ラベルをエッジ中点付近へ描く（`semantic_model.py`の`_format_transition_label`が
  組み立て、レンダラーは描くだけ）。
- **多重度ラベル（h3）**: `feature_typing`エッジと、h7で畳まれた2項connectorの
  エッジにラベルとして多重度を載せる（`[1]`／`[1..*]`等）。
- **ポートの境界表示（h5）**: `port_def`/`port_usage`は通常の矩形ではなく、親要素の
  **境界上に置かれる小さな正方形**として描画される（`svg_renderer.py`の
  `_render_port_node`）。ラベルは外側へ出す。各ポートの左右どちらに付くかは、
  接続線が短くなる側をView IR側が選ぶ（`port_side`）。
- **角丸ノード（Stage 3）**: `state_def`/`state_usage`/`action_def`/`action_usage`は
  UML/SysML慣習に合わせ角丸矩形で描く。

## 5. 対応していないもの

- **合成／共有集約の菱形記法**: `end`ごとのaggregation kindがそもそもパースされて
  いないため、区別に必要な情報がAST側に無い（h6で明示的に見送り。新たなパーサー
  拡張が必要になった時点で改めて起票する）。
- **コンパートメント表記（h4、保留）**: attribute等を親矩形内の区画に文字列として
  畳む表記。attributeのクリック選択性を壊し、他のノード種別との視覚的一貫性も
  損なうため保留中（コストではなく設計判断）。
- **シーケンス図（相互作用図）**: ライフライン、メッセージ矢印、活性区間の表記なし
  （`message_usage`は他の要素と同じ矩形として並ぶ）。
- **ユースケース図**: 楕円・アクター（棒人間）等の専用アイコンなし。
- **パラメトリック/計算図**: 拘束パラメータのバインディング専用表記なし
  （`connection`エッジとして他の関連と同じ直線で描かれる）。
- **アクティビティ図の制御ノード**: fork/join、decision/mergeの専用記法なし
  （`activity`ビューでフロー方向の矢印と層配置までは対応済み）。
- **状態遷移図の疑似状態**: 初期状態の黒丸、終了状態の二重丸等の専用記号なし。
- エッジの交差回避・経路最適化は行わない（直線で結び、交差は許容する）。

## 6. スコープに関する方針

`SysMLv2_Viewer_構想書.md`§13（非目標）は「SysML v2のすべての表記・図法を一度に
完全再現すること」を初期段階の非目標としている。さらに
`SysMLv2_Viewer_表現力強化_機能選択計画書.md`§0.0 が、この非目標を恒久的な
役割分担として明文化した:

> 本システムは既存MBSEツールと競合せず補完する。人とAIがSysML v2のtextを共同で
> 育てる工程に特化し、完成後の正式なグラフィカル表現（OMG Notation章準拠の
> 印刷可能な成果物）は、それを最も得意とする既存ツールへMCPサーバ経由で委ねる。

したがって新しい記法対応の採否は「見た目が正式記法にどれだけ近いか」ではなく、
**「それを実施することで、人とAIが認識しなくてはいけないことが図で判断つくか」**
の1点で判断する。§5の未対応項目は、この基準に照らして現時点で優先度が低いか、
必要な情報がAST側に無いものである。

## 7. 拡張する場合の入り口

- 新しい関連種別の視覚表現を追加する場合: `svg_renderer.py`の`_KIND_MARKER`／
  `_KIND_DASH`にキーを足す（未知の種別は既定へフォールバックするため、
  エッジ抽出だけ追加しても描画は壊れない）。
- エッジにラベルを載せる場合: `semantic_model.py`側で`edge["label"]`を組み立てる
  （h2で確立した配管。レンダラーは`label`があれば中点付近に描く）。
- 新しいダイアグラム種別を追加する場合: `graph_ir.py`の`_VIEW_SELECTORS`に
  view_typeとセレクタ関数を登録し、入れ子矩形とフローのどちらでも足りなければ
  `view_ir.py`に専用レイアウトを追加する（現在は`build_view_ir`（入れ子矩形）と
  `build_flow_view_ir`（層別フロー）の2アルゴリズムがある）。
- ノードの形状を種別ごとに変える場合: `svg_renderer.py`の`_ROUNDED_NODE_TYPES`
  （角丸）や`_render_port_node`（ポート）が先例。

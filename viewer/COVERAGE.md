# SysML v2 Viewer 対応状況

このドキュメントは、`viewer/` のSysML v2ビュアーが現時点（2026-09-18、表現力強化
Stage 0〜3 ＋ h1〜h7、および構想書 Phase C・Phase D 完了時点）で
「何を表示し、何を表示しないか」「検証結果に対して何ができるか」を示す。
実装（`viewer/graph_ir.py`・`viewer/view_ir.py`・`viewer/svg_renderer.py`・
`viewer/impact.py`・`viewer/apply_fix.py`・`viewer/backend/app.py`、および
関連抽出元の `sysml_v2_checker_advanced/semantic_model.py`・`lint_issue.py`・
`fix_candidates.py`）を根拠に記載しており、
企画段階の仕様書（`SysMLv2_Viewer_構想書.md`等、gitignore対象の内部ドキュメント）とは
表記が食い違う箇所があるため、実装の実態を優先して書いている。

§1〜§4 が描画（何が図に出るか）、§5 が検証結果まわり（Findingに対して何ができるか）、
§6 以降が未対応項目とスコープ方針である。

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

型/重要度でのチェックボックスフィルタ（Group2 b9）、階層の折りたたみ（b10）、
手動ドラッグ配置（b11/b12）は、全ビューに横断的にかかる表示制御であって
新しい`view_type`ではない。ただし**フローレイアウトの2ビューでの対応状況は
一様ではない**:

| 表示制御 | `structure`／`requirement_traceability`／`verification` | `state_machine`／`activity` |
|---|---|---|
| フィルタ（b9） | ○ | ○（描画済みSVGの表示/非表示なのでレイアウトに依存しない） |
| 折りたたみ（b10） | ○ | **×**（フラットな層配置では「子を畳む」が構造ビューと同じ意味にならない） |
| 手動ドラッグ配置（b11/b12） | ○ | ○（2026-09-18対応） |

**フィルタはノードだけでなく、端点が隠れたエッジも隠す**（2026-09-18対応。
`app.js`の`applyEdgeFilters`）。それまでは`.sysml-node`の表示/非表示しか
切り替えておらず、片端の消えた線が宙に浮いたまま残っていた。行き先の無い矢印は
「関連はあるが相手が描かれていない」のか「相手をフィルタで消した」のかを
区別できず、§1が未解決エッジを描かない理由と同じ問題をフィルタ経由で
作り出していた。**片端でも隠れていれば隠す**（両端が隠れたときだけ消す規則では
片端だけ隠れた線が残り、症状が半分残る）。エッジのラベル（h2の遷移ラベル、
h3の多重度）も同じ`data-edge-id`を持たせてあり、線と一緒に消える。

手動配置は`pinned_positions`としてview_typeごとに分けて保存され（保存先は
ブラウザの`localStorage`。§5.6と同じ割り切り）、タブを切り替えても、
ページを読み込み直しても、そのビューで置いた位置が復元される。

**座標の意味が2系統ある**点に注意すること。`build_view_ir`（入れ子矩形）では、
親を持つノードの値は親の内容領域を基準にした**相対オフセット**である。
一方`build_flow_view_ir`では全ノードが同じ平面に並び相対化の基準となる親が
存在しないため、値は**絶対座標**である。フロントエンドの`toPinnedPosition`が
`currentViewType`を見てどちらで送るかを決めている。どちらの経路でも、
ピン留めしたノード以外は動かない。

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

  判定に票を持つのは**配線されるエッジだけ**（`_PORT_SIDE_EDGE_KINDS` =
  `connection`／`flow`）。型付け・継承・要求トレース・振る舞いの順序は、
  モデル上の関係であってポートに刺さる線ではないので数えない。
  **2026-09-18までは全エッジを数えており**、ポートの型（`port po : Pw;`の
  `feature_typing`）が判定に票を投じていた。`port def`は普通パッケージ直下に
  置かれるためそのボックスは入れ子のポートから見て常に同じ方向にあり、本物の
  接続の判定を押し切ることがあった（実測例: 本物の接続は左を52対54で選んで
  いたのに、型エッジが右を60対46で選び、合計112対100で右に決まっていた）。
  副作用として`port def`自身の左右が、他の要素が増えてパッケージが広がる
  だけで入れ替わっていた。
- **角の形で定義と使用を区別（2026-09-18）**: **定義（`_def`）は直角、
  使用（`_usage`/`_instance`）は角丸**で描く（`svg_renderer.py`の
  `_is_usage_type`）。SysML v2の図記法が定義と使用を角の形で区別しているので、
  それに合わせたもの（仕様書の Table 4 "Definition and Usage – Representative
  Notation"）。独自の工夫ではなく規格への追従である。

  **これは2026-09-18にStage 3の実装を訂正したものである。** それ以前は角丸が
  「状態・アクション」を表しており、`state_def`と`action_def`も角丸だった。
  これはUMLで状態・アクションを角丸で描く慣習を持ち込んだもので、SysML v2の
  記法と衝突していた――角の形がdef/usageを意味する記法の下では、
  「`state def`が角丸」は「これはusageである」と言っているに等しい。
  定義側を直角に直したのはその訂正であって、記法忠実度を下げる判断ではない。

  h1のステレオタイプ表記（«part def» と «part»）でも区別自体はできるが、
  あれは読まないと分からない。形は読まずに分かる。

  境界上のポート（`_render_port_node`）はこの規則の対象外。ポートは矩形では
  なく境界上の小さな正方形で描いており、角丸を入れても形が潰れて読み取れない
  うえ、「ポートである」ことは既に形で分かっている。

## 5. 検証結果（Finding）まわりでできること

ここは描画ではなくレビュー支援側の能力で、構想書 Phase C（Verification Review）と
Phase D（AI-assisted Editing）で入った。

### 5.1 Findingの取得と図上への反映

`/api/model` が `findings`（`LintIssue.to_dict()` の配列）を返し、重大度ごとに図上へ
オーバーレイする。`view_type="verification"`（§3）はFindingが付いた要素を起点に
範囲を絞ったビューである。

**Findingは要素そのものとは限らない場所に付く。** 要素の中の参照（無名ノード、
idは`<所有者のid>/<型>#<連番>`）に付くことがあり、そのidはGraph IRに存在しない。
また、描画対象にならない深さの入れ子フィーチャを指すこともある。

そのため`/api/model`は各Findingに **`owner_element_id`（そのFindingを表示すべき
描画ノードのid、無ければ`null`）** を付けて返す。解決は
`viewer/impact.py`の`resolve_finding_node_id`が行い、**図上のオーバーレイ・
重要度フィルタ・インスペクタ・検証ビューの起点がすべてこれを使う**（同じ寄せを
各所で書き分けると片方だけ直す事故が起きる。実際、オーバーレイとフィルタだけが
生の`element_id`を使い続けて黙って効いていなかった。2026-09-18に修正）。

解決の規則は「**自分自身が描画ノードならそれ。違えば、描画ノードに当たるまで
末尾から1階層ずつ落とす**」（区切りは`::`と`/`）。
`impact_origin_id()`（最初の`/`より前を無条件に取る）を流用しないこと。
影響範囲の起点としては正しいが、ここでは**切りすぎる**――
`...::home_b/port_usage#0::commandReceived`のように`/`を含むidが
そのまま描画ノードである例が実在し（コーパスの`/`付きFinding 231件中172件）、
無条件に切ると指摘の主語ではなく数階層上の祖先に色が付く。

コーパス実測（2026-09-18、819ファイル・1,414 Finding）で、図上のノードに
結び付くFindingは **872件 → 1,242件**（+370）になり、**元から正しく当たっていた
ものが別ノードへ移った件数は0**。

### 5.2 確信度（confidence）

`LintIssue.to_dict()` の `confidence` が、そのルールが参照実装とどれだけ一致したかの
**実測値**を返す（`sysml_v2_checker_advanced/rule_confidence.json` に同梱）。
`{value, sole_agree, sole_disagree, basis, caveat, measured_at}` の形で、
値だけを切り出せないよう根拠と但し書きを必ず同じ辞書に入れて返す。

- 供給源は730件コーパス×参照実装の実測のみ。LLMにもヒューリスティックにも由来しない。
- `value` は「参照実装も同じファイルを不正と判定した割合」であって
  「同じ箇所を同じ理由で指摘した割合」ではない。**一致率の上限**であり真の精度ではない。
- 単独発火が閾値に満たないルールは `null`。**推定で埋めない**（「未測定」と
  「測ったが低い」を混同させないため）。インスペクタは未測定をそう明示する。

### 5.3 影響範囲

`viewer/impact.py`。Findingを起点に、解決済みエッジを**有向**にBFSで2次
（`IMPACT_DEPTH`）まで辿る。伝播方向はエッジ種別ごとに違う（`IMPACT_DIRECTION`）:

| 種別 | 向き | 理由 |
|---|---|---|
| `specialization`／`subsetting`／`redefinition`／`feature_typing` | 逆 | 宣言は参照先に依存する（`x : T` のTが変われば x が影響を受ける） |
| `satisfy`／`verify` | 逆 | `by`側が変われば充足・検証の主張が影響を受ける |
| `transition`／`succession`／`flow` | 順 | from=source なのでエッジの向きがそのまま |
| `connection` | 無向 | どちらが上流とも言えない |

未知の種別は無向として扱う（取りこぼすより広く見せる方が用途上安全側）。
`/api/model` が `impact` として全ノード分をまとめて返す。
2026-09-14に`app.js`から移設し、方向づけの表ごと `tests/test_viewer_impact.py` で固定した。

### 5.4 修正候補

`sysml_v2_checker_advanced/fix_candidates.py`。形は
`{title, detail, edit: {find, replace}, caveat}`。

**方針: 書き換え方が一意に決まるルールにだけ付ける。** もっともらしいだけの候補は
指摘そのものの信頼を削るので、候補が書けないルールは `suggestion=None` のままにする。
現在候補を持つのは3つ:

| ルール | 候補 |
|---|---|
| `_check_accessible_feature_paths` | 不正な`::`境界を`.`へ |
| interface／allocation usage の種別エラー | 期待する種別のdefinitionでの型付けへ（同一ファイル内に候補が1つだけのときのみ。複数あれば一意に決まらないので候補なし） |
| `_check_package_level_feature_redefinition` | `redefines` → `subsets`（**意味が変わる**ので但し書き付き） |

MCPサーバ経由の利用者にもそのまま届く（`GraphRAG/mcp_server.py` の
`_format_lint_issue` が `suggestion` を通す）。

### 5.5 候補の適用（Phase D）

**プレビューと確定を必ず2段に分ける。** 「適用した場合を確認」を押すと
`/api/apply-fix` が適用済みテキストを作り、`/api/model` と同じ経路で再パース・
再検証して返す。UIは「指摘 N件 → M件」を見せ、そのうえで適用するかを利用者が決める
（構想書§12-5 Human authority）。**適用すると壊れる候補**（当てた結果パースできなく
なるもの）も `ast_error` としてそのまま見せる。

適用契約（`viewer/apply_fix.py`）: Findingの`source_range`が示す範囲内に現れる
最初の`find`を`replace`に置き換える。範囲を限るので、同じ文字列がファイル中の別の
場所にあっても巻き込まない。なお`end_offset`は**終端の文字を含む**ので、
Pythonのスライスは`[start_offset : end_offset + 1]`である。

### 5.6 レビュー状態と履歴

Open／Accepted／Resolved／False-Positive の状態遷移と履歴を持つが、
**保存先はブラウザの`localStorage`だけである。** サーバー側永続化は見送った
（c5、2026-09-07のユーザー判断。Viewerの位置づけがローカル開発ツールであるため）。
したがってブラウザ・端末をまたいで引き継がれず、レビュアー間でも共有されない。
手動ドラッグ配置（`pinned_positions`）とビュー状態も同じくlocalStorageに載る。

### 5.7 RAG連携

- `/api/related-concepts` — 選択要素の型・ラベルでGraphRAGを引き、関連概念を返す。
- `/api/explain` — 選択要素やFindingの説明をLLMで生成する。**実課金**なので
  選択のたびに自動では走らせず、明示的な要求時のみ呼ぶ。引用は決定的に付ける。

いずれも直接importではなく**MCP stdio経由**で呼ぶ。README が
`HybridRAG/rag/`・`GraphRAG/graphrag/` 配下を内部実装と明記しており、
公開契約はMCPサーバの側だからである（Group4 b15の判断）。

## 6. 対応していないもの

### 描画

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
- **ポートの左右は最短にならないことがある**（構造的な限界、2026-09-18に確認）。
  `port_side`は**ポートごとに独立して**決まり、判定材料は相手の親ボックスの中心x
  である。そのため次の2つが漏れる。
  1. **相手ポートが親のどちら側の辺に付いたか**が分からない（中心で近似するため）。
     相手ポートの位置を見て測り直す2巡目を試したが、互いに繋がった2つのポートが
     相手の1巡目の位置を見て揃って反対側へ移り、線がかえって伸びた（実測 68→116）。
     繋がったポート対の最短化は「両方を同じ側へ」という**連立した**判断であって、
     片方ずつ貪欲に決める形では表現できない。
  2. そもそも`build_view_ir`は子を**縦一列**に積むだけで横方向の配置を持たないため、
     ほとんどのノードのxがほぼ同じになり、左右の判定に使える差がほとんど無い。
     入れ子の深さぶんのインデント（8px）と親ボックスの幅の違いが効くだけになる。

  1本1本を最短にすることが目的なら、ポートの左右ではなく**横方向のレイアウトを
  持つこと**から始める話になる。現状は「接続の向きの手がかり」程度に読むこと。

### レビュー支援側

- **レビュー状態のサーバー側永続化**: §5.6のとおり見送り（設計判断）。共同レビューや
  端末をまたいだ継続はできない。
- **意図からのパッチ生成**: 「この構成を冗長化したい」のような意図を起点に候補を
  作る経路は無い。現在の修正候補はチェッカーのルールが機械的に組み立てたものだけで、
  LLMは介在しない。構想書 Phase E（Generation Review Workbench）の範囲。
- **複数候補の比較**: 1つのFindingに対する候補は最大1つで、複数案を並べて比べる
  UIは無い。
- **外部MBSEツールへの描画委任**: §7の位置づけが前提にしている「完成後の正式な
  描画を外部ツールへMCP経由で委ねる」経路は、**まだ実装も実証もされていない**
  （`mcp_servers.json` に該当サーバは無い）。多くの非目標がこの未検証の前提の上に
  載っていることは意識しておくこと。
- **どの要素にも結び付かないFinding**: `element_id`が空のFindingは、図上の
  オーバーレイにも重要度フィルタにも載らない（§5.1の`owner_element_id`が`null`に
  なる）。寄せ先が無いものを無理にどこかへ結び付けると無関係な要素が指摘を
  持っているように見えるため、**意図的に据え置いている**。
  コーパス実測（2026-09-18）で全Findingの**12.0%（1,414件中170件）**がこれに当たるが、
  **169件は単一ルール`_check_conjugated_port_typing`由来**で、そちらは
  `source_range`も持たないため図にもテキストにも現れない。Viewer側の設計では
  なくチェッカー側のルールの問題なので、直すならそちら
  （参照実装で境界を実測してから、という本プロジェクトの手順に従うこと）。
  残りは`import NoSuchPackage::*;`のように**存在しない名前**を指すFindingで、
  こちらは結び付ける相手が無いのが正しい。
- **フロントエンドの自動テスト**: `viewer/frontend/app.js` にJSのテスト基盤は入れて
  いない（P2-Gの判断、2026-09-14）。検証手順はREADMEの「Viewerフロントエンドの
  検証方針」に明文化してある。回帰を抱えたいロジックはPython側へ移す
  （§5.3の影響範囲走査がその先例）。

## 7. スコープに関する方針

`SysMLv2_Viewer_構想書.md`§13（非目標）は「SysML v2のすべての表記・図法を一度に
完全再現すること」を初期段階の非目標としている。さらに
`SysMLv2_Viewer_表現力強化_機能選択計画書.md`§0.0 が、この非目標を恒久的な
役割分担として明文化した:

> 本システムは既存MBSEツールと競合せず補完する。人とAIがSysML v2のtextを共同で
> 育てる工程に特化し、完成後の正式なグラフィカル表現（OMG Notation章準拠の
> 印刷可能な成果物）は、それを最も得意とする既存ツールへMCPサーバ経由で委ねる。

したがって新しい記法対応の採否は「見た目が正式記法にどれだけ近いか」ではなく、
**「それを実施することで、人とAIが認識しなくてはいけないことが図で判断つくか」**
の1点で判断する。§6の未対応項目（描画側）は、この基準に照らして現時点で優先度が
低いか、必要な情報がAST側に無いものである。

**「再現しない」と「違う意味で描く」は別である。** この基準が言っているのは
記法を*網羅しなくてよい*ということであって、規格と*矛盾する*描き方をしてよい
ということではない。描かない記法は情報が減るだけだが、規格が別の意味に使って
いる視覚的手がかりを流用すると、読み手を積極的に誤らせる。2026-09-18に訂正した
角丸がその実例で、UMLの慣習から「状態・アクション＝角丸」を持ち込んだ結果、
角の形でdef/usageを区別するSysML v2の記法の下では`state def`が
「usageである」と主張する図になっていた（§4）。新しい視覚的手がかりを足すときは、
規格がその手がかりを既に別の意味に使っていないかを先に確かめること。

なお**この基準が適用されるのは描画・記法の話に限る。** §5のレビュー支援側
（確信度・影響範囲・修正候補）は「図で判断つくか」ではなく構想書§12の設計原則
（4 Explain before persuade、5 Human authority）が採否の基準になる。

## 8. 拡張する場合の入り口

- 新しい関連種別の視覚表現を追加する場合: `svg_renderer.py`の`_KIND_MARKER`／
  `_KIND_DASH`にキーを足す（未知の種別は既定へフォールバックするため、
  エッジ抽出だけ追加しても描画は壊れない）。
- エッジにラベルを載せる場合: `semantic_model.py`側で`edge["label"]`を組み立てる
  （h2で確立した配管。レンダラーは`label`があれば中点付近に描く）。
- 新しいダイアグラム種別を追加する場合: `graph_ir.py`の`_VIEW_SELECTORS`に
  view_typeとセレクタ関数を登録し、入れ子矩形とフローのどちらでも足りなければ
  `view_ir.py`に専用レイアウトを追加する（現在は`build_view_ir`（入れ子矩形）と
  `build_flow_view_ir`（層別フロー）の2アルゴリズムがある）。
- ノードの形状を種別ごとに変える場合: `svg_renderer.py`の`_is_usage_type`
  （def/usageで角の形を分ける）や`_render_port_node`（ポート）が先例。
  出力を変えると`tests/fixtures/viewer/vehicle_sample.svg`のゴールデン比較が
  落ちるので、**差分が意図した箇所だけであることを確かめてから**再生成すること。
- 修正候補を持つルールを増やす場合: 候補の文面と組み立ては
  `sysml_v2_checker_advanced/fix_candidates.py` へ集約してあるので、そこへ
  ビルダー関数を足し、ルール側は`LintIssue(..., suggestion=...)`と1行渡すだけにする
  （ルール名キーの一覧表にしないのは、「そのルールが何を根拠に落としたか」を
  知らないと作れない候補があるため。§5.4の`::`境界がその例）。適用経路（§5.5）は
  `edit`さえ埋まっていればそのまま動くので、UI側の変更は要らない。
- 影響の伝播方向を変える／エッジ種別を増やす場合: `viewer/impact.py`の
  `IMPACT_DIRECTION`にキーを足す（未知の種別は無向へフォールバックするので、
  足さなくても壊れない）。`tests/test_viewer_impact.py`が表ごと固定しているので、
  変えたら期待値も一緒に動かすこと。
- 確信度を測り直す場合: `scripts/recheck_local_only.py --rule-stats` →
  `scripts/build_rule_confidence_table.py` で`rule_confidence.json`を作り直す。
  チェッカー本体は`confidence`の有無に依存しないので、テーブルが無くても動く。

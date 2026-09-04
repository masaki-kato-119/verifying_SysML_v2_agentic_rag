# SysML v2 独自チェッカー vs OMG公式Pilot Implementation 比較評価レポート

作成日: 2026-08-28
対象: `sysml_v2_checker_advanced/`（ANTLR4ベース、`sysml_v2_checker_advanced/antlr/SysMLMin.g4`という「最小」文法）
比較対象: OMG公式 SysML v2 Pilot Implementation（`sysml-v2-pilot-implementation` 由来の Jupyter kernel jar 経由）

**本レポートのスコープは「問題の洗い出し」までであり、修正の実装は別プランとする。**
次にこのプロジェクトへ入る人が本レポートだけを読んで各問題を再現・着手できることを目標に、
具体的なファイルパス・行番号・コード抜粋・診断メッセージを添えている。

---

## 1. 評価方法の要約

### 1.1 参照実装の入手・実行方法

- 参照実装は OMG公式リポジトリ `Systems-Modeling/SysML-v2-Pilot-Implementation` 由来。実体は
  `eval/sysml_reference/vendor/_extracted/share/jupyter/kernels/sysml/jupyter-sysml-kernel-0.61.0-all.jar`
  （Jupyter用SysMLカーネルのfat jar。**バージョン0.61.0に固定**）。
- 呼び出しは `eval/sysml_reference/vendor/RefDriver.java`（本評価用に用意した薄いラッパー）経由。
  内部で `org.omg.sysml.interactive.SysMLInteractive`（Jupyterカーネルが内部で使うのと同じAPI）の
  `si.loadLibrary(libraryDir)` → `si.process(text, false)` を呼び、`Issue`（Xtextの構文/意味診断）を
  JSONへシリアライズして標準出力に返す。
- Python側 `eval/sysml_reference/reference_driver.py` が `java -cp <classpath> RefDriver <libraryDir> <tmpfile>`
  をサブプロセスとして**サンプル1件ごとに新規JVMを起動**して呼び出す。

### 1.2 サンプル収集元

- `eval/sysml_samples/manifest.json` に730件をカタログ化（各: path, source_repo, category, sha256等）。
- カテゴリ: `official_examples`(322, 公式サンプル集), `tooling_fixtures`(192, サードパーティOSSツールのテストフィクスチャ),
  `xpect_test_cases`(126, 公式Pilot Implementation自身のXPECTテストから抽出。意図的なエラー例を含む),
  `curated_models`(36), `industry`(28), `educational`(25), `textbook`(1)。

### 1.3 比較ハーネスの仕組み

- `scripts/run_reference_comparison_eval.py` が各サンプルについて (a) ローカル
  `sysml_v2_checker_advanced.parser.parse_sysml`/`lint_sysml`、(b) 参照実装（上記RefDriver経由）を
  それぞれ実行し、診断を `{"severity", "line", "message"}` に正規化して
  `eval/sysml_results/<sha256[:16]>.json` へ保存する。
- 両実装の「error重大度の診断が1件でもあるか」を突き合わせ、`agreement` を
  `both_clean` / `both_error` / `local_only_error` / `reference_only_error` /
  `local_crash` / `reference_crash` / `both_crash` に分類する。
- `scripts/analyze_reference_comparison.py` で、`local_only_error`/`reference_only_error` バケットの
  メッセージを（引用符付き識別子・数値を `<X>`/`<N>` に正規化して）クラスタリングし、頻出パターンを抽出できる。

### 1.4 既知の制約（ハーネス自体の限界。診断結果を解釈する際に必ず考慮すること）

1. **単一ファイル解析が前提。** ローカルチェッカーもRefDriver呼び出しも1ファイル単位で完結しており、
   同一リポジトリ内の他ファイルへのimport解決は行わない（RefDriverは標準ライブラリ`libraryDir`のみロードする）。
   そのため、複数ファイルに分割されたモデル（例: `apollo-11-sysml-v2`）の一部だけを渡すと、
   参照実装側は「他ファイルの型/名前空間を解決できない」という大量のカスケードエラーを返す。
   これは両実装の設計上の限界であり、本レポートの多くの `reference_only_error` はこれが原因（§4.2参照）。
2. **参照実装はJVM起動オーバーヘッドが大きく、重いファイルでタイムアウトする。**
   `reference_crash` が5件（`official_examples`2件・`tooling_fixtures`2件・`industry`1件）発生しているが、
   いずれもJVMの起動/処理時間が確保したタイムアウトを超えたことによるもので、ファイル内容とは無関係。
   「両実装の相違」としてはカウントしていない。
3. **【本評価で新たに判明した重要な制約】参照実装（jar v0.61.0の`SysMLInteractive.process()`)は、
   ビジビリティ修飾子（`public`/`private`/`protected`）を伴わない裸の`import`文を、
   ファイル中のどの位置にあっても構文エラーとして拒否する。** 詳細と再現手順は §4.3 を参照。
   これは真の文法違反ではなく参照実装（もしくは評価に使っているJupyterカーネルAPIの使い方）側の
   アーティファクトである可能性が高く、`both_error`/`reference_only_error` の集計値を押し上げている。
4. `both_error`（両実装がエラーを検出）は「両実装が同じ問題を検出した」ことを意味しない。
   §5 のサンプリング調査の通り、実際にはほぼ全てのケースで両者は**別々の理由**でエラーを出している。

---

## 2. サンプルコーパスの統計

### 2.1 カテゴリ別件数と agreement 集計（730件全件、確定値）

| agreement | 件数 | 割合 |
|---|---:|---:|
| both_clean | 253 | 34.7% |
| local_only_error（ローカルのみエラー＝偽陽性の疑い） | 231 | 31.6% |
| both_error（両方エラー。ただし中身は別問題のことが多い） | 215 | 29.5% |
| reference_only_error（参照実装のみエラー＝偽陰性の疑い） | 26 | 3.6% |
| reference_crash（JVMタイムアウト。無関係として除外） | 5 | 0.7% |

### 2.2 カテゴリ別 agreement 内訳

| category | 総数 | both_clean | local_only_error | both_error | reference_only_error | reference_crash |
|---|---:|---:|---:|---:|---:|---:|
| official_examples | 322 | 108 (33.5%) | 154 (**47.8%**) | 55 (17.1%) | 3 (0.9%) | 2 |
| tooling_fixtures | 192 | 103 (53.6%) | 20 (10.4%) | 54 (28.1%) | 13 (6.8%) | 2 |
| xpect_test_cases | 126 | 36 (28.6%) | 47 (37.3%) | 36 (28.6%) | 7 (5.6%) | 0 |
| curated_models | 36 | 1 (2.8%) | 7 (19.4%) | 27 (75.0%) | 1 (2.8%) | 0 |
| industry | 28 | 1 (3.6%) | 2 (7.1%) | 24 (85.7%) | 0 | 1 |
| educational | 25 | 4 (16.0%) | 1 (4.0%) | 18 (72.0%) | 2 (8.0%) | 0 |
| textbook | 1 | 0 | 0 | 1 (100%) | 0 | 0 |

**official_examples（OMG公式サンプル集そのもの）の `local_only_error` 率が47.8%と突出して高い**。
つまりローカルの文法（`SysMLMin.g4`）は、OMG自身が公開している「正しいはずのSysML v2」の半数近くを
パースできていない。curated_models/industry/educational は `both_error` 率が非常に高いが、これは
§1.4-1の単一ファイル解析の限界（他ファイル依存の未解決参照カスケード）が主因であり、
文法カバレッジ不足とは別の問題として扱う（§5参照）。

---

## 3. 優先順位付けされた問題点一覧

優先度は「頻度（該当ファイル数）」と「影響度（構文の一大分類が丸ごと使えないか／個別ルールの欠落か／
単発の軽微な差か）」で判定している。件数は `eval/sysml_results/*.json` を機械的に集計した実測値。

### P0: 構文の一大分類が丸ごとパースできない（影響度・頻度ともに最大）

#### P0-1. `qualifiedName`（`.`区切りのみ）が式・alias対象・transition端点・代入対象などで
広範に使われており、`::`（パッケージ修飾参照）を受理できない

- **症状**: 式の中の列挙リテラル参照（`EnumType::literal`）、`alias`の対象、`transition`の
  `first`/`then`/`accept`対象、`succession`のconnector end、`assign`の代入先などで
  `::`を書くと `mismatched input '::' expecting {...}` / `no viable alternative at input '::'`。
- **頻度**: `local_only_error`中で**33ファイル・83件**（このバケット単独では最大規模の症状グループ）。
  実際には後述P0-4のtransition関連や、あらゆる式コンテキストに波及するため、実際の影響範囲はさらに広い。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1165-1167`
  ```
  qualifiedName
      : (ID | QUOTED_NAME) ('.' (ID | QUOTED_NAME))*
      ;
  ```
  一方、`::`と`.`の両方を受理する`namespacePath`（同ファイル1912-1914行）が別に存在するが、
  `inheritanceClause`の基底型やredefine対象など一部の場所でしか使われていない。
  式(`expression`の`nameRefExpr`, 1783行目付近)・`aliasStmt`(288-290行)・`transitionStmt`の
  `source`/`trigger`/`target`(1653-1659行)・`connectorEnd`(1150-1152行、`transitionStmt`や
  `successionStmt`が使う)・`assignmentStmt`の`target`(1314-1316行、`simpleName`のみでdot pathすら不可)
  は軒並み`qualifiedName`または`simpleName`を使っており、`::`を通せない。
- **再現例**:
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/org.omg.sysml.interactive/VehicleModel_2_Simplified.sysml:42`
    ```
    if ignitionCmd.ignitionOnOff==IgnitionOnOff::on
    ```
    → ローカル: `mismatched input '::' expecting {'[', 'bind'}` (line 42, column 75)
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/training/01. Packages/Documentation Example.sysml:13`
    ```
    alias Torque for ISQ::TorqueValue;
    ```
    → ローカル: `mismatched input '::' expecting {'{', ';'}` (line 13, column 21)
- **推定される修正方向（診断のみ、実装はスコープ外）**: `expression`の`nameRefExpr`・`aliasStmt`の
  `target`・`transitionStmt`の`source`/`trigger`/`target`・`connectorEnd`・`assignmentStmt`の`target`を
  `qualifiedName`から`namespacePath`（またはそれに準ずる`::`対応版）へ置き換える。広範囲に影響するため
  慎重な回帰テストが必要。

#### P0-2. Occurrence の portion usage（`snapshot`/`timeslice`）が極端に簡略化されすぎている

- **症状**: `snapshot`/`timeslice`usageの本体（`{ ... }`）・多重度・`ordered`修飾・`= value`値代入・
  `first`/`then`による連鎖宣言のいずれも受理できない。
- **頻度**: `local_only_error`中で**8ファイル・9件**が直接該当（ただし実際にはOccurrence章の構文全体が
  連鎖的に壊れるため、1ファイルあたりの実エラー数は非常に多い。例えば
  `Time Slice and Snapshot Example.sysml`は`local_only_error`パターン集計の最頻出クラスタ
  （`mismatched input ';' expecting {'[', 'bind'}`919件、`no viable alternative`491件等）の主要な発生源）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:158-162`
  ```
  portionUsageStmt
      : kind=('snapshot' | 'timeslice') simpleName ';'
      ;
  ```
  名前+`;`のみで、本体・多重度・値代入・`ordered`のいずれも無い。また`bareThenStmt`
  (1599-1601行、`'then' target=qualifiedName ';'`)は「既存要素への参照」のみを想定しており、
  `then timeslice ownership[0..*] ordered { ... }`のような「`then`に続けてportion usageを
  宣言と同時に連鎖させる」複合形には未対応。
- **再現例**: `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/training/27. Occurrences/Time Slice and Snapshot Example.sysml:9-25`
  ```sysml
  part def Vehicle {
      timeslice assembly;
      first assembly then delivery;
      snapshot delivery {                       // ← 本体を持てない
          attribute deliveryDate : Date;
      }
      then timeslice ownership[0..*] ordered {  // ← then+多重度+ordered+本体、すべて未対応
          snapshot sale = start;                 // ← "= value" 未対応
          ref item owner : Person[1];
          timeslice driven[0..*] { ... }
      }
      snapshot junked = done;                    // ← "= value" 未対応
  }
  ```
  → ローカル: `missing '}' at 'snapshot'` (line 11), `mismatched input ';' expecting {'[', 'bind'}` (line 16, column 24) 等、多数のカスケードエラー。
- **他の該当例**: `.../examples/Simple Tests/OccurrenceTest.sysml:20`, `.../Individuals Examples/JohnIndividualExample.sysml:11`,
  `eval/sysml_samples/raw/sysml-v2-models/models/example_family/family.sysml:103`。
- **修正方向の当たり**: `portionUsageStmt`を他のusage系ルール（`itemUsage`等）と同型に拡張し、
  `multiplicitySpec?`・`'ordered'?`・`('=' value=expression)?`・`('{' partBodyElement* '}' | ';')`を追加する。
  加えて`bareThenStmt`/`bareFirstStmt`に「宣言を伴う連鎖」の代替を追加する必要がある。

#### P0-3. `individual` はプレフィックス修飾子であるべきなのに、独立した構文として実装されている

- **症状**: 公式コーパスでは`individual`は`occurrence def`/`item def`/`part def`/`action def`および
  それらのusageの**直前に付くプレフィックス修飾子**として使われる（例:
  `individual occurrence def IO2 { ... }`, `individual item ii : II1;`）。しかし現在の文法は
  `individual def X`（単独）と`individual NAME (: ID)?;`（単独usage）の2形しか受理しない。
- **頻度**: `local_only_error`中で**6ファイル・20件**（`IndividualTest.sysml`だけで6件の
  `extraneous input 'individual'`）。加えて`both_error`側でも`apollo-11-sysml-v2/Technical/SystemPackage.sysml`
  で同型のエラーが発生（該当箇所は他の理由でも同時にエラーになっているため`both_error`に分類されている）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:203-209`
  ```
  individualDef
      : isAbstract='abstract'? 'individual' 'def' simpleName inheritanceClause? '[' ']' ( '{' partBodyElement* '}' | ';' )
      ;
  individualUsage
      : isAbstract='abstract'? 'individual' simpleName ( ':' ID )? ';'
      ;
  ```
  `individual occurrence def`/`individual item def`/`individual part def`/`individual action def`や、
  `individual item ii : II1;`/`individual part p : IP1;`のような「`individual` + 他のキーワード」の
  組み合わせを受理する規則が存在しない。
- **再現例**: `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/Simple Tests/IndividualTest.sysml`
  ```sysml
  package IndividualTest {
      individual def IO1;                    // ← これは通る
      individual occurrence def IO2 {        // ← 通らない: line 3
          individual io : IO1;               // ← 通らない: line 4
      }
      individual item def II1 { ... }        // ← 通らない: line 7
      individual part def IP1 { ... }        // ← 通らない: line 18
      individual action def AP1 { ... }      // ← 通らない: line 29
  }
  ```
  → ローカル: `extraneous input 'individual' expecting {...}` (line 3/4/7/8/15/18/19/26/29...)
- **修正方向の当たり**: `occurrenceDef`/`itemDef`/`partDef`/`actionDef`（および対応する`*Usage`）の
  先頭に`isIndividual='individual'?`を追加する設計に変更するのが最も自然。現行の
  `individualDef`/`individualUsage`は「`individual`単体で他の型キーワードを伴わない」特殊ケース
  （`individual def IO1;`）用として残すか統合するかは要検討。

#### P0-4. メタデータのプレフィックス注釈`#Type`とショートハンド`@Type {...}`が未実装

- **症状**: `#Type`（要素宣言の前に置く「Prefix Metadata Annotation」）と、`@Type { ... }`/`@Type;`
  （`metadata`キーワードを省略した短縮usage形）のどちらも文法に存在しない。特に`@`はレキサーに
  トークンとして登録すらされておらず、`token recognition error at: '@'`という最も重症な形で失敗する。
- **頻度**: `local_only_error`中で `@` 絡み22ファイル・100件、`#` 絡み9ファイル・48件（重複ファイルを除くと
  実質25ファイル前後）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4`には`#`を使う規則が式の添字アクセス演算子
  `#(...)`（1675-1677行付近のコメント参照）としてしか存在せず、「宣言の前に置くprefix annotation」としての
  `#Type`は影も形もない。`@`はどの規則にもlexerトークンにも登場しない。`metadataUsage`(423-425行)は
  `'metadata' simpleName inheritanceClause? ...`のみで、`@`によるショートハンド形の代替を持たない。
- **再現例**: `eval/sysml_samples/derived/sysml-v2-pilot-implementation-xpect/src/org/omg/sysml/xpect/tests/simpletests/MetadataTest.sysml`
  ```sysml
  #Security enum def ClassificationLevel { ... }      // line 7: プレフィックス注釈
  ref y {
      @Classified { classificationLevel = ... }        // line 28: @ショートハンド usage
      @Security;                                        // line 31
  }
  private ref #Classified #Security z1;                 // line 34: 複数プレフィックス注釈
  abstract #Classified z2;                               // line 35
  ```
  → ローカル: line 28で `token recognition error at: '@'`（レキサーレベルの失敗）、
  line 7/34/35等で `extraneous input '#' expecting {...}`。
- **修正方向の当たり**: (a) レキサーに`@`トークンを追加する、(b) `metadataUsage`に
  `'@' typeRef=namespacePath ( '{' partBodyElement* '}' | ';' )`のようなショートハンド代替を追加する、
  (c) ほぼ全ての宣言規則（`topLevelElement`/`partBodyElement`が委譲する多数の規則）の先頭に
  `('#' namespacePath)*`のようなprefix annotationの反復を追加する、という3段階の対応が必要になる
  比較的大掛かりな拡張。影響ファイル数・影響範囲（宣言のほぼ全種類が対象になりうる）の両方から見て
  優先度は高いが、実装コストも大きい。

#### P0-5. State machine の `accept`/`do` トリガー・エフェクト節が狭すぎる、
`accept ... then X;`という「`first`省略の暗黙遷移」形が未対応

- **症状**:
  1. `transitionStmt`の`accept`節はトリガーを`qualifiedName`（単純参照）としてしか受理できず、
     `accept when EXPR`（式ガード付きトリガー）や`accept at EXPR`（クロックトリガー）を受理できない。
  2. `transitionStmt`の`do`節は`effect=qualifiedName`（既存アクションへの単純参照）としてしか受理できず、
     `do send new X() to Y`のようなインラインsendアクションを受理できない。
  3. `stateBodyElement`には`initialTransitionMember`(`'then' target=qualifiedName ';'`、1537-1539行)は
     あるが、「`accept`/`do`付きで、かつ`first`を省略した暗黙遷移」（`accept X do Y then Z;`のように
     enclosing stateを暗黙のsourceとする形）に対応する規則が無い。
  4. `assignmentStmt`の代入先`target`が`simpleName`のみで、`counter.count := ...`のようなドット区切り
     パスを受理できない。
- **頻度**: `local_only_error`中で send/accept/assign関連が**21ファイル・72件**。
- **根本原因/再現例**:
  - `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1653-1659`（`transitionStmt`）:
    ```
    transitionStmt
        : 'transition' simpleName? 'first' source=qualifiedName
          ( 'accept' trigger=qualifiedName (':' triggerType=namespacePath)? ('via' via=qualifiedName)? )?
          ( 'if' guard=expression )?
          ( 'do' ('action')? effect=qualifiedName )?
          'then' target=qualifiedName ';'
        ;
    ```
    `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/validation/05-State-based Behavior/5-State-based Behavior-1a.sysml:120`
    ```
    transition 'normal-degraded'
        first normal
        accept when 'sense temperature'.temp > vehicle1_c1.Tmax   // ← "when EXPR" 未対応
        do send new 'Over Temp'() to vehicle1_c1.vehicleController // ← インラインsend 未対応
        then degraded;
    ```
    → ローカル: `mismatched input 'accept' expecting 'then'` (line 120) （前の文がまだ閉じられていない扱いになりカスケード）
  - `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1486-1511`（`stateBodyElement`。
    `initialTransitionMember`(1537-1539行)はあるが accept/do付き版が無い）:
    `eval/sysml_samples/derived/sysml-v2-pilot-implementation-xpect/src/org/omg/sysml/xpect/tests/simpletests/StateTest.sysml:17-19,25`
    （XPECTコメントで `noErrors` と明記されている＝公式に正しい構文）
    ```sysml
    state S1;
        accept s : Sig
        do action D
        then S2;                 // "first"省略の暗黙遷移。stateBodyElementに対応する規則が無い
    ...
    accept Exit then done;       // 同上の最短形
    ```
  - `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1314-1316`（`assignmentStmt`）:
    ```
    assignmentStmt
        : isThen='then'? visibilityIndicator? ('action' actionName=simpleName?)? 'assign'? target=simpleName op=('=' | ':=') value=expression ';'
        ;
    ```
    `eval/sysml_samples/derived/.../simpletests/AssignmentTest.sysml:29`
    ```
    do assign counter.count := counter.count + 1;   // target が simpleName のみで dot path 不可
    ```
- **修正方向の当たり**: `transitionStmt`のtrigger節に`'when' guard=expression`・`'at' clock=expression`の
  代替を追加、effect節に`sendActionStmt`/`assignmentStmt`等の既存インラインアクション規則を埋め込む。
  `stateBodyElement`に「`('accept' ... )? ('if' ...)? ('do' ...)? 'then' target ';'`（`first`無し）」の
  代替を追加。`assignmentStmt`の`target`を`qualifiedName`（またはP0-1の対応後は`namespacePath`）に拡張。

---

### P1: 複数ファイルに影響する、個別の構文要素の欠落

#### P1-1. ShortName注釈 `<name>` が一部の `_def` 規則にしか実装されていない

- **症状**: `part <'1'> b: B;`のように、usage側の宣言名の前に短縮名`<...>`を書く形が
  `partUsage`等の**usage系規則には一つも実装されていない**（`packageDef`/`partDef`/`itemDef`/
  `viewDef`/`metadataDef`という一部の`_def`規則にのみ実装済み）。
- **頻度**: `local_only_error`中で**14ファイル・70件**。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:988-997`（`partUsage`。他の`*Usage`規則も同様）
  にはshortName節が無い。一方 `partDef`(707-709行)には`('<' shortName=(ID | QUOTED_NAME) '>')?`がある。
- **再現例**:
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/Simple Tests/PartTest.sysml:6`
    ```
    part <'1'> b: B;
    ```
    → ローカル: `extraneous input '<' expecting {...}` (line 6, column 7) に続き
    `mismatched input '>' expecting {...}` (line 6, column 11)。
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/State Space Representation Examples/EVSample.sysml:231`
    ```
    requirement <C1> rangeRequirementSmall :> smallEVRequirement : RangeRequirement { ... }
    ```
- **修正方向の当たり**: `partUsage`/`itemUsage`/`requirementUsage`等のusage系規則にも
  `('<' shortName=(ID | QUOTED_NAME) '>')?`を（`simpleName`の直前あたりに）追加する。

#### P1-2. `exhibit state` usage が `partBodyElement` に登録されておらず、型節も無い

- **症状**: `exhibit state 'name': 'Type';`のように、`part def`本体内に書く`exhibit state`文が
  パースできない。
- **頻度**: 直接該当は2ファイルのみだが、`exhibit state`は状態表明の主要構文の一つ。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:154-156`
  ```
  exhibitStateUsageStmt
      : 'exhibit' 'state' simpleName ';'
      ;
  ```
  が(a) `packageBodyElement`/`topLevelElement`（109-111行付近）にしか登録されておらず
  `partBodyElement`（832-930行）には無い、(b) 型節（`: 'Type'`）を持たない。
- **再現例**: `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/validation/05-State-based Behavior/5-State-based Behavior-1a.sysml:12,17`
  ```sysml
  part def VehicleA {
      perform action 'provide power': 'Provide Power';
      exhibit state 'vehicle states': 'Vehicle States';   // line 12: part def本体内、かつ型節あり
  }
  part def VehicleController {
      exhibit state 'controller states': 'Controller States';  // line 17
  }
  ```
  → ローカル: `extraneous input 'exhibit' expecting {...}` (line 17)（part def本体内では未登録のため）。
- **修正方向の当たり**: `exhibitStateUsageStmt`を`partBodyElement`にも追加し、
  `('exhibit' 'state' simpleName (':' namespacePath)? ';')`のように型節を付与する。

#### P1-3. `stateDef`（ネストした状態機械定義）が `partBodyElement` に登録されていない

- **症状**: `part def X { state def Y { ... } }`のように、part def本体内に`state def`（`state`ではなく
  `state def`、つまりネストした状態定義）を直接書く形がパースできない。`state`（defなし、usage形）は
  `partBodyElement`に登録済みだが`state def`は登録されていない。
- **頻度**: 1ファイル内で15箇所（`smart-home-complex.sysml`のような大規模実サンプルで、同一構造が
  繰り返し使われるため1ファイルへの影響が大きい）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1475-1477`
  ```
  stateDef
      : isAbstract='abstract'? 'state' 'def' simpleName inheritanceClause? ( '{' stateBodyElement* '}' | ';' )
      ;
  ```
  は`packageBodyElement`(54行目)と`stateBodyElement`(1490行目、state-in-state用)にしか登録されておらず、
  `partBodyElement`(832-930行)のリストには含まれていない（`stateUsage`は914行目で登録済み）。
- **再現例**: `eval/sysml_samples/raw/sysml-v2-lsp/examples/smart-home-complex.sysml:175`
  ```sysml
  part def SomeDevice {
      ...
      state def DeviceLifecycle {     // line 175: part def本体内の state def
          doc /* ... */
          state provisioning;
          ...
      }
  }
  ```
  → ローカル: `extraneous input 'def' expecting {'{', ';', ':', ':>', ':>>', 'subsets', 'redefines', '[', 'type', ID, QUOTED_NAME}` (line 175, column 14)
  （`state`の直後は`stateUsage`としてしかマッチせず、`simpleName`ではない予約語`def`が来て失敗する）。
  同ファイル内に同型のエラーが10箇所（level 175, 307, 414, 456, 492, 705, 745, 818, 1023 他）繰り返される。
- **修正方向の当たり**: `partBodyElement`のリストに`stateDef`を追加する（1行追加で解決する見込みの
  高い、コストの低い修正）。

#### P1-4. `connectionEndMember` の型節が conjugation `~` に非対応（`portUsage` とは非対称）

- **症状**: `end port p4: ~P;`のように、connection/interface定義本体の`end`メンバーで
  conjugatedな型参照（`~TypeName`）を書くとパースできない。同じ「型の共役」記法は`portUsage`
  （`port p2: ~P;`）では既に対応済みであり、実装の非対称性が原因。
- **頻度**: **5ファイル・15件**。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:647-656`
  ```
  connectionEndMember
      : 'end' (endName=simpleName endMult=multiplicitySpec?)?
        kind=('occurrence' | 'port' | 'item')?
        isRef='ref'?
        innerName=simpleName?
        (':' ID)?                         // ← conjugated='~'? が無い
        multiplicitySpec?
        ...
  ```
  一方 `portUsage`（1858-1867行）は `(':' conjugated='~'? ID)?` と既に対応済み。
- **再現例**:
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/Simple Tests/ConjugationTest.sysml:16`
    ```sysml
    interface def I {
        end p1: P;
        end p2: ~P;     // line 16
    }
    ```
    → ローカル: `extraneous input '~' expecting ID` (line 16, column 10)
  - `eval/sysml_samples/raw/sysml-v2-models/models/example_family/family.sysml:94`
    ```
    end communicationPartnerB : ~VerbalExchange;
    ```
- **修正方向の当たり**: `connectionEndMember`の`(':' ID)?`を`(':' conjugated='~'? ID)?`へ変更するだけの
  極めて小さな修正で直る見込み。

#### P1-5. `comment`/`doc` 文の `about <ref>` 節・`locale <string>` 節が未実装

- **症状**: `comment about C /* ... */`（コメント対象の明示）、`doc locale "en_US" /* ... */`
  （ロケール注釈）のいずれも文法に無い。
- **頻度**: `local_only_error`中で**6ファイル・9件**（ただし公式コーパスの`comment`/`doc`利用のかなりの
  割合がこれらの節を伴うため、実際の影響は「該当メッセージ数」以上に広い）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:255-265`
  ```
  commentStmt
      : 'comment' simpleName? DOC_COMMENT
      ;
  documentationStmt
      : 'doc' simpleName? DOC_COMMENT
      ;
  textualRepresentationStmt
      : ('rep' simpleName)? 'language' STRING_LITERAL DOC_COMMENT
      ;
  ```
  いずれも`about`/`locale`節を持たない（`locale`は文法コメントで「未対応」と明記済みだが、`about`は
  未実装であることの記述が無く見落とされていた可能性がある）。
- **再現例**:
  - `eval/sysml_samples/raw/sysml2-cli/tests/fixtures/official/phase2-basic/Comments.sysml:13`
    ```
    comment about Comments /* Comment about Package */
    ```
    → ローカル: `extraneous input 'Comments' expecting DOC_COMMENT` (line 13, column 16)
  - `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/examples/Simple Tests/CommentTest.sysml:32`
    ```
    doc locale "en_US" /* Documentation about Package */
    ```
    → ローカル: `extraneous input '"en_US"' expecting DOC_COMMENT` (line 32, column 12)
- **修正方向の当たり**: `commentStmt`に`('about' about=namespacePath)?`を、
  `documentationStmt`/`textualRepresentationStmt`に`('locale' locale=STRING_LITERAL)?`を追加する。

---

### P2: 単一構文要素の欠落（影響ファイル数は少ないが再現性は高い）

#### P2-1. `messageUsage` に `of Type[mult]`（ペイロード型節）が無い

- **頻度**: 4ファイル・27件（`17-Sequence Modeling`系・`webshop`・`family.sysml`）。
- **根本原因**: `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1379-1385`
  ```
  messageUsage
      : isAbstract='abstract'? 'message' simpleName?
        (':' ID)?
        multiplicitySpec?
        ...
  ```
  `'of' payloadType=namespacePath multiplicitySpec?`という代替形が無い。
- **再現例**: `eval/sysml_samples/raw/sysml-v2-pilot-implementation/sysml/src/validation/17-Sequence Modeling/17b-Sequence-Modeling.sysml:26`
  ```
  message publish_message of Publish[1];
  ```
  → ローカル: `mismatched input 'of' expecting {'{', ';', ':', ':>', ':>>', 'subsets', 'redefines', '['}` (line 26, column 26)

#### P2-2. `succession flow NAME from A to B;`（succession + flow の複合キーワード形）が未実装

- **頻度**: 4ファイル・6件。
- **根本原因**: `successionUsage`（`sysml_v2_checker_advanced/antlr/SysMLMin.g4:1580-1585`）は
  `'succession' simpleName? multiplicitySpec? 'first' ... 'then' ...`という`first`/`then`形のみで、
  `'succession' 'flow' simpleName 'from' ... 'to' ...;`という別形（flowと succession を組み合わせた
  `SuccessionFlowUsage`)には対応していない。
- **再現例**: `eval/sysml_samples/raw/sysml2-cli/tests/fixtures/official/phase2-basic/FlashlightExample.sysml:48`
  ```
  succession flow onOffCmdFlow from sendOnOffCmd.onOffCmd to produceDirectedLight.onOffCmd;
  ```
  → ローカル: `extraneous input 'flow' expecting {'[', 'type', 'first', ID, QUOTED_NAME}` (line 48, column 13)

---

## 4. 参照実装側だけがエラーを検出するケース（`reference_only_error`, 26件）の内訳

### 4.1 本当にローカルのlintルールが未実装なもの（真の偽陰性）

`sysml_v2_checker_advanced/linter_rules/*.py`をgrepし、以下のルールがいずれも実装されていないことを確認した
（`state_machine_rules.py`にはentry/do/exit の**kindタグ検証**はあるが、「1つしか持てない」という
**重複数チェック**は無いなど、"似て非なる"チェックはあっても対象の意味検証そのものは無い）:

| 参照実装のメッセージ | 該当ファイル数 | 未実装の確認方法 |
|---|---:|---|
| `An attribute must be typed by attribute definitions.` 等 "must be typed by" 系 | 多数（ただし§4.2参照） | - |
| `Cannot override a binding feature value` | 7 | `linter_rules/`に該当ロジック無し |
| `Only one return parameter is allowed` | 2 | `linter_rules/definition_usage_rules.py`にreturn parameter数チェック無し |
| `A state may have at most one entry/do/exit action.` | 各2 | `state_machine_rules.py`はkindタグ検証のみ、重複数チェック無し |
| `Only one subject is allowed.` / `Subject must be first parameter.` | 各2 | `linter_rules/`に該当ロジック無し |
| `Subsetting/redefining feature cannot be nonunique if subsetted/redefined feature is unique` | 2 | `linter_rules/`に該当ロジック無し |
| `Must invoke a behavior or a behavioral feature` | 1 | `linter_rules/`に該当ロジック無し |
| `Must be an accessible feature (use dot notation for nesting)` | 3 | `linter_rules/`に該当ロジック無し |

これらはいずれも `eval/sysml_samples/derived/sysml-v2-pilot-implementation-xpect/.../validation/invalid/*.sysml`
という、公式Pilot Implementation自身が「1ファイル1ルール」の意図的invalidテストとして用意しているもの由来で、
頻度（1〜7件）は低いが、対応するSysML v2の意味制約が明確でテストケースも既製であるため、
実装難易度は比較的低いと考えられる。

代表例: `eval/sysml_samples/derived/sysml-v2-pilot-implementation-xpect/src/org/omg/sysml/xpect/tests/validation/invalid/RequirementSubject_Invalid.sysml`
（"Only one subject is allowed." / "Subject must be first parameter." を意図的に踏む最小fixture）。

### 4.2 単一ファイル解析の設計限界によるもの（意図的なスコープ外。バグではない）

`Couldn't resolve reference to Type/Feature/Namespace 'X'.`、`An attribute/usage must be typed by ... definitions.`、
`An occurrence, item or part must be typed by occurrence definitions.` 等は、いずれも
「標準ライブラリ型（`Real`/`Integer`/`String`/`Boolean`等）や他ファイルの型を`import`していない、
または他ファイルの要素を参照している」ことに起因する。例:

- `eval/sysml_samples/raw/sysml2-cli/tests/fixtures/modify/delete-basic.sysml`
  （フォーマッタ/編集操作のテストフィクスチャで、`ScalarValues`のimportを意図的に省略している）
- `eval/sysml_samples/raw/sysml-v2-lsp/test/fixtures/valid/camera.sysml`, `vehicle.sysml`
- `eval/sysml_samples/raw/sysml-v2-pilot-implementation/org.omg.sysml.xpect.tests/src/Vehicle.sysml`

ローカルチェッカーは単一ファイルの構文解析＋ヒューリスティックなlintに徹しており、標準ライブラリや
他ファイルに対するフル型解決を行わない設計になっている。これは仕様上の判断であり、直ちに「バグ」として
扱うべきではないが、**将来的にローカルライブラリのスタブ（`ScalarValues`等の主要な型名だけを
"既知の組み込み型"として許可するテーブル）を持たせる**ことで、この種の偽陰性の一部（および
`local_only_error`側での過剰な"Couldn't resolve"的誤検出があれば、それ）を減らせる可能性がある。

### 4.3 【重要・要フォローアップ】参照実装（比較ハーネス）が裸の `import` 文を一律で拒否する問題

`reference_only_error`のうち3件（`e3003_valid_import.sysml`, `Import_Visibility_Invalid.sysml`,
`CalculationExample.sysml`）は、いずれも一見単純な `import X::*;`（ビジビリティ修飾子
`public`/`private`/`protected`無し）が原因で、参照実装が
`mismatched input 'import' expecting '}'` → `no viable alternative at input '::'` →
（ファイル末尾で）`extraneous input '}' expecting EOF` という一連の構文エラーを返している。

**これは当初「ローカルの文法が緩すぎて`import X::`という不正構文を見逃している」という仮説だったが、
本調査で全く異なる、より根深い原因であることが判明した。**

#### 検証手順と結果

1. `.venv`のPythonから`eval/sysml_reference/reference_driver.py`の`run_reference_check`を直接呼び出し、
   最小の再現ケースを作成:
   ```python
   text = '''package Foo {
       import ISQ::*;
       part def Bar;
   }
   '''
   ```
   → 参照実装は `mismatched input 'import' expecting '}'` 等のエラーを返す（**再現可能**）。
2. `import`を`private import`に変えるだけで、上記エラーは**消える**（クリーンにパースされる）。
   `public import`/`protected import`でも同様に成功する。
3. 位置を変えても（ファイル先頭、`part def`の後、ファイル冒頭のimportなし版等）、
   ビジビリティ修飾子を伴わない`import`は**常に**失敗する。
4. コーパス全体（730件）を機械的に走査したところ、「ビジビリティ修飾子なしの`import`文を含むファイル」は
   **37件**存在し、そのうち**32件が`both_error`、5件が`reference_only_error`に分類され、
   `both_clean`または`local_only_error`に分類されたものは1件も無かった**（100%の再現率）。
5. `RefDriver.java`は内部で `SysMLInteractive.process(text, false)`（Jupyterカーネル用APIの
   第2引数`false`）を呼んでいる。この第2引数を`true`に変えて再コンパイル・再実行しても
   **同じエラーが再現した**ため、この引数が原因ではないことも確認済み。
6. コーパス全体では、ビジビリティ修飾子付きimportを使うファイルが407件あるのに対し、
   修飾子なしimportのみを使うファイルは25件（他に12件は両方のスタイルを混在）と、
   明らかに少数派のスタイルである。

#### 結論と推奨事項

- ローカルの`importStmt`文法（`visibilityIndicator? 'import' namespacePath ('::' '*')? ';'`、
  `sysml_v2_checker_advanced/antlr/SysMLMin.g4:1878-1880`）は、ビジビリティ修飾子を任意
  （`?`）として扱っており、これはSysML v2の一般的なスタイル・他の"bare import"利用例と矛盾しない。
  **この点についてローカルの文法を「参照実装に合わせて修飾子必須にする」修正は推奨しない**
  （参照実装側の挙動の方が疑わしいため）。
- 原因は次のいずれかと推測される（本調査では特定until至らず）:
  (a) 評価に使っている `jupyter-sysml-kernel-0.61.0-all.jar` 固有の既知の不具合、
  (b) `SysMLInteractive`というJupyterカーネル向けAPI（`next()`/`counter`フィールドを持つ、
  対話的セッション/セル評価を想定した設計）を「1ファイルまるごとの静的解析」目的で流用していることに
  起因する使い方の不整合。
- **今後の対応案**: (1) 同梱されているjarから`SysMLInteractive`以外のバッチ向けエントリポイント
  （もしあれば）を探して切り替える、(2) 別バージョンのPilot Implementation jarで同じ再現ケースを試す、
  (3) 少なくとも本レポートの`both_error`/`reference_only_error`の集計値を解釈する際は、
  「ビジビリティ修飾子なしimportを含むファイル37件」を別枠として扱う、のいずれか。
  **`both_error`215件のうち32件（約15%）はこの問題が(部分的に)混入していることに注意。**

---

## 5. `both_error`（両実装がエラーを検出、215件）のサンプリング調査

自動分類ツールは未整備のため、`random.seed(42)`で12件をランダム抽出し目視確認した
（`eval/sysml_results/*.json`を直接参照。作業に使ったスクリプトは
`C:\Users\...\scratchpad\both_error_sample.py`、内容は本文末尾の付記を参照）。

**結論: 12件中ほぼ全てで、ローカルと参照実装は「別々の理由」でエラーを検出しており、
"both_error"は「両方が同じ問題を見つけた」ことを意味しない。**

代表例:

| ファイル | ローカルの検出内容 | 参照実装の検出内容 | 一致度 |
|---|---|---|---|
| `AllocationUsage_Invalid.sysml`（xpect） | `extraneous input ':' expecting {...}`（構文） | `An allocation must be typed by allocation definitions.`（意味） | 不一致（別問題） |
| `apollo-11-sysml-v2/Technical/SystemPackage.sysml` | `individual`修飾子の構文ギャップ（P0-3） | 他ファイル未import起因の大量`Couldn't resolve reference`カスケード | 不一致（別問題） |
| `smart-home-complex.sysml` | `state def`のpartBodyElement未登録（P1-3）× 10箇所 | `ScalarValues`未import起因の`Couldn't resolve reference to Type 'Real'/'String'/...` | 不一致（別問題。このファイルはimport文自体を1つも持たない） |
| `TrafficLightIntersectionRequirements.sysml` | `actor driver`等のキーワード直後スペース欠落によるトークン化失敗の疑い（未分類、要個別調査） | §4.3の「裸のimport」問題＋型未解決カスケード | 不一致（別問題） |
| `.../training/12. Binding Connectors Example-1.sysml` | 独自ルールで `Import 'Port Example::*' が存在しないパッケージ 'Port Example' を参照しています` を検出 | `Couldn't resolve reference to Namespace ''Port Example''.`から始まる型解決カスケード | **一致（数少ない、実質同じ根本原因を検出できている好例）** |

最後の例（Binding Connectors Example-1.sysml）は、ローカルの「存在しないパッケージへのimportを検出する」
独自ルールが、参照実装の型解決失敗と実質的に同じ根本原因（存在しないパッケージ`'Port Example'`への
import）を捉えられている数少ない一致例であり、ローカルチェッカーの独自ルールにも一定の価値があることを
示している。

**示唆**: `both_error`を「両実装が合意した高信頼の問題」として扱うのは誤りである。今後の分析・改善では
`both_error`内の個々のケースについても、両者の診断メッセージを突き合わせて「同じ根本原因か」を
判定する仕組み（例えば行番号の近接度や意味カテゴリでのラフなマッチング）を用意すると、
より正確な「両実装一致率」が把握できる。

---

## 6. まとめ: 優先順位付き問題一覧（再掲）

| 優先度 | 問題 | 該当ファイル数(概算) | 種別 |
|---|---|---:|---|
| P0-1 | `qualifiedName`が`::`非対応（式/alias/transition/assign等広範） | 33+ | 文法カバレッジ（横断的） |
| P0-2 | Occurrence portion usage（snapshot/timeslice）が簡略化されすぎ | 8+ | 文法カバレッジ（大分類） |
| P0-3 | `individual`が独立構文でプレフィックス修飾子になっていない | 6+ | 文法カバレッジ（大分類） |
| P0-4 | メタデータ注釈 `#Type`/`@Type{}` が未実装（`@`はlexerにも無い） | 25+ | 文法カバレッジ（大分類） |
| P0-5 | transition/stateのaccept/do節が狭い、暗黙遷移形が無い、assign対象がdot path非対応 | 21+ | 文法カバレッジ（大分類） |
| P1-1 | ShortName `<name>` がusage系規則に無い | 14 | 個別ルール欠落 |
| P1-2 | `exhibit state`がpartBodyElement未登録＋型節無し | 2 | 個別ルール欠落 |
| P1-3 | `stateDef`がpartBodyElement未登録 | 1ファイルに集中(10箇所) | 個別ルール欠落（低コスト修正） |
| P1-4 | `connectionEndMember`がconjugation `~`非対応（portUsageとの非対称） | 5 | 個別ルール欠落（低コスト修正） |
| P1-5 | `comment`/`doc`の`about`/`locale`節が無い | 6 | 個別ルール欠落 |
| P2-1 | `messageUsage`に`of Type[mult]`節が無い | 4 | 単発 |
| P2-2 | `succession flow ... from ... to ...;`複合形が無い | 4 | 単発 |
| §4.1 | 意味検証ルール7種が未実装（return parameter数、entry/do/exit重複、subject制約、nonunique制約、behavior呼び出し制約、accessible feature制約、binding feature override制約） | 各1〜7 | lintルール欠落（reference_only_error） |
| §4.2 | 単一ファイル解析の設計限界による型未解決カスケード | 多数 | 意図的スコープ外（バグではない） |
| §4.3 | 参照実装が裸のimportを一律拒否する（ハーネス側の疑わしい挙動） | 37（both_error内32含む） | ハーネス/参照実装側の制約（要フォローアップ） |

---

## 7. 本レポートのスコープについて

本レポートは**問題の洗い出し（analyze_findings + report）までをスコープ**としており、
上記いずれの問題についても文法・lintルールの修正実装は行っていない。修正は別プランとして
今後着手されることを想定し、各問題について再現可能な最小限の情報（ファイルパス・行番号・
該当する文法規則の行番号・診断メッセージ）を記載した。

修正着手時の推奨順序は §6 の表の優先度（P0 > P1 > P2）に従うことを推奨するが、
P0-4（メタデータ注釈）はP0の中でも実装コストが大きい一方、P1-3・P1-4は1〜数行の修正で
解決できる可能性が高く「低コスト・即着手可能」なクイックウィンとして先に着手する価値がある。
また §4.3（参照実装が裸のimportを拒否する問題）は、ローカルの修正ではなく評価ハーネス自体の
検証・改善が必要な項目であるため、他の項目と並行して別途フォローアップすることを推奨する。

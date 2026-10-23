# 自作チェッカー × Pilot 差分評価: ベースライン（2026-10-15）

研究の問い: 自作 SysML v2 Checker（`sysml_v2_checker_advanced`、ANTLR4 + Python）は、OMG Pilot 実装（0.62.0）と同じ水準の判定に到達できるか。
このファイルは、その出発点の測定結果。手順は各スクリプトの docstring、自動生成の詳細は `results/latest/REPORT.md`。

## 測り方

- コーパス 288 件（`build_corpus.py`）
  - LLM 生成モデル 15（Opus 6 / Sonnet 9、AGV 課題。複数ファイルは 1 テキストに連結）
  - 検証済み最小例 5（Pilot でエラー 0・警告 0 を確認済みのテーマ別モデル）
  - 負例 127（誤りをわざと入れた probe。1 ファイル 1 件）
  - 変異体 141（検証済み最小例に、LLM が実際にした誤りを 1 か所だけ入れたもの。12 種類）
- 正解: Pilot（sysml-mcp-server の `SysMLService.validate`）の診断（`label_pilot.py`）
- 自作: `lint_text_with_locations` とパースエラー（`run_local.py`）
- 突き合わせ（`compare.py`）: エラーを「行 + 種類」（構文・未解決参照・型の種類・アクセス範囲 など）に正規化して比べる。警告は除く。変異体は元のモデルとの差分で評価する

## 結果

| 指標 | 値 |
| --- | --- |
| unit 単位の見逃し率（Pilot はエラー、自作は問題なし） | 25.5%（208 件中 53 件） |
| unit 単位の誤検出（Pilot は問題なし、自作はエラー） | 29 件 |
| 行 + 種類の再現率 / 適合率 | 11.0% / 15.4% |
| **正しいモデル（検証済み 5 件）を誤りとした数** | **4 / 5** |
| **入れた誤りの検出率（変異体の差分）** | **52 / 112 = 46%**（同じ行で 51） |

変異の種類別（Pilot がエラーを出した変異体のうち、自作が新しいエラーを出した数）:

| 変異 | 検出 | | 変異 | 検出 |
| --- | --- | --- | --- | --- |
| 予約語を名前に | 20/20 | | 可視性の無い import | 12/20 |
| `perform` の `action` 抜け | 8/8 | | 存在しない型名 | 4/20 |
| `and` → `&&` | 3/3 | | `::` でフィーチャをたどる | 1/13 |
| 制約の `==` → `=` | 2/2 | | 型付きライブラリの import 漏れ | 1/10 |
| item を attribute に | 1/2 | | SI に無い単位 | 0/12 |
| def 側の `default` → `=` | 0/2 | | | |

Pilot のエラーの種類別の再現率（同じ行・同じ種類）: 構文 50%、束縛の上書き 40%、flow の端 29%、未解決参照 6.5%、アクセス範囲 5.9%、型の種類 1.3%、`Must reference ...` 0%。

## 分かったこと

1. **構文は強いが、名前解決と型が弱い**。予約語・`&&`・`action` 抜けのような構文レベルの誤りはほぼ全部拾う。一方、Pilot の診断の大半を占める「未解決参照」（384 件）と「型の種類」（228 件）はほとんど一致しない。ここが Pilot との差の本体で、KerML の名前解決（import・継承メンバー・可視性）と、ライブラリ（ISQ / SI / ScalarValues）の意味論が無いことに対応する。
2. **正しいモデルを読めない文法の穴がある**（4/5 で誤検出）。`attribute x : Real default := 100.0;`、state の中の略記 `accept … then`、要素短縮名の import（`private import Pkg::'SN-R001';`）、interface def の end 名を使った flow。**パースに失敗するとそのファイルの lint が全部止まる**ので、文法の穴は見逃しを連鎖的に増やす。
3. **ライブラリの中身を知らない**: SI に無い単位（`[kN]` `[kWh]` 等）0/12、`ScalarValues` などの import 漏れ 1/10、存在しない型名 4/20。名前がライブラリに実在するかを調べていない。
4. **`::` と `.` の区別**（Must be an accessible feature）は 1/13。名前解決の結果（フィーチャか名前空間か）が無いと判定できない。
5. 可視性の無い import は自作の文法が受け付けてしまう（自作文法は `visibility?`、公式 Xtext は必須）。12/20 の検出は連鎖による偶然を含む。

## 到達に向けての含意（P4 で詳細化）

- 最初に効くのは「文法の穴をふさぐ」こと（正しいモデルで 0 エラーにする。誤検出が消え、lint が止まらなくなる）と、「ライブラリの名前表を使った名前解決」（未解決参照・単位・import 漏れ）。
- 型の種類・アクセス範囲・`Must reference` は、KerML の派生プロパティ（継承メンバー、フィーチャの種類）を持つ名前解決層が前提になる。Pilot 側の規模は、名前解決 1.1 千行、アダプタ 9.8 千行、派生プロパティ 17.8 千行、検証ルール `@Check` 115 個（約 3 千行）。
- 次の P3 で Pilot 自身の xpect テスト（`XPECT errors` 489 件）を加え、構文以外の検証ルールの網羅度を測る。

## P3: Pilot 自身の xpect テストで測った検証ルールの網羅度（2026-10-15）

Pilot ソース（`C:\pilot_tmp`、2026-08-13）の `org.omg.sysml.xpect.tests` の SysML テスト 126 件（期待エラー 164 件・期待警告 40 件）をコーパスに加えた（計 414 件）。設定部分だけを空行に置き換え、XPECT の注釈は SysML のコメントなので残した。

- **オラクルの確認**: 期待エラー 164 件のうち、Pilot 0.62.0 が同じメッセージを出したのは 161 件、同じ行まで一致は 132 件（行のずれは、`at "..."` が複数行にまたがるテストで行を特定しきれないため）。テストの版と jar の版の差による食い違いはほぼ無い。
- **自作の網羅度**: 期待エラーのうち、自作が同じ行・同じ種類で出したのは **51 / 164（31%）**、同じ行に何らかのエラーを出したのは 68（41%）。
- 期待メッセージ 66 種類のうち、自作が 1 件も一致しないのは **46 種類（期待エラー 87 件）**。
  - 全件一致: subject の個数・位置、objective の外の verify、state の entry/do/exit の個数、variant / variation の所有、return の個数、view rendering の個数、parallel state の遷移。**構造の数え上げで判定できる規則は実装済み**。
  - 一致しない主なもの: 「X must be typed by Y definitions」系（occurrence / usage / calculation / state / use case / analysis / constraint / connection / flow / enumeration / requirement / case など、計 50 件超）、`Must be model-level evaluable`、`Must have a concrete type`、再定義の制約（nonunique、方向、所有型、パッケージ直下）、`Must reference a …`。**どれも「参照先が何の種類か」を知る名前解決が前提**。
- xpect だけで見た unit 単位: 見逃し率 27.9%、行 + 種類の再現率 32.4%・適合率 74.2%（自作が出したエラーはおおむね正しいが、出せていないものが多い）。

種類の対応づけ（`compare.py` の `PILOT_CATEGORIES` / `LOCAL_CATEGORIES`）は、P3 で「個数の制約（cardinality）」「置き場所（placement）」を足して細かくした。そのため全体の数値は P2 の初回と少し違う（全体: 見逃し率 25.9%、行 + 種類の再現率 15.2%・適合率 23.1%、414 件）。

## 段階 A: 文法の穴とパース停止（2026-10-15）

変更（`ROADMAP.md` の段階 A）:

- 文法（`SysMLMin.g4`）: 値の `:=`（初期値）と `default :=`、`perform` の `::>` / `references`、state の本体の `port` / `item`。
- パースエラーがあっても、読めた部分を lint する（`lint_text_with_locations(..., recover=True)`。`run_local.py` は既定で有効）。
- 正しいモデルでの誤検出 2 件: 短い名前（`<'SN-R001'>`）の import・修飾名を解決する。型なしの `interface ... connect` の中の flow は、end 名（source / target）がライブラリ由来なので確かめない。

| 指標 | P3（段階 A 前） | 段階 A 後 |
| --- | --- | --- |
| 正しいモデルの誤検出（verified 5 件） | 4 | **0** |
| xpect の valid（34 件） | both_clean 33 / both_error 1 | 同じ（both_error は Pilot も同じエラーを出すテスト） |
| 構文: unit ごとの最初の構文エラーを同じ行で | — | **63 / 70（90%）** |
| 構文: Pilot の構文エラー全件（後続エラー込み） | 62 / 115 | 71 / 115 |
| 層 1（文法）の再現率（`analyze_gaps.py`） | 63% | 72.9% |
| 変異体の検出（元の unit との差分） | 52 / 112 | **71 / 112** |
| unit 単位: false_alarm / missed | 29 / 65 | **0** / 97 |
| 行 + 種類: 再現率 / 適合率 | 15.2% / 23.1% | 16.4% / **67.1%** |

**見逃し（missed）が 65 から 97 に増えたのは、測り方の上での見かけの悪化**。増えた 32 件はどれも、P3 では Pilot のエラーと関係の無い場所に自作がエラーを出していたため「両方エラー」と数えられていた unit だった。

- 16 件: 文法の穴による構文エラー（例: Pilot は 35 行目の未解決参照、自作は 448 行目の `:=` で構文エラー）。
- 16 件: 元のモデルの誤検出（structure の 54・59 行目、connections の 162 行目）を、変異体が引き継いでいたもの。

穴が埋まったので、本当の検出漏れ（主に層 2 の名前解決）が見えるようになった。変異体の差分評価は元のモデルの雑音を差し引くので、52 から 71 への改善を正しく示している。

構文の残り 7 件は、自作の文法が Pilot より緩いもの（`require` を requirement の外に書く、略記 `accept ... then` の置き場所、`interaction def`、`about` のドット経路、`decide` の分岐先でのその場の宣言など）。Pilot は閉じ括弧などに後続エラーを出すため、構文は「unit ごとの最初の 1 件」で測る（`compare.py` の `syntax_first_error`）。

## 段階 B: スコープつき名前解決（2026-10-15〜16、終了）

### コーパスの追加

Pilot ソースの KerML の名前解決のテスト（`imports` / `scoping` / `visibility` / `linking`、105 件）を SysML に書き換えて加えた（計 519 件、`build_corpus.py` の `kerml_to_sysml`）。`classifier` / `class` / `type` → `part def`、`datatype` → `attribute def`、`metaclass` → `metadata def`、`feature` とキーワードの無い feature → `part`。テストが読み込む `/src/*.kerml` も書き換えて後ろに連結した。ラベルは書き換えたテキストに Pilot が付けるので、書き換えが元のテストの意図とずれても比較は正しい。書き換え後に Pilot が構文エラーを出すものは無い。

段階 B の開始時点の結果は `results/sB_start`（指摘の種類の対応づけで、自作の汎用ルールの「存在しない型」をメッセージから未解決参照と見なすようにしたので、段階 A の数値とは少し違う）。

### 作ったもの

- `sysml_v2_checker_advanced/scope_resolver.py`: AST から名前空間の木を作り、KerML の規則で名前を解決する。結果は「見つかった / 無い / 不明」の 3 値で、**不明はエラーにしない**。
  - 内側から見える名前: 所有メンバー、import したメンバー、継承したメンバー（private 以外）、外側の名前空間へ。修飾名の 2 番目以降は public なメンバーだけ。
  - import: private / public、`::*`、`::**`（名前空間そのものも）、要素 import（短い名前も持ち込む）、`all`、`expose`、filter（`@X` とその and / or / not）。可視性の無い import は参照実装では構文エラーなので効かせない。import の対象は、同じ名前空間でそれより前の import までを使って解決する（Xtext と同じ。循環も起きない）。
  - 種類: 定義の特化は定義だけ、型付けはパッケージ以外、再定義・部分集合は usage だけを候補にする（参照実装の `Couldn't resolve reference to Classifier` など）。usage で型付けしたものは `A usage must be typed by definitions` として別に出す。
  - 式の中の名前（単位、`noSuch == true`、`a.b.c` の連鎖）。ラムダの引数・トリガーのペイロードは除く。列挙の値は型付けでは継承されない。
  - 標準ライブラリ: パッケージ直下は索引（`library_index.json`）で引く。型の中身は持たないので、ライブラリの定義の本体で宣言されている名前（`scripts/build_library_feature_names.py` → `library_feature_names.json`）にあるときだけ「不明」にする。部品・動作などが暗黙に特化する型（Kernel Semantic Library と Systems Library の定義の直接のメンバー）の名前も同じ。
- `linter.py` の `_check_scoped_references`: 平らな名前表による「存在しない型・パッケージ・要素・計算・PortDefinition」の指摘をこれで置き換え、参照実装と同じ文言（`Couldn't resolve reference to <種類> '<名前>'.`）で出す。接続の端点・遷移の状態など、名前解決がまだ見ない参照の既存の指摘は残し、同じ要素に重ねては出さない。

2026-10-16 に加えたもの:

- 参照の形: `verify X;` / `verify x : T;`（`requirement` 無し）と `exhibit s;`（`state` 無し）は参照（文法と AST に区別を残した）。satisfy などの参照先の名前は、その usage の名前として引けない。定義に付く前置メタデータ（`#logical part def`）も AST に残す。引用符の外れた `'1.1'` の `.` を連鎖と取り違えない。
- 接続の端・satisfy の `by` の連鎖（`a.b.c`）の 2 番目以降も確かめる。
- ライブラリ: 名前の集合に再定義（`:>> width`）と続くキーワード（`in ref alternative`）の名前も入れた。ライブラリの型から継承した feature の中では、その集合で「無い」と言えるものはエラーにする（`item b : Box { :>> length = 80 [cm]; }` の cm）。
- アクセス範囲（`scope_resolver.inaccessible_features`、`linter._check_accessible_features_scoped`）。参照実装で確かめた規則:
  - 接続の端（connect / bind / flow / allocate / interface / succession / then、satisfy の by）で `::` を使って feature をたどる（左が usage でも定義でも）。両端が同じ定義の feature なら通る。
  - 部分集合の先で、`::` の左が usage（`part x :> v::engine;`）。再定義と、左が定義のものは通る。
  - 接続の端の単純名が、接続を持つ型ではなく外側の型の feature。message の端と値の式は、入れ子の usage の中なら通り、入れ子の定義の中では不可。
  - 端の `.` と `::` の区別は AST では `::` に正規化されていたので、元の書き方を付帯情報（`antlr_transformer.AnnotatedNode`、`==` は普通の dict と同じ）として残した。

### 結果

未解決参照（行 + 種類）は、Pilot に構文エラーがある unit を分けて数える（`compare.py` の `unresolved_references`）。構文エラーがあると Pilot は回復で要素を失い、その先の参照まで未解決にするため（可視性の無い import、予約語の名前など）。

| 指標 | 段階 B 開始時 | 10-15 | 10-16（終了） |
| --- | --- | --- | --- |
| **未解決参照の再現率 / 適合率**（Pilot に構文エラーの無い unit） | — | 87.4% / 98.8% | **90.3% / 98.1%**（408 / 8 / 44） |
| **アクセス範囲の再現率 / 適合率** | 26% / — | 26% / — | **95.3% / 100%**（41 / 0 / 2） |
| 未解決参照の再現率（全体） | 17.4% | 70.6% | 73.2% |
| 層 2（名前解決）の再現率（`analyze_gaps.py`） | 7.8% | 66.8% | 74.8% |
| 正しいモデルの誤検出（verified 5 件） | 0 | 0 | 0 |
| unit 単位: false_alarm / missed（519 件） | 18 / 117 | 1 / 46 | **1 / 26** |
| 見逃し率 | 39.0% | 15.3% | **8.7%** |
| 行 + 種類: 再現率 / 適合率 | 19.1% / 67.0% | 47.9% / 83.6% | 51.4% / 84.7% |
| 変異体の検出（元の unit との差分） | 71 / 112 | 99 / 112 | **110 / 112** |
| xpect の期待エラー（同じ行・同じ種類） | 51 / 164 | 78 / 164 | 78 / 164 |
| 構文: unit ごとの最初の構文エラー | 90% | 90% | 90% |

残る false_alarm 1 件は KerML の `doc <B>`（文書の短い名前）を自作の文法が受け付けないもので、名前解決とは別。

テスト: 既存のテストはすべて通る。参照実装との一致のテスト（`test_sysml_reference_conformance.py`）は、xfail だった p04（usage の `::>` の先）と s2e（兄弟のパッケージの import）が一致するようになった。s2k（`[SI::m/s]` の `s`）は、ライブラリの型の中身を持たないため「不明」になり、xfail にした。名前解決とアクセス範囲の規則は `tests/test_scope_resolver.py`（35 件）で固定した。

### 終了判定と残した課題

終了条件（未解決参照・アクセス範囲の再現率と適合率 ≥ 90%、正しいモデルの誤検出 0、既存テストを壊さない）を満たした。次の課題は残した。

- 未解決参照の見逃し 44 件（構文エラーの無い unit）: メタデータの値で絞る filter（`[(as Safety).isMandatory]`、26 件。値の評価が要る）、ライブラリの型のメンバー表（s2k、`ISQ::TemperatureValue` のような alias の先の種類）、関数呼び出しの名前、`assign` の先。
- 構文エラーのある unit（再現率 28%）は、Pilot のエラー回復の仕方まで真似ないと一致しない。到達判定からは外し、分けて報告する。
- `rule_confidence.json` の `_check_import` / `_check_part_instance` の実測値は、未解決参照の指摘を `_check_scoped_references` に移したので古い（`scripts/recheck_local_only.py --rule-stats` で測り直す）。

## 段階 C: 解決結果を使う種類の判定（2026-10-16、終了）

### 作ったもの

- `scope_resolver.kind_violations`（リンターの `_check_usage_kinds_scoped`）: 参照実装の `SysMLValidator.checkAllTypes` / `checkOneType` を、名前解決の結果の上で写した。平らな表による `_check_usage_type_kinds` と、段階 B で入れた汎用の「usage で型付け」の判定はこれで置き換えた。
  - usage の「すべての型」は、明示の型付けと、部分集合・再定義の先から継承した型（参照する usage〈satisfy / perform / exhibit / include / `event x`〉は参照先の型）。型付きの接続は、型の定義の端の型も持つ。
  - 定義の種類は KerML のメタクラスの集合で持つ（Behavior は Class、Function は Behavior、Predicate は Function。action def は Behavior、calc def は Function、constraint def・requirement def は Predicate）。action と state の usage の型は Behavior でよい（`state s : D;` で D が action def でも通る。k24）。ライブラリは索引の宣言の種類（`attribute def`、KerML の `datatype` / `behavior` / `function` / `predicate` / `assoc` / `metaclass` など）から引き、分からないもの（`alias` など）は判定しない。
  - 型がちょうど 1 つでなければならない usage（requirement・calc・case など）、individual（individual def がちょうど 1 つ）、前置メタデータ（metadata def でない・抽象なら `Must have a concrete type`）、参照先の種類（`Must reference an action / a state / a requirement`）。
  - 接続・束縛・flow の端の feature の型が解決できない場合（参照実装は端の行にも `A usage must be typed by definitions.` を出す）。
- **連鎖の扱い**: 型や参照先が解決できないと、参照実装は同じ行に種類のエラーも重ねて出す（解決できない型は代理〈proxy〉として残り、どのメタクラスにも当たらないため）。自作は原因の未解決参照だけを出す（既存のテストも「1 回だけ報告する」ことを固めている）。`compare.py` は、Pilot が同じ行に未解決参照と種類のエラーを出し、自作がその行に未解決参照を出していれば、種類のエラーも当たったと数える（`cascade_credit`、180 件）。行の違う連鎖（再定義の先・接続の端）は自作も出す。
- `compare.py`: 種類ごとの再現率・適合率を、Pilot に構文エラーの無い unit とある unit に分けて出す（`stage_categories`）。自作のメッセージが参照実装と同じ文言（`must be typed by` / `Must reference` / `Must be an accessible feature`）なら、出したルールにかかわらずその種類として数える。

### 結果

| 指標（Pilot に構文エラーの無い unit） | 段階 C 開始時 | 段階 C 終了 |
| --- | --- | --- |
| **種類の判定（typing_kind）の再現率 / 適合率** | —（全体で 15.8%、60 / 380） | **95.1% / 99.2%**（250 / 2 / 13） |
| **参照先の種類（must_reference）の再現率 / 適合率** | —（全体で 0%） | **93.3% / 100%**（28 / 0 / 2） |
| 未解決参照の再現率 / 適合率 | 90.3% / 98.1% | 90.3% / 98.1% |
| アクセス範囲の再現率 / 適合率 | 95.3% / 100% | 95.3% / 100% |

| 指標（519 件全体） | 段階 C 開始時 | 段階 C 終了 |
| --- | --- | --- |
| 正しいモデルの誤検出（verified 5 件） | 0 | 0 |
| unit 単位: false_alarm / missed | 1 / 26 | **1 / 19** |
| 見逃し率 | 8.7% | **6.3%** |
| 行 + 種類: 再現率 / 適合率 | 51.4% / 84.7% | **70.5% / 87.0%** |
| 変異体の検出 | 110 / 112 | 110 / 112 |
| xpect の期待エラー（同じ行・同じ種類） | 78 / 164 | **110 / 164** |

Pilot に構文エラーがある unit での種類の判定の再現率は 28%（Pilot はエラー回復で要素を失い、その先の型をすべて種類のエラーにする）。段階 B と同じく到達判定からは外し、分けて報告する。

テスト: 既存のテストはすべて通る。種類の判定の規則は `tests/test_scope_resolver.py`（45 件）で固定した。

### 残した課題

- 種類の判定の見逃し 13 件: 参照先の暗黙の型（`perform pp;` の pp が型なしの part なら Parts::Part を持つので action でない）、意味的メタデータの基底型の制約（`#g3 attribute a3;`）、action の本体の引数が型の引数を名前で暗黙に再定義する形、`return` が結果の引数を暗黙に再定義して継承を隠す形。
- 誤検出 2 件は、暗黙の再定義で継承が隠れる形（`calc c2 : C { return r1 : T; }` の T が C の結果の引数でなく attribute def T に解決する）。

## 段階 D: 個別の検証ルール（2026-10-16、終了）

### 終了条件の読み替え

ROADMAP の「xpect の期待エラー ≥ 95%」は、期待エラー 164 件のうち参照実装（Pilot 0.62.0）自身が同じ箇所に出すのが 132 件しかない（テストの版と jar の版の差、`at "..."` が複数行にまたがるもの）ため、そのままでは参照実装も満たせない。**参照実装が同じ箇所に出した期待エラーのうち 95%** と読み替えた。

### 作ったもの

- 文法: `perform x : T;`（参照に型を書く形。LLM の書き方で、参照実装は受け付ける）、`private package`、`doc <B>`。自作だけが構文エラーにしていた 13 件が消えた。
- 名前解決: filter のメタデータの値（`[(as Safety).isMandatory]`、`== false`。参照実装の Import_Filtered のラベルで確かめた意味だけ）。パッケージの可視性。
- `validation_rules.py`（リンターの `_check_pilot_validations`）: objective は 1 つまで（型・特化の先の objective も数える）、enum の attribute は型を 1 つ、flow def の端は 2 つまで（継承した端も数える）、individual def は 1 つまで、interface の端は port、port def と port の中の port 以外の usage は ref、filter の条件とメタデータの値はモデルの水準で評価できる式（関数呼び出し・`~`・`->` は不可、`new` はよい）、filter の結果は Boolean。
- `compare.py`: 連鎖として数える組を広げた（端の参照の誤り〈アクセス範囲・未解決〉に重なる「Must have at least two related elements」「Cannot identify flow end」）。自作の指摘が参照実装と同じ英文で始まれば、参照実装の種類の対応表で分類する。対応表に `expression_result`・`end_kind` を足した。

### 結果

| 指標 | 段階 D 開始時 | 段階 D 終了 |
| --- | --- | --- |
| **xpect: 参照実装が同じ箇所に出した期待エラーのうち、自作も同じ行・同じ種類** | 110 / 132（83.3%） | **126 / 132（95.5%）** |
| **行 + 種類の再現率 / 適合率（Pilot に構文エラーの無い unit）** | 85.7% / 95.9% | **92.0% / 97.2%** |
| 未解決参照（同） | 90.3% / 98.1% | 96.2% / 97.8% |
| アクセス範囲（同） | 95.3% / 100% | 95.3% / 100% |
| 種類の判定（同） | 95.1% / 99.2% | 96.2% / 99.2% |
| 参照先の種類（同） | 93.3% / 100% | 93.3% / 100% |
| unit 単位: false_alarm / missed（519 件） | 1 / 19 | **0 / 17** |
| 見逃し率（519 件） | 6.3% | 5.7% |
| 行 + 種類の再現率 / 適合率（519 件） | 70.5% / 87.0% | 74.8% / 88.4% |
| 変異体の検出 | 110 / 112 | 110 / 112 |
| 連鎖として数えた件数（cascade_credit） | 180 | 193 |

テスト: 既存のテストはすべて通る。段階 D の規則は `tests/test_validation_rules.py` で固定した。

### 残した課題

- xpect の残り 6 件: message の型（`message :A from b to c;` の `:A` と `of A` が AST で区別できない）、`Cannot annotate ItemUsage`（メタデータ定義の annotatedElement の制約）、`event a.areal;` の参照先の種類、accept を持つ遷移の始点、閉じ括弧の構文エラー。
- 見逃し率の目標（≤ 2%）には届いていない（5.7%、17 件）。12 件は Pilot に構文エラーの無い unit で、未実装の個別ルール（束縛した値の上書き 4、constant の再定義、方向の食い違う再定義、subject の位置、invoke の引数、メタデータの annotatedElement の制約など）。5 件は Pilot に構文エラーがある unit（Pilot のエラー回復の仕方まで真似ないと一致しない）。

## held-out の誤検出の修正（2026-10-16）

研究のまとめ（`RESULTS.md`）で、開発に使っていない公開モデル（`build_heldout.py`、131 件）を測ったところ、Pilot がエラーを出さない 96 件のうち 27 件で誤検出した（研究前は 17 件）。原因ごとに直した（内容は `RESULTS.md` の 4 章）。**この修正は held-out を見ながら行ったので、修正後の held-out の数値は汎化の証拠にならない。**

| 指標 | 修正前 | 修正後 |
| --- | --- | --- |
| held-out: Pilot がエラーを出さない 96 件での誤検出 | 27 | **2**（文法の穴。名前解決によるものは 0） |
| held-out: 行 + 種類の再現率 / 適合率（構文エラーの無い 127 件） | 81.4% / 84.9% | 80.6% / 94.6% |
| 開発: 行 + 種類の再現率 / 適合率（構文エラーの無い unit） | 92.0% / 97.2% | 91.7% / 97.2% |
| 開発: 未解決参照の再現率 / 適合率（同） | 96.2% / 97.8% | 95.6% / 97.7% |
| 開発: 正しいモデルの誤検出・変異体・xpect | 0 / 110 / 126 | 0 / 110 / 126 |

テスト: 既存のテストはすべて通る。修正した形は `tests/test_scope_resolver.py` の `test_held_out_forms` で固定した。参照名に引用符を残すようにしたので（`Spec::'R-010'`）、2 件のテストの期待値を直した。

## 複数ファイル対応（2026-10-22）

自作のリンターをフィードバックにして 4 ファイルの AGV モデルを生成したところ（`C:\test\sysml_models\eval\linter_gen\RESULT.md`）、MCP の `lint_sysml_file` は 1 ファイルずつ検証するので、ファイルをまたぐ正しい参照がすべて未解決のエラーになった（初稿で 50 件中 46 件が誤検出）。ほかのファイルの名前を `known_external_types` で渡しても、ほかのファイルのパッケージを import したファイルでは解決できない名前がすべて「不明」になり、同じファイルの中の誤記まで見逃した（誤りを 1 つずつ入れた 12 版で 4 件しか見つからない。Pilot は 12 件）。

### 作ったもの

- `ScopeResolver(ast, external_names, other_asts)`: ほかのファイルの AST を、ファイルごとのルートに組み立て、各ファイルの最上位の要素をグローバルな名前空間に置く（Pilot で確認: 最上位の private な要素もほかのファイルから見える。ファイルの最上位の import はそのファイルの中だけに効く）。判定するのは対象のファイルの参照だけ。
- `model_files.py`: 一緒に検証するファイルを集める。決まりは sysml-mcp-server の `validate_sysml` と同じ（file_path だけなら同じフォルダ、directory ならサブフォルダも含む、`""` なら 1 ファイル）。構文エラーのファイルは読まず、`unparsable_files` として返す。
- `SysMLAdvancedLinter.lint(..., other_asts)`・`lint_text_with_locations(..., other_asts)`。平らな名前表のルールには、ほかのファイルで宣言された名前を `known_external_types` と同じ扱いで渡す。
- MCP: `lint_sysml_file(file_path, directory=None)` は既定でフォルダを読む。`lint_sysml_text(sysml_text, file_path=None, directory=None)`（file_path はこのテキストで置き換えるファイル）。結果に `scope`・`loaded`・`unparsable_files`・`note` を付けた。

AGV の probe を調べる中で見つかった、1 ファイルでも起きる名前解決の不足も直した（どれも Pilot で確かめた形）。

- 遷移の `accept T`（型の節の無い形）の型を名前解決で確かめる。指摘は accept の行に出す（古い平らな規則は import があると黙り、遷移の先頭の行に出していた。ヒントは引き継いだ）。
- 端の名前の付いた接続の端（`interface i : I connect x ::> a.nosuch to ...`）: 元の書き方が `x::>a.nosuch` のまま連鎖として読まれ、確かめていなかった。端の名前を外して確かめ、指摘は端の行に出す（ANTLR の行を端の付帯情報に残した）。
- 接続の端の先頭の名前が無いもの（`connect a.p to nob.p;`・`connect a to nob2;`・`bind`・interface）を出す。以前は flow だけ。
- 端の名前（`x ::> wheel.lugNut`、n 項の `connect (x ::> a.p, ...)` も）を接続のメンバーにする（型の同名の端を再定義し、`::>` の先を部分集合にする）。中の `connect y ::> x.q` の x.q を解決する（held-out の Vehicle_Example・Arrowhead_Framework_Example で、上の修正の直後に出た誤検出）。
- 端の名前の付いた端の型の種類（Pilot は端の行に `A port must be typed by port definitions.`）は、端の種類と行が合わせられないので、以前どおり出さない。

### 結果

| 指標 | 修正前 | 修正後 |
| --- | --- | --- |
| AGV の probe（誤りを 1 つずつ入れた 12 版、MCP の `lint_sysml_file`） | 4 / 12（名前を渡したとき）。名前を渡さないと誤検出 10〜25 件に埋もれる | **12 / 12**（Pilot と同じ指摘。正しいモデルはエラー 0） |
| AGV の初稿（MCP の `lint_sysml_file`） | エラー 50（うち 46 は誤検出） | **エラー 4**（Pilot と同じ 4 件） |
| 開発: 行 + 種類の再現率 / 適合率（構文エラーの無い 449 件） | 91.7% / 97.2% | 91.8% / 97.3% |
| 開発: 未解決参照の再現率 / 適合率（同） | 95.6% / 97.7% | 95.8% / 98.0% |
| 開発: 正しいモデルの誤検出・変異体・xpect | 0 / 110 / 126 | 0 / 110 / 126 |
| held-out: 行 + 種類の再現率 / 適合率（構文エラーの無い 127 件） | 80.6% / 94.6% | 81.7% / 94.7% |
| held-out: 未解決参照・型の種類の再現率 | 78.0% / 85.6% | 79.0% / 87.2% |
| held-out: Pilot がエラーを出さない 96 件での誤検出 | 2 | 2 |

開発と held-out のコーパスは 1 unit = 1 テキストなので、複数ファイルの名前解決そのものは測っていない（AGV の probe だけ）。held-out の誤検出 2 件は以前からの文法の穴。端の修正の直後に held-out で出た新しい誤検出（Vehicle_Example・Arrowhead_Framework_Example）は held-out を見ながら直したので、held-out の数値はここでも汎化の証拠にならない。開発の Pilot に構文エラーのある unit（llm-sonnet-A2）で、端の先頭の未解決が 3 件増えた（import の可視性の無い構文エラーでパッケージが見えないための連鎖。到達判定の外）。

テスト: `tests/test_multi_file.py`（16 件）。既存のテストはすべて通る。

### 残した課題

- ~~複数ファイルのモデルのコーパス（フォルダ単位の unit）を作り、Pilot の `validate_sysml`（directory）と比べる。~~ → 次の章。
- 構文エラーのあるほかのファイルは読まない。Pilot はエラー回復で読めた部分の要素を見せる（AGV の probe m02 で、壊れたファイルの前半の定義は解決した）。
- 名前を渡すたびにほかのファイルをパースし直す（AGV の 4 ファイルで 1 ファイル 0.3〜0.7 秒）。

## フォルダ単位のコーパス（2026-10-22）

複数ファイル対応を、1 つの AGV モデルより広く確かめる。フォルダをそのまま残し、ファイルごとに 1 unit にした
（`build_folders.py`。id は `<フォルダ>__<ファイル>` なので `compare.py` をそのまま使う）。

- **正解**: Pilot がフォルダのファイルを一緒に読んだときの、そのファイルの指摘（`label_pilot_folders.py`、
  sysml-mcp-server の `validate_files`。MCP の `validate_sysml` に directory を渡したときと同じ）。
- **自作**: 同じフォルダのほかのファイルを一緒に読む（`run_local_folders.py`。MCP の `lint_sysml_file` の既定と同じ）。
  `--single` は 1 ファイルずつ（複数ファイル対応の前の MCP と同じ）。
- **フォルダ**（2 ファイル以上。サブフォルダは含めない）: folder-dev = 開発で見たモデル（eval/runs・eval/runs_sonnet の
  LLM の AGV 15 個、linter_gen の AGV 2 個、verified のテーマ 10 個。eval/blind* は runs の名前を伏せた写しなので
  入れない）。folder-heldout = held-out と同じ公開リポジトリの 86 個（348 ファイル）。
- **xfile-mutant**: Pilot がエラーを出さない 79 フォルダの 1 ファイルに、ほかのファイルで宣言された名前の誤記を
  1 つ入れたもの（118 版）。型の名前（`part x : Vehicle` → `Vehicl`）、feature の連鎖の 2 番目以降
  （`v.maxSpeed` → `v.maxSped`）、import するパッケージ（`private import Defs::*` → `Dfs`）。
  最後から 2 文字目を落とし、フォルダのどこにも無い名前になるものだけ。

### 結果（Pilot に構文エラーの無いファイル、行 + 種類の再現率 / 適合率）

| source | ファイル | 1 ファイルずつ（以前の MCP） | **フォルダを読む（今の MCP）** | 正しいファイルの誤検出: 以前 → 今 |
| --- | --- | --- | --- | --- |
| folder-dev | 121 | 97.5% / 6.6% | **98.8% / 100%** | 54 / 104 → **0 / 104** |
| folder-heldout | 339 | 81.6% / 74.9% | **81.4% / 95.2%** | 44 / 269 → **3 / 269** |
| xfile-mutant | 118 | 83.3% / 25.2% | **82.6% / 97.3%** | — |

ファイルをまたぐ誤り（Pilot が誤りを入れた行にエラーを出した 117 版のうち、自作も同じ行に同じ種類のエラー）:

| operator | 版 | 1 ファイルずつ | **フォルダを読む** |
| --- | --- | --- | --- |
| 型の名前 | 37 | 32 | 30 |
| feature の連鎖 | 41 | 35 | 35 |
| import | 39 | 39 | 39 |
| 合計 | 117 | 106 | **104（88.9%）** |

- **1 ファイルずつの数は見かけだけ**: ほかのファイルの名前はすべて未解決になるので、入れた誤りも出るが、同じ形の
  誤検出に埋もれる（適合率 6.6〜75%、Pilot がエラーを出さないファイルの 26%（98 / 373）で誤検出）。フォルダを読むと、誤検出がほぼ消えて
  （正しいファイルの誤検出 98 → 3）、入れた誤りの 89% を Pilot と同じ行・同じ種類で出す。
- **見逃した 13 版**は、ファイルをまたぐことと関係なく、自作の名前解決がその位置の参照を確かめていないもの:
  flow の `of T` の型（2）、式の中の呼び出し・`new T(...)` の名前（4）、action の中の `accept T via p`（1）、
  flow の端の 3 段以上の連鎖・n 項の接続の端からの連鎖（4）、制約式の中の連鎖（1）、部分集合の先の連鎖（1）。
  1 ファイルずつで「出た」のは、ほかのファイルの名前がすべて未解決になるため（偶然の一致）。
- **held-out の誤検出 3 件**は文法の穴（advent-of-sysml-v2 の `defined by`、sysmod の 2 ファイル）。以前からの held-out の 2 件と同じ原因。
- 測る途中で、flow の端が自分を含む interface の名前から始まる形（`interface pi ... { flow from pi.source.m to ...; }`）を
  古い平らな規則（`_check_one_flow_end`）が「外側の feature」と誤検出していた（ServerSequenceRealization-2・3）。
  Pilot はそれ自身に解決して通す。直した（`tests/test_multi_file.py`）。開発・held-out の数値は変わらない。
- **妥当性**: folder-heldout は held-out と同じリポジトリのモデルで、その誤検出の修正（2026-10-16）にも、今回の
  flow の規則の修正にも使ったので、汎化の証拠としては弱い。xfile-mutant は機械的な 1 文字の誤記だけで、
  LLM が書く誤りの分布とは違う。

### 残した課題

- ~~見逃した 13 版の参照の位置を名前解決で確かめる。~~ → 次の章。
- ~~構文エラーのあるほかのファイルを、エラー回復で読めた部分だけ使う（Pilot と同じ）。~~ → 次の章。

## 見逃した位置と、構文エラーのあるファイル（2026-10-22〜23）

前章で見逃した 13 版の位置を確かめるようにし、構文エラーのあるファイルも回復で読めた部分を使うようにした。
どれも小さな例で Pilot の指摘（行・名前・種類）を確かめてから入れた（`tests/test_multi_file.py`）。

### 確かめるようにした参照

- flow の `of T` の型（Type）。
- 式の中の呼び出し・`new T(...)` の名前（Element）。Pilot は import していないライブラリの関数（`sqrt(2.0)`・
  `max`・`size`）も未解決にする。式の木で呼び出しの形になる演算子（`(a) xor (b)` の xor など）は除く。
- action の中の `accept T via p` の型（Type）。
- 部分集合・再定義の先の連鎖（`ref part sub :> c.noo;`）。先頭が自分の名前なら自分自身に解決する
  （`ref p : Person :> p.asPresident;`）。
- ラムダの型のある引数からの連鎖（`{in ref w : A; w.wheel.rr > 0}`。型から確かめる）。
- flow・message の端の行: 端が flow の先頭と違う行にあるとき、端の行に出す（ANTLR の行を付帯情報に残した）。
- 前置のメタデータ（`#idd port p`）: これまで型を不明にしていた。metadata def の特化の連鎖をたどり、
  `:>> baseType = X meta T` があれば X を継承元にし、SemanticMetadata まで baseType が無ければ何も足さない
  （ほかのライブラリの metadata・解決できない名前は不明のまま）。
- state の本体の `accept cl : T via p do action { ... cl.x ... }` の cl（do の action が accept の子になるので、子から見えるようにした）。

### 構文エラーのあるファイル

- エラー回復の木を読むとき、形の崩れた部分木で例外になっても、その部分木だけを `{"type": "recovered_error"}` に
  して残りを読む（以前はファイル全体を読めなかったとみなした）。対象のファイルの lint（recover=True）と、
  一緒に読むほかのファイルの両方に効く。
- ほかのファイルは回復で読めた部分を使う（`model_files.parse_other_file`）。MCP の結果に `partial_files` を足した。
- 回復の仕方は Pilot（Xtext）と ANTLR で違い、どの要素が残るかは一致しない（AGV の probe m02 では、Pilot は
  エラーのあとの state def を落とすが、ANTLR は残す）。

### 結果

| 指標 | 前章 | この章 |
| --- | --- | --- |
| ファイルをまたぐ誤記（Pilot がその行に出した 117 版） | 104 | **117（100%）** |
| フォルダ（dev）: 行 + 種類の再現率 / 適合率・正しいファイルの誤検出 | 98.8% / 100%・0 / 104 | 98.8% / 100%・0 / 104 |
| フォルダ（held-out のリポジトリ） | 81.4% / 95.2%・3 / 269 | **83.9% / 94.7%**・3 / 269 |
| 開発: 行 + 種類（構文エラーの無い 449 件）・正しいモデルの誤検出 | 91.8% / 97.3%・0 | **92.0% / 97.3%**・0 |
| 開発: 未解決参照の再現率 / 適合率 | 95.8% / 98.0% | 96.2% / 98.0% |
| held-out: 行 + 種類（構文エラーの無い 127 件） | 81.7% / 94.7% | **85.5% / 92.7%** |
| held-out: 同（sysmod の 2 件を除く 125 件） | 86.3% / 97.5% | **87.8% / 97.6%** |
| held-out: 未解決参照・型の種類の再現率 | 79.0% / 87.2% | **84.3% / 88.8%** |
| held-out: Pilot がエラーを出さない 96 件での誤検出 | 2 | 2 |

- **held-out の適合率が下がったのは sysmod の 2 件**（自作の文法の穴があり、Pilot は構文エラーを出さない）。以前は
  回復の木が例外になり lint が止まっていたが、回復で読めるようになって、穴で落ちた要素の先の参照が未解決と
  出る。2 件を除くと適合率は変わらない（97.5% → 97.6%）。直すには文法の穴を埋める。
- 測る途中で、古いテスト 3 件の期待値が Pilot と違っていた（`flow of Q` の Q がパッケージ、特化の無い
  metadata def の `#g1` の中の再定義、定義の無い `new Signal()`）。Pilot に合わせて直した。
- 測る途中で、held-out のエラー回復の木で、名前の空のメタデータで名前解決が落ちていた（sysml-v2-lsp の invalid の
  fixture）。直した。
- 同じ held-out と、そのリポジトリのフォルダを見ながら直したので、held-out の数値は汎化の証拠としては弱い。

### 残した課題

- ~~`xs->forAll {...}` の `->` の呼び出しの名前~~ → 次の章。
- ~~値の式の連鎖の先の種類の語~~ → 次の章。
- ~~sysmod の文法の穴と advent-of-sysml-v2 の `defined by`~~ → 次の章。

## `->` の呼び出し、連鎖の種類の語、文法の穴（2026-10-23）

どれも小さな例で Pilot の判定（構文エラーの有無、指摘の行・名前・種類）を確かめてから入れた。

- **`->` の呼び出しの名前**（`xs->forAll {...}`・`xs->size()`）: 式の中の呼び出しと同じく名前解決する。Pilot は
  import していないライブラリの関数（`collect`・`sum`・`size`・`isEmpty`・`forAll`・`select`）を未解決にする。
- **連鎖の先の種類の語**: Pilot は式の中の連鎖の先が無いとき、`a.bx`（2 つ）は `Element`、3 つ以上
  （`a.b.nx`・`a.bx.c.m`）は `Feature` と書く（値の式でも制約の式でも同じ）。これに合わせた。
- **文法の穴**（フォルダ単位のコーパスで、Pilot は構文エラーを出さないのに自作が出した形）:
  並びの式の末尾のカンマ（`("a", "b", )`）、方向付きの引数の種類（`in concern`・`out requirement`・
  `out verification`・`out use case`・`occurrence`）、`occurrence def`・`use case def`・`concern def` の前置の
  メタデータと短い名前（`#project occurrence def <PRJ> ...`）、use case の修飾名の型と名前の後の多重度、
  occurrence の型の前の再定義と多重度（`ref occurrence project :>> this : Project;`）、interface の短い名前と
  多重度（`interface <asis> xs[1..*] : I connect ...`）、名前の無い interface の修飾名の型
  （`interface :Ifs::I connect ...`）、名前の無い frame と再定義（`frame concern :T;`・`frame p :>> A::b :> C::d;`）、
  part の `defined by`（`:` と同じ。仕様のキーワード）、succession の多重度（`first [0..1] a then [0..1] b;`）、
  名前の後の loop（`action x loop { ... } until c;`。`while` と同じ位置）。
- 穴を埋めて sysmod が読めるようになったところで、`::` の左が参照を囲む型自身（短い名前の `PRJ::company`）
  の形を古い規則（`_check_accessible_feature_paths`）が誤検出していた。囲む要素の短い名前も自己参照として
  除外した（Pilot で確認。外からの `PRJ::company` は Pilot も自作も `Must be an accessible feature`）。
- 古いテスト 2 件（`->collect`・`->forAll` を import 無しで使っていた）は、意図を変えずに import を足した
  （Pilot でエラー 0 を確認）。

### 結果

| 指標 | 前章 | この章 |
| --- | --- | --- |
| 開発: 行 + 種類（構文エラーの無い 449 件）・正しいモデルの誤検出・xpect・変異体 | 92.0% / 97.3%・0・126・110 | 92.0% / 97.3%・0・126・110 |
| held-out: 行 + 種類（構文エラーの無い 127 件） | 85.5% / 92.7% | **84.3% / 97.6%** |
| held-out: 同（sysmod の 2 件を除く 125 件） | 87.8% / 97.6% | 87.8% / 97.6% |
| held-out: Pilot がエラーを出さない 96 件での誤検出 | 2 | **0** |
| フォルダ（held-out のリポジトリ）: 行 + 種類・正しいファイルの誤検出 | 83.9% / 94.7%・3 / 269 | **81.7% / 98.4%・0 / 269** |
| フォルダ（dev）・ファイルをまたぐ誤記 | 98.8% / 100%・117 / 117 | 98.8% / 100%・117 / 117 |

- held-out の誤検出は文法の穴だけだったので、**0 件**になった（開発・held-out・フォルダのどれでも、Pilot が
  エラーを出さないモデル・ファイルでの誤検出が 0）。
- held-out の再現率が下がったのは sysmod の 2 件だけ（2 件を除くと変わらない）。読めなかったときは構文エラーの
  連鎖の未解決が、Pilot の同じ行の指摘と偶然に一致していた。
- held-out はこの修正にも使ったので、汎化の証拠としては弱い（前章と同じ）。

### 残した課題

- ~~`frame x;` の x は既にある concern への参照~~ → 直した（2026-10-23）。`concern` の無い `frame c;`・
  `frame c : T;`・`frame p :>> A::b;` は既にある concern を参照し（継承したものも見える）、`frame concern c;` は
  宣言（Pilot で確認。`tests/test_pilot_parity_stage_a.py`）。開発・held-out・フォルダの数値は変わらない
  （コーパスに存在しない concern を frame する例が無い）。
- 構文エラーのあるファイルの回復の仕方が Pilot（Xtext）と違う。AGV の probe m02 では、Pilot は action の中の
  セミコロン抜けのあとで `missing EOF at 'then'` を出してファイルを閉じ、残りの定義を捨てる。ANTLR は残りを
  読み続ける。どこで閉じるかは Xtext のエラー回復の細部によるので、合わせる確かな方法が無い。既知の違いとして残す。
- ~~新しい held-out での測定~~ → 次の章。

## 新しい held-out: LLM が書いたモデル（2026-10-23）

これまでの held-out は誤検出の修正に使ったので、汎化の証拠にならなくなった。そこで、研究に使っていない題材で、
新しくモデルを書かせ、**規則を変えずに**測った（測ったのはコミット `6a1d61c` のリンター）。

- **題材**（`C:\test\sysml_models\eval\heldout2\SPECS.md`。AGV の課題と同じ形式）: 家庭用コーヒーマシン、電動アシスト
  自転車、エレベーター、小型人工衛星の電源サブシステム、輸液ポンプ。
- **書き手**: 研究の文脈を持たないサブエージェント。開発に使った Opus ではなく Sonnet と Haiku が、題材ごとに 1 本ずつ
  （10 フォルダ・53 ファイル）。1 回で書いた初稿で、検証ツール・ほかのモデルは使わせていない。
- **比べ方**: フォルダ単位のコーパスと同じ（`build_folders.py --heldout2`、ほかのスクリプトは `--root heldout2`）。
  Pilot はフォルダごと、自作は MCP の `lint_sysml_file` の既定（同じフォルダを読む）。

### 結果

| 指標 | 1 ファイルずつ（以前の MCP） | **フォルダを読む（今の MCP）** |
| --- | --- | --- |
| 行 + 種類の再現率 / 適合率（Pilot に構文エラーの無い 12 ファイル） | 85.4% / 26.1% | **85.4% / 97.2%** |
| 同（全 53 ファイル。構文エラーのあるファイルを含む） | 88.1% / 84.4% | **87.7% / 95.6%** |
| Pilot がエラーを出さないファイル（8 件）での誤検出 | 6 | **1** |
| unit 単位の見逃し（Pilot はエラー、自作は 0） | 0 | 1 |

Pilot の種類ごとの再現率（全 53 ファイル、フォルダを読む）: 未解決参照 94.6%（544 / 575）、型の種類 90.0%（505 / 561）、
構文エラーの行 73.1%（122 / 167）、参照先の種類 61.5%（8 / 13）。

- **LLM の初稿の 77%（41 / 53 ファイル）に Pilot の構文エラーがある**。構文エラーの無いファイルは 12 件と少ない。
  全ファイルの見逃しの大半は、Pilot（Xtext）のエラー回復の連鎖（`A usage must be typed by definitions.` 52 件、
  `extraneous input ... expecting EOF` 34 件など）で、回復の仕方の違いによる（既知）。
- **誤検出 1 件**: `entry action initial;`（`action` キーワード付きの entry は新しい action の宣言）を、既存の action への
  参照（`entry initial;` と同じ）として扱い、後の `first initial then standby;` を未解決とした。AST が両者を区別していない。
- **見逃し 1 件**: `Redefining feature must have a compatible direction`（再定義の方向の食い違い。未実装の個別ルール、
  RESULTS.md の 5 章）。
- Pilot がエラーを出さないフォルダが無かったので、ファイルをまたぐ誤記の版は作れなかった。
- **比較**: 前の held-out の「段階 D 後（規則を作るときに held-out を見ていない）」は、構文エラーの無い入力で
  81.4% / 84.9%、正しいモデルの誤検出 27 / 96 だった。今回は 85.4% / 97.2%、誤検出 1 / 8。題材・書き手が違うので
  直接は比べられないが、誤検出の修正が新しいモデルにも効いていることを示す。
- **限界**: 規模が小さい（構文エラーの無いファイル 12 件、正しいファイル 8 件）。書き手は Opus 以外だが、同じ
  Claude の系統。題材の仕様は私が書いた。

### 残した課題

- `entry action x;`（宣言）と `entry x;`（参照）を AST で区別する（今回の誤検出）。直すと、この held-out の数値も
  汎化の証拠でなくなる。
- 再定義の方向の食い違い（`Redefining feature must have a compatible direction`）。

## 段階 E: Pilot の新しい版への追従（0.62.0 → 0.63.0、2026-10-23）

Pilot の 2026-09 リリース（0.63.0、10 月 22 日公開）の `jupyter-sysml-kernel-0.63.0.zip`（GitHub のリリースの添付、
sha256 をリリースの値と照合）を `C:\test\SysMLv2_pilot\pilot-0.63.0\` に置き、**4 つのコーパスの正解ラベルを
0.63.0 で作り直した**（`label_pilot*.py` を環境変数 `SYSML_JAR`・`SYSML_LIBRARY` で 0.63.0 に向け、`labels_063/`
に書く。MCP サーバの `vendor` の jar は 0.62.0 のまま）。`diff_pilot_versions.py` で版の差を数えた。

### 0.63.0 で変わったこと（リリースノートと、コーパスで実際に変わったもの）

- **リリースノート**: 明示的な部分集合（再定義でない `:>`）を持つ usage の多重度の既定値が `1..1` に（後方互換で
  ない変更）。connection def・flow def の端が usage であることの検証。多重度の導出の修正。ライブラリ・メッセージは
  「変更なし」。
- **コーパスで変わったもの**: 開発 519 件のうち 1 件、held-out 131 件のうち 1 件、フォルダ 596 件のうち 3 件、
  新しい held-out 53 件のうち 1 件だけ。
  - メッセージの文言: `A flow connection must be typed by flow connection definitions.` →
    `A flow usage must be typed by flow definitions.`、`A flow connection definition can have at most two ends.` →
    `A flow definition can have at most two ends.`（リリースノートには書かれていない）。
  - 新しい警告 `Bound features should have conforming types`（警告は比べていない）。
  - 多重度の既定値の変更による新しいエラーは、コーパスにも小さな例（部分集合の 6 形）にも現れなかった。
- **ライブラリ**: リリースノートは「変更なし」だが、`Systems Library/Flows.sysml` が変わっていた（Message の端
  `source`・`target` が加わり、`messages` が `action` に）。0.63.0 の jar には 0.63.0 のライブラリを使った。

### 追従

- 自作の 2 つのメッセージを 0.63.0 の文言にした（`scope_resolver.py` の種類の表、`validation_rules.py`）。比較の
  種類の表（`compare.py`）は両方の文言を同じ種類に分けるので、変えていない。
- MCP サーバの中継クラス（`SysMLDaemon`、0.62.0 の jar に対してコンパイル）は 0.63.0 の jar でもそのまま動いた。
- **ライブラリの `.index.json`**: 配布物の `sysml.library` には `.index.json` があり、段階 E のラベルはそれを含むライブラリで
  作った。sysml-mcp-server の README によると、`.index.json` があると継承した feature を部分集合の先にしたとき誤って
  未解決になる（サーバのテスト `test_inherited_feature_resolves_without_library_index`）。ただし版の差で増えたエラーは
  flow の文言だけで、未解決は 1 件も増えていないので、ラベルへの影響は見つからなかった。MCP サーバに入れるときは
  `.index.json` を消した（2026-10-23。サーバのテスト 42 件が通る）。次の版からは、消したライブラリでラベルを作る。

### 結果（正解を 0.63.0 にしたとき。Pilot に構文エラーの無い入力の行 + 種類）

| コーパス | 0.62.0 の正解 | 0.63.0 の正解 |
| --- | --- | --- |
| 開発（449 件） | 92.0% / 97.3% | 92.0% / 97.3% |
| held-out（127 件） | 84.3% / 97.6% | 84.3% / 97.6% |
| フォルダ（578 件） | 82.7% / 98.6% | 82.7% / 98.6% |
| 新しい held-out（12 件） | 85.4% / 97.2% | 85.4% / 97.2% |
| 正しいモデル・ファイルでの誤検出 | 0・0・0・1 | 0・0・0・1 |
| xpect（Pilot 自身が同じ箇所に出すもののうち自作も出す） | 126 / 132（95.5%） | 124 / 128（96.9%） |

- xpect の期待エラーは 0.62.0 のソースのテストから作ったので、文言の変わった flow の 4 件は、0.63.0 の Pilot では
  「同じメッセージ」にならず、分母から外れた。0.63.0 のソースのテストで作り直すのが正しい（未実施）。
- **追従の手間**: ダウンロードからラベルの作り直し、差の確認、メッセージの修正、測り直しまで、ハーネスがあるので
  機械的に済んだ（ラベルの作り直しが最も長く、約 1 時間）。今回の版は小さな変更だった。

### 残した課題

- ~~MCP サーバ（sysml-mcp-server）の Pilot を 0.63.0 にするかどうか~~ → 0.63.0 にした（2026-10-23。jar とライブラリを
  入れ替え、中継クラスをコンパイルし直した。0.62.0 は `C:\test\SysMLv2_pilot\pilot-0.62.0-backup` に退避）。
- xpect のコーパスを 0.63.0 のソース（`Source code` の zip）のテストで作り直す。
- 多重度の既定値の変更が実際にどんなモデルで違いを出すかを、Pilot のテスト（PR #815・#821）で確かめる。

## 再現手順

```
cd C:\test\verifying_SysML_v2_agentic_rag
.venv\Scripts\python.exe -I eval\pilot_parity\build_corpus.py
C:\test\SysMLv2_pilot\sysml-mcp-server\.venv\Scripts\python.exe -I eval\pilot_parity\label_pilot.py   # 数十分（索引キャッシュ無し）
.venv\Scripts\python.exe -I eval\pilot_parity\run_local.py
.venv\Scripts\python.exe -I eval\pilot_parity\compare.py
```

フォルダ単位のコーパス:

```
.venv\Scripts\python.exe eval\pilot_parity\build_folders.py
C:\test\SysMLv2_pilot\sysml-mcp-server\.venv\Scripts\python.exe -I eval\pilot_parity\label_pilot_folders.py
.venv\Scripts\python.exe eval\pilot_parity\build_folders.py --mutants
C:\test\SysMLv2_pilot\sysml-mcp-server\.venv\Scripts\python.exe -I eval\pilot_parity\label_pilot_folders.py
.venv\Scripts\python.exe -I eval\pilot_parity\run_local_folders.py
.venv\Scripts\python.exe -I eval\pilot_parity\run_local_folders.py --single
.venv\Scripts\python.exe -I eval\pilot_parity\compare.py --corpus eval\pilot_parity\folders\corpus --labels eval\pilot_parity\folders\labels --out eval\pilot_parity\folders\results\multi
.venv\Scripts\python.exe -I eval\pilot_parity\compare.py --corpus eval\pilot_parity\folders\corpus --labels eval\pilot_parity\folders\labels_single --out eval\pilot_parity\folders\results\single
.venv\Scripts\python.exe -I eval\pilot_parity\analyze_folders.py
```

新しい held-out（LLM が書いたモデル、`C:\test\sysml_models\eval\heldout2`）は、上の各スクリプトに `--heldout2`
（build_folders.py）・`--root heldout2`（label_pilot_folders.py・run_local_folders.py・analyze_folders.py）を付け、
compare.py の `--corpus`・`--labels`・`--out` を `eval\pilot_parity\heldout2\...` にする。

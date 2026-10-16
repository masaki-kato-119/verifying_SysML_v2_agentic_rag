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

## 再現手順

```
cd C:\test\verifying_SysML_v2_agentic_rag
.venv\Scripts\python.exe -I eval\pilot_parity\build_corpus.py
C:\test\SysMLv2_pilot\sysml-mcp-server\.venv\Scripts\python.exe -I eval\pilot_parity\label_pilot.py   # 数十分（索引キャッシュ無し）
.venv\Scripts\python.exe -I eval\pilot_parity\run_local.py
.venv\Scripts\python.exe -I eval\pilot_parity\compare.py
```

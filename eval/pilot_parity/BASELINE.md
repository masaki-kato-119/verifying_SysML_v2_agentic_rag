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

## 再現手順

```
cd C:\test\verifying_SysML_v2_agentic_rag
.venv\Scripts\python.exe -I eval\pilot_parity\build_corpus.py
C:\test\SysMLv2_pilot\sysml-mcp-server\.venv\Scripts\python.exe -I eval\pilot_parity\label_pilot.py   # 数十分（索引キャッシュ無し）
.venv\Scripts\python.exe -I eval\pilot_parity\run_local.py
.venv\Scripts\python.exe -I eval\pilot_parity\compare.py
```

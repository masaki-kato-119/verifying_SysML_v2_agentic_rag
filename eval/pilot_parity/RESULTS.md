# 自作 SysML v2 チェッカーは Pilot 実装と同じ水準に到達できるか（研究の結果、2026-10-16）

## 1. 問いと結論

**問い**: 自作 SysML v2 チェッカー（`sysml_v2_checker_advanced`、ANTLR4 + Python）は、OMG SysML v2 Pilot 実装 0.62.0（以下 Pilot）と同じ水準の判定に到達できるか。

**結論**:

1. **開発に使ったコーパスでは到達した**（Pilot に構文エラーの無い入力について）。Pilot の判定を「行 + エラーの種類」の単位で再現率 92.0%・適合率 97.2% で再現し、正しいモデルを誤りとしない。Pilot 自身のテスト（xpect）の期待エラーのうち、Pilot 自身が同じ箇所に出すものの 95.5% を自作も出す。研究前（P2・P3）は、行 + 種類の再現率 / 適合率が全体で 11% / 15%、xpect の期待エラーは 164 件中 31% だった。
2. **開発に使っていない公開モデル（held-out）でも、改善の大部分は汎化した**。構文エラーの無い入力で、行 + 種類の再現率は 3.4% → 81.4%、適合率は 21.7% → 84.9%。
3. **ただし held-out では、正しいモデルの誤検出が増えた**（Pilot がエラーを出さない 96 件のうち 17 件 → 27 件）。名前解決が扱えていない形と文法の穴が原因で、開発コーパスに無い書き方に対して規則が過剰に厳しい。**「到達できる」と言えるのは開発コーパスの範囲まで**で、一般の SysML v2 モデルについては、誤検出をなくす作業が残っている。
4. 方法としては、**Pilot をオラクルにした差分評価で、Pilot のロジック（KerML の名前解決、`SysMLValidator` の検証ルール）を読んで写し、境界を Pilot に実際のモデルを通して確かめる**やり方が有効だった。当初の見積もり（2.5〜3.5 か月）に対し、段階 A〜D は Claude と一緒の作業で 2 日（2026-10-15〜16）で終わった。

## 2. 方法

### オラクルと比較の単位

- 正解は Pilot 0.62.0 の診断（sysml-mcp-server の常駐デーモン経由、`label_pilot.py`）。自作は `lint_text_with_locations`（`run_local.py`）。
- エラーを「行 + 種類」（構文、未解決参照、アクセス範囲、型の種類、参照先の種類、束縛の上書き など 20 種類）に正規化して比べる（`compare.py`）。警告は比べない。自作の日本語のメッセージは、出したルールと文言から種類を決める（自作が Pilot と同じ英文を出せば Pilot の対応表で分類）。
- **連鎖の扱い**: 型や参照先が解決できないと、Pilot は同じ行に種類のエラー（`must be typed by …` / `Must reference …`）を、端の参照が誤っていると関係の数・flow の端のエラーを重ねて出す。自作は原因の指摘だけを出す（同じ原因で何件も出すと LLM の自己修正の邪魔になる。既存のテストもこれを固めている）。比較では、自作がその行に原因の指摘を出していれば、Pilot の連鎖のエラーも当たったと数える（開発コーパスで 193 件。`summary.json` の `cascade_credit`）。
- **Pilot に構文エラーがある入力は分けて数える**。Pilot はエラー回復で要素を落とし、その先の参照を未解決・種類違いにする。この連鎖は自作の名前解決では再現しないし、再現する価値も低い（原因は構文エラー 1 件）。

### コーパス

開発用（519 件、`build_corpus.py`）:

| 出どころ | 件数 | 内容 |
| --- | --- | --- |
| llm | 15 | LLM（Opus / Sonnet）が書いた AGV のモデル |
| verified | 5 | Pilot でエラー 0・警告 0 を確かめたテーマ別の最小例 |
| probe | 127 | 誤りをわざと入れた負例 |
| mutant | 141 | verified に LLM が実際にした誤りを 1 か所入れたもの（12 種類） |
| xpect | 126 | Pilot ソースの SysML の xpect テスト |
| kerml | 105 | Pilot ソースの KerML の名前解決のテスト（imports / scoping / visibility / linking）を SysML に書き換えたもの |

held-out（131 件・393 ファイル、`build_heldout.py`）: `C:\test\sysml_models` の公開リポジトリ（SysML-v2-Release の examples / training / validation 83、advent-of-sysml-v2 21、apollo-11 11、SysML-v2-Models 8、sysml-v2-lsp 4、sysmod 2 ほか）をディレクトリごとに 1 件にまとめたもの。**段階 A〜D の規則を作るときには一度も見ていない**。ただし SysML-v2-Release などは、この研究より前の自作チェッカーの開発（「730 件」のベースライン）で使われた可能性がある。

## 3. 段階ごとの結果（開発コーパス）

Pilot の層ごとに差を測り（P4、`ROADMAP.md`）、層の順に埋めた。詳細は `BASELINE.md`。

| 段階 | 内容 | 主な成果 |
| --- | --- | --- |
| A 文法の穴とパース停止 | `:=`、state の中の port など。パースエラーがあっても読めた部分を lint | 正しいモデルの誤検出 4 → 0、構文の再現率 90% |
| B スコープつき名前解決 | `scope_resolver.py`: 名前空間の木、import（可視性・`::*`・`::**`・filter）、継承メンバー、短い名前、式の中の名前と連鎖、アクセス範囲 | 未解決参照 17%（全体）→ 90%（構文エラーの無い unit）、アクセス範囲 26% → 95% |
| C 解決結果を使う種類の判定 | Pilot の `checkAllTypes` / `checkOneType` を KerML のメタクラスの表で写した | 種類の判定 → 95%、参照先の種類 → 93% |
| D 個別の検証ルール | `validation_rules.py`: objective の数、flow def の端の数、interface の端、モデルの水準で評価できる式 など。文法の穴の残り、メタデータの値による filter | xpect 83% → 95.5%、行 + 種類 → 92% |

研究前（P2）と研究後の比較（開発コーパス）:

| 指標 | P2（研究前） | 段階 D 後 | 目標 |
| --- | --- | --- | --- |
| 正しいモデル（verified 5 件）の誤検出 | 4 件 | **0 件** | 0 件 |
| unit 単位の誤検出（Pilot は問題なし・自作はエラー） | 29 件 | **0 件** | — |
| unit 単位の見逃し率 | 25.5% | 5.7% | ≤ 2% |
| 行 + 種類の再現率 / 適合率（全体） | 11.0% / 15.4% | 74.8% / 88.4% | — |
| 行 + 種類の再現率 / 適合率（Pilot に構文エラーの無い unit） | — | **92.0% / 97.2%** | ≥ 90% / ≥ 90% |
| 変異体で入れた誤りの検出 | 46% | **98%**（110 / 112） | ≥ 95% |
| xpect の期待エラー（同じ行・同じ種類） | 164 件中 51（31%） | 164 件中 126。Pilot 自身が同じ箇所に出す 132 件のうち **95.5%** | ≥ 95% |

種類ごと（Pilot に構文エラーの無い unit、再現率 / 適合率）: 未解決参照 96.2% / 97.8%、アクセス範囲 95.3% / 100%、型の種類 96.2% / 99.2%、参照先の種類 93.3% / 100%。

## 4. held-out での確認

| 指標（held-out 131 件） | 研究前（`9010907`） | 研究後（段階 D） |
| --- | --- | --- |
| 行 + 種類の再現率 / 適合率（Pilot に構文エラーの無い 127 件） | 3.4% / 21.7% | **81.4% / 84.9%** |
| 未解決参照 | 5.3% / 95.5% | 78.0% / 93.2% |
| アクセス範囲 | 3.0% / 50% | 81.8% / 100% |
| 型の種類 | 0.9% / 100% | 87.8% / 99.8% |
| 参照先の種類 | 0% / — | 92.1% / 98.6% |
| unit 単位の見逃し | 1 件 | 0 件 |
| **Pilot がエラーを出さない 96 件での誤検出** | **17 件** | **27 件** |

再現率は開発コーパスに近い水準まで汎化した。一方、正しいモデルでの誤検出は増えた。27 件の内訳（重なりあり）:

- 名前解決（17 件）: 参照の連鎖の区切りの取り違え（`perform startVehicle.trigger1;`・`exhibit vehicleStates.off;` の `.` が AST で `::` に正規化され、修飾名として解決される）、variation や再定義の中の再定義（`variation port :>> autoPort`、`part :>> cylinder`）、message の端の連鎖、式の中の名前（calc の中で後に宣言される名前など）、ライブラリの alias の先の種類（`PlaneAngleValue`）。
- 文法の穴（8 件）: 文書の中の自然文を含む sysmod のモデル、`first [0..1] x`、`in concern c : C`、`item redefines payload [0..1] : T` など。

これらは開発コーパスに無かった書き方で、規則が開発コーパスに合わせ込まれていたことを示す。どれも名前解決・文法の個別の不足で、方法の限界ではないと考えるが、直して held-out で測り直すまでは、一般のモデルで「到達した」とは言えない。

## 5. 残る差

- **Pilot に構文エラーがある入力**（開発コーパスで 70 件）: 未解決参照の再現率 28%。Pilot のエラー回復で落ちた要素の先の連鎖で、到達判定から外した。
- **unit 単位の見逃し 17 件**（目標 2% に対し 5.7%）: 12 件は構文エラーの無い入力で、未実装の個別ルール（束縛した値の上書き 4、constant の再定義、方向の食い違う再定義、subject の位置、invoke の引数、メタデータの annotatedElement の制約）。5 件は構文エラーのある入力。
- **held-out の誤検出 27 件**（4 章）。
- Pilot の検証メッセージ 186 種類のうち、コーパスに現れないものの多くは未対応。

## 6. 妥当性への脅威

- **開発と評価のデータの重なり**: 段階 A〜D の規則は開発コーパスを見ながら作った。held-out（4 章）で確かめたが、held-out の一部（SysML-v2-Release など）は研究前のチェッカーの開発で使われた可能性がある。
- **オラクルが 1 つの版だけ**: Pilot 0.62.0 の判定を正解とした。Pilot の版が変われば正解も変わる（段階 E で版ごとに測る）。
- **基準の読み替え**: xpect の基準は「期待エラー 164 件の 95%」から「Pilot 自身が同じ箇所に出す 132 件の 95%」に読み替えた（Pilot 自身が 164 件を満たさないため）。
- **連鎖の数え方**: Pilot が重ねて出すエラーを、自作が原因を出していれば当たりとした（193 件）。この規則を使わなければ、行 + 種類の再現率は下がる。
- **KerML テストの書き換え**: KerML の名前解決のテストを SysML に機械的に書き換えた。正解は書き換え後のテキストに Pilot が付けたので比較は正しいが、元のテストの意図とずれた箇所がありうる。
- **種類への正規化**: 「行 + 種類」は Pilot のメッセージと自作のルール名・文言の対応表に依存する。メッセージ単位では測っていない。

## 7. 作ったもの

| ファイル | 内容 |
| --- | --- |
| `sysml_v2_checker_advanced/scope_resolver.py`（約 1,500 行） | スコープつき名前解決、アクセス範囲、種類の判定 |
| `sysml_v2_checker_advanced/validation_rules.py` | 個別の検証ルール |
| `scripts/build_library_feature_names.py` | 標準ライブラリの型の本体で宣言される名前の表 |
| 文法（`SysMLMin.g4`）・変換（`antlr_transformer.py`） | 文法の穴、参照の形、端の元の書き方（付帯情報） |
| `eval/pilot_parity/`（`build_corpus.py`・`build_heldout.py`・`label_pilot.py`・`run_local.py`・`compare.py`・`analyze_gaps.py`） | 差分評価のハーネス |
| `tests/test_scope_resolver.py`・`tests/test_validation_rules.py` ほか | 規則の単体テスト（参照実装で確かめた形） |

コミット: `e54b426`（段階 A）、`dd1d8aa`・`0dad3de`（段階 B）、`c0cf9e2`（段階 C）、`ade1b60`（段階 D）。ブランチ `research/pilot-parity`。

## 8. 次の一手

1. held-out の誤検出 27 件をなくす（4 章の原因ごと）。特に、参照の連鎖の区切りを AST に残すこと（`perform a.b`・`exhibit a.b` の `.`）と、文法の穴。直したら held-out で測り直す。
2. held-out を開発に使わない評価用として固定し、以後の変更は開発コーパスと held-out の両方で測る。
3. 段階 E: Pilot の新しい版ごとにコーパスのラベルを作り直して測る。
4. `rule_confidence.json`（各指摘に付ける信頼度）を新しいルールで測り直す。

## 再現手順

```
cd C:\test\verifying_SysML_v2_agentic_rag
:: 開発コーパス
.venv\Scripts\python.exe -I eval\pilot_parity\build_corpus.py
C:\test\SysMLv2_pilot\sysml-mcp-server\.venv\Scripts\python.exe -I eval\pilot_parity\label_pilot.py
.venv\Scripts\python.exe -I eval\pilot_parity\run_local.py
.venv\Scripts\python.exe -I eval\pilot_parity\compare.py
:: held-out
.venv\Scripts\python.exe eval\pilot_parity\build_heldout.py
C:\test\SysMLv2_pilot\sysml-mcp-server\.venv\Scripts\python.exe -I eval\pilot_parity\label_pilot.py --corpus eval\pilot_parity\heldout\corpus --out eval\pilot_parity\heldout\labels\pilot
.venv\Scripts\python.exe -I eval\pilot_parity\run_local.py --corpus eval\pilot_parity\heldout\corpus --out eval\pilot_parity\heldout\labels\local
.venv\Scripts\python.exe -I eval\pilot_parity\compare.py --corpus eval\pilot_parity\heldout\corpus --labels eval\pilot_parity\heldout\labels --out eval\pilot_parity\heldout\results
```

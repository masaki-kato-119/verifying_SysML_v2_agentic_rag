# 自作 SysML v2 チェッカーは Pilot 実装と同じ水準に到達できるか（研究の結果、2026-10-23）

## 1. 問いと結論

**問い**: 自作 SysML v2 チェッカー（`sysml_v2_checker_advanced`、ANTLR4 + Python）は、OMG SysML v2 Pilot 実装 0.62.0（以下 Pilot）と同じ水準の判定に到達できるか。

**結論**: **Pilot に構文エラーの無いモデルについては、主な判定（名前解決・型の種類・参照先の種類・アクセス範囲）で Pilot の水準にほぼ到達した。正しいモデルをほとんど誤りとせず（適合率 97% 前後）、Pilot の指摘の 85〜92% を同じ行・同じ種類で出す。** ただし完全な同等ではない。構文エラーのあとの扱い、未実装の個別ルール、Pilot の版の追従が残る。

1. **開発に使ったコーパス**（519 件）: Pilot に構文エラーの無い入力で、「行 + エラーの種類」の再現率 **92.0%**・適合率 **97.3%**。正しいモデルの誤検出 0。Pilot 自身のテスト（xpect）の期待エラーのうち、Pilot 自身が同じ箇所に出すものの **95.5%**（126 / 132）を出す。研究前は全体で 11% / 15%、xpect は 31% だった。
2. **開発に使っていない公開モデル（held-out、131 件）**: 規則を作るときに見ていない段階 D の時点で、再現率 3.4% → **81.4%**、適合率 21.7% → 84.9% と、改善の大部分が汎化した。ただし正しいモデルの誤検出が 96 件中 27 件あった。原因（名前解決の不足と文法の穴）を直して誤検出は **0 件**、行 + 種類は 84.3% / 97.6% になった。**この修正は held-out を見ながら行ったので、修正後の数値は汎化の証拠にならない。**
3. **新しい held-out**（研究に使っていない 5 つの題材で、研究の文脈を持たない Sonnet / Haiku が 1 回で書いた 10 モデル・53 ファイル。**規則を変えずに測った**）: Pilot に構文エラーの無いファイルで **85.4% / 97.2%**、全ファイルで **87.7% / 95.6%**。Pilot がエラーを出さない 8 ファイルでの誤検出は **1 件**。汎化の証拠になるが、規模は小さい。
4. **複数ファイルのモデル**: 研究の当初のコーパスは 1 テキストずつで、複数ファイルを測っていなかった。自作のリンターで 4 ファイルのモデルを生成すると、1 ファイルずつの検証では、ファイルをまたぐ正しい参照がすべて誤検出になり、実用にならなかった（AGV の初稿でエラー 50 件中 46 件が誤検出）。Pilot と同じくフォルダを一緒に読む名前解決を入れ、フォルダ単位のコーパス（113 フォルダ・478 ファイル）で、正しいファイルの誤検出は 98 / 373 → **0 / 373**、ファイルをまたぐ誤記は Pilot が出した 117 版の **117 版すべて**を同じ行・同じ種類で出す。
5. **LLM の初稿の 77% に Pilot の構文エラーがある**（新しい held-out の 41 / 53 ファイル）。構文エラーのあとの判定は、Pilot（Xtext）と ANTLR のエラー回復の仕方の違いで一致しない。LLM の生成の検証という用途では、ここが最大の残差。
6. **方法**: Pilot をオラクルにした差分評価で、Pilot のロジック（KerML の名前解決、`SysMLValidator` の検証ルール）を読んで写し、境界を Pilot に小さな例を通して確かめる、というやり方が有効だった。当初の見積もり（2.5〜3.5 か月）に対し、段階 A〜D は Claude と一緒の作業で 2 日（2026-10-15〜16）、複数ファイル対応と新しい held-out までで計 4 日（〜10-23）だった。

## 2. 方法

### オラクルと比較の単位

- 正解は Pilot 0.62.0 の診断（sysml-mcp-server の常駐デーモン経由）。1 テキストは `label_pilot.py`、フォルダは `label_pilot_folders.py`（`validate_files`。MCP の `validate_sysml` に directory を渡したときと同じ）。自作は `lint_text_with_locations`（`run_local.py`・`run_local_folders.py`）。
- エラーを「行 + 種類」（構文、未解決参照、アクセス範囲、型の種類、参照先の種類、束縛の上書き など 20 種類）に正規化して比べる（`compare.py`）。警告は比べない。
- **連鎖の扱い**: 型や参照先が解決できないと、Pilot は同じ行に種類のエラー（`must be typed by …` / `Must reference …`）などを重ねて出す。自作は原因の指摘だけを出す（同じ原因で何件も出すと LLM の自己修正の邪魔になる）。比較では、自作がその行に原因を出していれば、Pilot の連鎖のエラーも当たりと数える（開発コーパスで 214 件）。
- **Pilot に構文エラーがある入力は分けて数える**。Pilot はエラー回復で要素を落とし、その先の参照を未解決・種類違いにする。主な指標は「Pilot に構文エラーの無い入力」で示し、全体の数値も併記する。

### コーパス

| コーパス | 規模 | 内容 | 規則づくりに使ったか |
| --- | --- | --- | --- |
| 開発（`build_corpus.py`） | 519 件 | LLM の AGV モデル 15、Pilot で確かめた最小例 5、負例 127、変異体 141、Pilot の xpect テスト 126、KerML の名前解決のテストを SysML に書き換えたもの 105 | 使った |
| held-out（`build_heldout.py`） | 131 件・393 ファイル | `C:\test\sysml_models` の公開リポジトリ（SysML-v2-Release、advent-of-sysml-v2、apollo-11、SysML-v2-Models、sysml-v2-lsp、sysmod ほか）をディレクトリごとに 1 件 | 段階 D までは使わず、その後の誤検出の修正で使った |
| フォルダ単位（`build_folders.py`） | 113 フォルダ・478 ファイル + 変異体 118 | 開発の LLM モデル・テーマ（dev）と held-out と同じリポジトリのフォルダを、ファイルごとに 1 件。Pilot がエラーを出さないフォルダにファイルをまたぐ誤記を 1 つ入れた版 | 使った |
| 新しい held-out（`build_folders.py --heldout2`） | 10 フォルダ・53 ファイル | 研究に使っていない 5 題材を Sonnet / Haiku が 1 回で書いた初稿（`C:\test\sysml_models\eval\heldout2`） | **使っていない**（規則を変えずに測った） |

## 3. 段階ごとの結果（開発コーパス）

Pilot の層ごとに差を測り（`ROADMAP.md`）、層の順に埋めた。詳細は `BASELINE.md`。

| 段階 | 内容 | 主な成果 |
| --- | --- | --- |
| A 文法の穴とパース停止 | `:=`、state の中の port など。パースエラーがあっても読めた部分を lint | 正しいモデルの誤検出 4 → 0、構文の再現率 90% |
| B スコープつき名前解決 | `scope_resolver.py`: 名前空間の木、import（可視性・`::*`・`::**`・filter）、継承メンバー、短い名前、式の中の名前と連鎖、アクセス範囲 | 未解決参照 17%（全体）→ 90%（構文エラーの無い unit）、アクセス範囲 26% → 95% |
| C 解決結果を使う種類の判定 | Pilot の `checkAllTypes` / `checkOneType` を KerML のメタクラスの表で写した | 種類の判定 → 95%、参照先の種類 → 93% |
| D 個別の検証ルール | `validation_rules.py`: objective の数、flow def の端の数、interface の端、モデルの水準で評価できる式 など | xpect 83% → 95.5%、行 + 種類 → 92% |

| 指標（開発コーパス） | 研究前 | 今 | 目標 |
| --- | --- | --- | --- |
| 正しいモデル（verified 5 件）の誤検出 | 4 件 | **0 件** | 0 件 |
| unit 単位の誤検出（Pilot は問題なし・自作はエラー） | 29 件 | **0 件** | — |
| unit 単位の見逃し率 | 25.5% | 5.7% | ≤ 2% |
| 行 + 種類の再現率 / 適合率（全体） | 11.0% / 15.4% | 81.0% / 83.5% | — |
| 行 + 種類の再現率 / 適合率（Pilot に構文エラーの無い 449 件） | — | **92.0% / 97.3%** | ≥ 90% / ≥ 90% |
| 変異体で入れた誤りの検出 | 46% | **98%**（110 / 112） | ≥ 95% |
| xpect の期待エラー（同じ行・同じ種類） | 164 件中 51（31%） | Pilot 自身が同じ箇所に出す 132 件のうち **95.5%**（126） | ≥ 95% |

種類ごと（Pilot に構文エラーの無い unit、再現率 / 適合率）: 未解決参照 96.2% / 98.0%、アクセス範囲 95.3% / 100%、型の種類 96.2% / 99.2%、参照先の種類 93.3% / 100%。

## 4. held-out での確認

| 指標（held-out 131 件、Pilot に構文エラーの無い 127 件） | 研究前 | 段階 D 後（初めて測った値） | 今（held-out を見て直した後） |
| --- | --- | --- | --- |
| 行 + 種類の再現率 / 適合率 | 3.4% / 21.7% | **81.4% / 84.9%** | 84.3% / 97.6% |
| 未解決参照 | 5.3% / 95.5% | 78.0% / 93.2% | 81.5% / 96.1% |
| 型の種類 | 0.9% / 100% | 87.8% / 99.8% | 89.6% / 99.8% |
| 参照先の種類 | 0% / — | 92.1% / 98.6% | 92.1% / 100% |
| **Pilot がエラーを出さない 96 件での誤検出** | 17 件 | **27 件** | **0 件** |

**汎化の証拠になるのは「段階 D 後」の列だけ。** 再現率は開発コーパスに近い水準まで汎化したが、正しいモデルでの誤検出が増え、規則が開発コーパスに合わせ込まれていたことが分かった。原因は、参照の連鎖の区切りの取り違え、variation や再定義の中の再定義、式の中の名前、文法の穴（sysmod の `in concern c : C`・`first [0..1] x`、advent-of-sysml-v2 の `defined by` など）で、どれも Pilot の書き方の意味を写して直した（`BASELINE.md` の各章）。

## 5. 複数ファイルのモデル

### 生成の実験で見つかったこと（2026-10-22）

自作のリンターをフィードバックにして 4 ファイルの AGV モデルを生成した（`C:\test\sysml_models\eval\linter_gen\RESULT.md`）。MCP の `lint_sysml_file` は 1 ファイルずつ検証していたので、ファイルをまたぐ正しい参照がすべて未解決になった。ほかのファイルの名前を渡しても、そのパッケージを import したファイルでは解決できない名前がすべて「不明」になり、同じファイルの中の誤記まで見逃した（誤りを 1 つずつ入れた 12 版で 4 件しか見つからない。Pilot は 12 件）。

### 対応

- **名前解決**: ほかのファイルの AST を、ファイルごとのルートに組み立て、各ファイルの最上位の要素をグローバルな名前空間に置く（Pilot で確認: 最上位の private な要素もほかのファイルから見え、ファイルの最上位の import はそのファイルの中だけに効く）。指摘は対象のファイルのものだけ。
- **MCP**: `lint_sysml_file(file_path, directory=None)` は、Pilot の `validate_sysml` と同じ決まり（既定で同じフォルダ、directory ならサブフォルダも、`""` なら 1 ファイル）で一緒に読む。構文エラーのあるファイルはエラー回復で読めた部分を使い、`partial_files` で知らせる。
- **測る中で見つけた不足**（どれも Pilot の判定を小さな例で確かめてから入れた）: accept の型、名前付きの接続の端と端の先頭、flow の `of T`、式の中の呼び出し・`new T(...)`・`->` の呼び出しの名前（import していないライブラリの関数を Pilot は未解決にする）、部分集合の先の連鎖、ラムダの型付き引数からの連鎖、前置のメタデータの baseType、flow・message の端の行、`frame c;`（既にある concern への参照）、連鎖の先の種類の語（`a.b` は Element、3 つ以上は Feature）、文法の穴 11 種類。

### 結果（フォルダ単位のコーパス）

| 指標（Pilot に構文エラーの無いファイル） | 1 ファイルずつ（以前の MCP） | フォルダを読む（今の MCP） |
| --- | --- | --- |
| dev（121 ファイル）: 行 + 種類 | 97.5% / 6.6% | **98.8% / 100%** |
| held-out のリポジトリ（339 ファイル）: 行 + 種類 | 83.6% / 74.9% | **81.7% / 98.4%** |
| 正しいファイルでの誤検出 | 96 / 373 | **0 / 373** |
| ファイルをまたぐ誤記（Pilot がその行に出した 117 版） | 117（同じ形の誤検出に埋もれる） | **117 / 117** |

AGV の初稿では、今の MCP は Pilot と同じ 4 件だけを出す（以前は 50 件中 46 件が誤検出）。

## 6. 新しい held-out: LLM が書いたモデル（2026-10-23）

今の held-out は誤検出の修正に使ったので、研究に使っていない題材（コーヒーマシン、電動アシスト自転車、エレベーター、人工衛星の電源サブシステム、輸液ポンプ。`C:\test\sysml_models\eval\heldout2\SPECS.md`）で、研究の文脈を持たないサブエージェント（開発に使った Opus ではなく Sonnet と Haiku）に 1 回で書かせた 10 モデル・53 ファイルを、**規則を変えずに**（コミット `6a1d61c`）フォルダ単位で Pilot と比べた。

| 指標 | 1 ファイルずつ（以前の MCP） | フォルダを読む（今の MCP） |
| --- | --- | --- |
| 行 + 種類（Pilot に構文エラーの無い 12 ファイル） | 85.4% / 26.1% | **85.4% / 97.2%** |
| 行 + 種類（全 53 ファイル） | 88.1% / 84.4% | **87.7% / 95.6%** |
| Pilot がエラーを出さない 8 ファイルでの誤検出 | 6 | **1** |
| unit 単位の見逃し | 0 | 1 |

- 全ファイルで、Pilot の未解決参照の 94.6%（544 / 575）、型の種類の 90.0%（505 / 561）、構文エラーの行の 73.1% を同じ行に出す。
- 誤検出 1 件は `entry action initial;`（`action` 付きの entry は新しい action の宣言）を、既存の action への参照として扱ったもの。見逃し 1 件は未実装の「再定義の方向の食い違い」。
- **LLM の初稿の 77%（41 / 53 ファイル）に Pilot の構文エラーがある。** 全ファイルの見逃しの大半は、その回復の連鎖（`A usage must be typed by definitions.` 52 件、`extraneous input ... expecting EOF` 34 件など）。
- Pilot がエラーを出さないフォルダが無かったので、ファイルをまたぐ誤記の版は作れなかった。

## 7. 残る差

- **Pilot に構文エラーがある入力**: Pilot（Xtext）は回復でファイルを早く閉じて残りを捨てることがあり（AGV の probe で `missing EOF at 'then'`）、ANTLR は読み続ける。その先の未解決・種類の連鎖は一致しない。どこで閉じるかは Xtext の回復の細部によるので、合わせる確かな方法が無い。LLM の初稿の大半が該当するので、生成の検証では最大の残差。
- **未実装の個別ルール**（開発の unit 単位の見逃し 17 件のうち構文エラーの無い 12 件など）: 束縛した値の上書き、constant の再定義、方向の食い違う再定義、subject の位置、invoke の引数、メタデータの annotatedElement の制約。Pilot の検証メッセージ 186 種類のうち、コーパスに現れないものの多くは未対応。
- **`entry action x;` と `entry x;` の区別**（新しい held-out の誤検出 1 件）。直すと新しい held-out も汎化の証拠でなくなる。
- **警告は比べていない**（例: 自作の共役ポートの警告、Pilot の `Duplicate of inherited member name`）。

## 8. 妥当性への脅威

- **開発と評価のデータの重なり**: 段階 A〜D の規則は開発コーパスを見ながら作った。最初の held-out は段階 D の後に誤検出の修正に使ったので、修正後の数値は汎化の証拠にならない。フォルダ単位のコーパスの held-out 側も同じリポジトリ。**汎化の証拠になるのは、最初の held-out の段階 D 後の値と、新しい held-out の値だけ。**
- **新しい held-out の規模と偏り**: 構文エラーの無いファイル 12 件、正しいファイル 8 件と小さい。書き手は Opus ではないが同じ Claude の系統で、題材の仕様は私が書いた。
- **オラクルが 1 つの版だけ**: Pilot 0.62.0 の判定を正解とした。版が変われば正解も変わる。
- **基準の読み替え**: xpect の基準は「期待エラー 164 件の 95%」から「Pilot 自身が同じ箇所に出す 132 件の 95%」に読み替えた（Pilot 自身が 164 件を満たさないため）。
- **連鎖の数え方**: Pilot が重ねて出すエラーを、自作が原因を出していれば当たりとした（開発で 214 件）。使わなければ再現率は下がる。
- **種類への正規化**: 「行 + 種類」は Pilot のメッセージと自作のルール名・文言の対応表に依存する。メッセージ単位では測っていない。
- **変異体は機械的**: ファイルをまたぐ誤記は 1 文字の削除だけで、LLM が実際にする誤りの分布とは違う。

## 9. 作ったもの

| ファイル | 内容 |
| --- | --- |
| `sysml_v2_checker_advanced/scope_resolver.py`（約 1,900 行） | スコープつき名前解決（複数ファイル）、アクセス範囲、種類の判定 |
| `sysml_v2_checker_advanced/validation_rules.py` | 個別の検証ルール |
| `sysml_v2_checker_advanced/model_files.py` | 一緒に検証するファイルを集める（validate_sysml と同じ決まり、エラー回復） |
| `sysml_v2_checker_advanced/mcp_server.py` | `lint_sysml_file` / `lint_sysml_text` のフォルダ対応 |
| 文法（`SysMLMin.g4`）・変換（`antlr_transformer.py`） | 文法の穴、参照の形、端と accept の行、エラー回復の木の読み方 |
| `scripts/build_library_feature_names.py` | 標準ライブラリの型の本体で宣言される名前の表 |
| `eval/pilot_parity/`（`build_corpus.py`・`build_heldout.py`・`build_folders.py`・`label_pilot*.py`・`run_local*.py`・`compare.py`・`analyze_*.py`） | 差分評価のハーネス |
| `tests/test_scope_resolver.py`・`test_validation_rules.py`・`test_multi_file.py`・`test_pilot_parity_stage_a.py` ほか | 規則の単体テスト（Pilot で確かめた形） |

コミット（ブランチ `research/pilot-parity`）: `e54b426`（段階 A）、`dd1d8aa`・`0dad3de`（B）、`c0cf9e2`（C）、`ade1b60`（D）、`01a00dd`（まとめと held-out）、`9eca491`（held-out の誤検出の修正）、`07a03de`（複数ファイル対応）、`2ee3dbb`（フォルダ単位のコーパス）、`edca2ea`（`->` の呼び出し・文法の穴）、`6a1d61c`（frame）、`2e0ed0d`（新しい held-out）。

## 10. 次の一手

1. **新しい held-out を広げる**: 公開リポジトリのまだ集めていないモデル（ダウンロードの許可が要る）、Claude 以外の LLM が書いたモデル。構文エラーの無いファイルを増やす。
2. 構文エラーのあとの扱い: LLM の初稿の大半が該当する。Pilot と同じ回復は難しいので、「構文エラーを先に直させる」使い方の案内（MCP の note）と合わせて考える。
3. 未実装の個別ルール（方向の食い違う再定義など）と `entry action x;` の区別。直すたびに、使った held-out は開発用に回す。
4. 段階 E: Pilot の新しい版ごとにコーパスのラベルを作り直して測る。
5. `rule_confidence.json`（各指摘に付ける信頼度）を新しいルールで測り直す。

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

フォルダ単位のコーパスと新しい held-out は `BASELINE.md` の「再現手順」。

# 自作 SysML v2 チェッカーは Pilot 実装と同じ水準に到達できるか（研究の結果、2026-11-05。4 つ目の held-out まで）

## 1. 問いと結論

**問い**: 自作 SysML v2 チェッカー（`sysml_v2_checker_advanced`、ANTLR4 + Python）は、OMG SysML v2 Pilot 実装 0.62.0（以下 Pilot）と同じ水準の判定に到達できるか。

**結論**: **Pilot に構文エラーの無いモデルについては、主な判定（名前解決・型の種類・参照先の種類・アクセス範囲）で Pilot の水準にほぼ到達した。正しいモデルをほとんど誤りとせず（適合率 97〜100%）、Pilot の指摘の 88〜95% を同じ行・同じ種類で出す。** 開発コーパスの目標（行 + 種類 ≥ 90% / ≥ 90%、unit 単位の見逃し ≤ 2%、変異体 ≥ 95%、xpect ≥ 95%）はすべて満たす。 研究に使っていない公開リポジトリ（3 つ目の held-out）では、規則を変えずに測ったとき 70.0% / 82.9%・正しいファイルの 28% に誤検出で、開発の水準に汎化しなかった。その誤検出の原因（短い名前・前置メタデータの位置・式などの文法の穴、解決できないメタデータの扱い）を直して 88.0% / 97.7%・誤検出 2 ファイルになった（この値は汎化の証拠ではない）。**直したあとに、Claude 以外の LLM（OpenAI の 2 モデル）が研究に使っていない題材で書いた 4 つ目の held-out を規則を変えずに測ると、全ファイルで 80.9% / 86.4%。ただし全 50 ファイルに Pilot の構文エラーがあり、構文エラーの無いモデルでの汎化はこのデータでは測れなかった。** LLM の生成の検証という用途では、構文エラーのあとの扱いが最大の残差のまま。

1. **開発に使ったコーパス**（519 件）: Pilot に構文エラーの無い入力で、「行 + エラーの種類」の再現率 **95.3%**・適合率 **97.5%**（2026-11-05。10-29 は 94.9% / 97.5%）。正しいモデルの誤検出 0、変異体で入れた誤りは 112 / 112 を検出。Pilot 自身のテスト（xpect）の期待エラーのうち、Pilot 自身が同じ箇所に出すものの **96.2%**（127 / 132）を出す（0.63.0 のテストでは **96.3%**、129 / 134）。研究前は全体で 11% / 15%、xpect は 31% だった。
2. **開発に使っていない公開モデル（held-out、131 件）**: 規則を作るときに見ていない段階 D の時点で、再現率 3.4% → **81.4%**、適合率 21.7% → 84.9% と、改善の大部分が汎化した。ただし正しいモデルの誤検出が 96 件中 27 件あった。原因（名前解決の不足と文法の穴）を直して誤検出は **0 件**、行 + 種類は 84.3% / 97.6% になった。**この修正は held-out を見ながら行ったので、修正後の数値は汎化の証拠にならない。**
3. **新しい held-out**（研究に使っていない 5 つの題材で、研究の文脈を持たない Sonnet / Haiku が 1 回で書いた 10 モデル・53 ファイル。**規則を変えずに測った**）: Pilot に構文エラーの無いファイルで **85.4% / 97.2%**、全ファイルで **87.7% / 95.6%**。Pilot がエラーを出さない 8 ファイルでの誤検出は **1 件**。汎化の証拠になるが、規模は小さい。その後、この held-out の誤検出（`entry action x;`）と見逃し（再定義の方向）を見て直したので、直した後の値（92.7% / 100%）は汎化の証拠にならない。
4. **複数ファイルのモデル**: 研究の当初のコーパスは 1 テキストずつで、複数ファイルを測っていなかった。自作のリンターで 4 ファイルのモデルを生成すると、1 ファイルずつの検証では、ファイルをまたぐ正しい参照がすべて誤検出になり、実用にならなかった（AGV の初稿でエラー 50 件中 46 件が誤検出）。Pilot と同じくフォルダを一緒に読む名前解決を入れ、フォルダ単位のコーパス（113 フォルダ・478 ファイル）で、正しいファイルの誤検出は 98 / 373 → **0 / 373**、ファイルをまたぐ誤記は Pilot が出した 117 版の **117 版すべて**を同じ行・同じ種類で出す。
5. **3 つ目の held-out**（研究に使っていない公開リポジトリ 16 個・483 ファイル、2026-10-29。**規則を変えずに測った**）: Pilot に構文エラーの無いファイルで **70.0% / 82.9%**。Pilot がエラーを出さない 153 ファイルのうち **43 ファイル**に誤検出。リポジトリごとの差が大きく（murillosva は適合率 99.6%、Bruce Douglass の書籍の例は文法の穴で約 900 件の構文エラーの誤検出）、誤検出の原因は文法の穴・型の種類・名前解決の不足（`BASELINE.md` の「3 つ目の held-out」）。
6. **3 つ目の held-out の誤検出の修正**（2026-11-05）: 構文エラーの誤検出の大半は、KerML の短い名前（`item <'DS-1'> c`・`enum <S> 'spoofing'`）を一部の要素にしか受理していなかったこと、前置メタデータを修飾子の後（`abstract #x part def`）に書けなかったことなど、文法の穴 30 種類。名前解決では、解決できない前置メタデータ（`#feature`）で要素の中身を「不明」にして、中の名前を確かめていなかった。直したあと **88.0% / 97.7%**（Pilot がエラーを出さない 153 ファイルのうち誤検出 2）。開発・最初の held-out・フォルダ単位も下がらず、最初の held-out は 85.0% → **94.0%** / 99.3%、フォルダ単位は 83.5% → **90.5% / 99.8%**、誤検出 0（`BASELINE.md` の「3 つ目の held-out の修正」）。
7. **4 つ目の held-out**（2026-11-05、**規則を変えずに測った**）: 研究に使っていない 5 題材（ロボット掃除機・スマート温室・踏切・風力発電のピッチ制御・3D プリンター）を、OpenAI の gpt-5.6-terra と gpt-5.4-mini が 1 回で書いた 10 モデル・50 ファイル。**50 ファイルすべてに Pilot の構文エラー**（`state machine def`・`calculation def`・`let`・`literal` など SysML v2 に無い書き方、可視性の無い import）。全ファイルで **80.9% / 86.4%**。自作も 50 ファイルすべてに構文エラーを出し、構文エラーの行の 79% を同じ行に出す。
8. **LLM の初稿の 77〜100% に Pilot の構文エラーがある**（2 つ目の held-out の 41 / 53、4 つ目の 50 / 50 ファイル）。構文エラーより後ろの判定は、Pilot（Xtext）と ANTLR のエラー回復の仕方の違いで一致しないことがあるが、測ると LLM の初稿では自作の指摘の 92〜96% が Pilot と同じ行・同じ種類だった（要素をまとめて落とす書き方のファイルでは 53%）。そこで MCP の lint は、構文エラーがあっても行ごとの構文エラーと読めた部分の指摘を返し、構文エラーより後ろの指摘に `after_syntax_error` を付けて「先に構文エラーを直す」よう案内するようにした（以前は構文エラーの文字列を 1 つ返すだけだった。§7）。
9. **Pilot の新しい版への追従**（段階 E、0.62.0 → 0.63.0）: 正解を 0.63.0 で作り直しても、4 つのコーパスの数値は変わらなかった。変わったのは flow の 2 つのメッセージの文言だけで、自作も合わせた。差分評価のハーネスで、追従はほぼ機械的に済んだ（`BASELINE.md` の「段階 E」）。あわせて MCP サーバ（sysml-mcp-server）の Pilot も 0.63.0 にし、`validate_sysml` と自作のリンターの文言をそろえた。
10. **方法**: Pilot をオラクルにした差分評価で、Pilot のロジック（KerML の名前解決、`SysMLValidator` の検証ルール）を読んで写し、境界を Pilot に小さな例を通して確かめる、というやり方が有効だった。当初の見積もり（2.5〜3.5 か月）に対し、段階 A〜D は Claude と一緒の作業で 2 日（2026-10-15〜16）、複数ファイル対応と新しい held-out までで計 4 日（〜10-23）だった。

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
| D' 残った個別ルール（10-23） | 再定義の方向、束縛の上書き、constant、`entry action x;`、`assign` の代入先と `Referent must be time varying`、呼び出しの引数（特化した定義も）、`Cannot annotate`、subject の位置、variant の連鎖、意味的メタデータの種類 | 行 + 種類 92.0% → 94.4%、unit 単位の見逃し 17 → 6 件（残りはすべて構文エラー）、変異体 110 → 112 / 112 |

| 指標（開発コーパス） | 研究前 | 今 | 目標 |
| --- | --- | --- | --- |
| 正しいモデル（verified 5 件）の誤検出 | 4 件 | **0 件** | 0 件 |
| unit 単位の誤検出（Pilot は問題なし・自作はエラー） | 29 件 | **0 件** | — |
| unit 単位の見逃し率 | 25.5% | **1.7%**（5 件、すべて Pilot に構文エラーのあるもの） | ≤ 2% |
| 行 + 種類の再現率 / 適合率（全体） | 11.0% / 15.4% | 81.0% / 83.5% | — |
| 行 + 種類の再現率 / 適合率（Pilot に構文エラーの無い 449 件） | — | **94.9% / 97.5%** | ≥ 90% / ≥ 90% |
| 変異体で入れた誤りの検出 | 46% | **100%**（112 / 112） | ≥ 95% |
| xpect の期待エラー（同じ行・同じ種類） | 164 件中 51（31%） | Pilot 自身が同じ箇所に出す 132 件のうち **96.2%**（127） | ≥ 95% |

種類ごと（Pilot に構文エラーの無い unit、再現率 / 適合率）: 未解決参照 96.2% / 98.0%、アクセス範囲 95.3% / 100%、型の種類 96.2% / 99.2%、参照先の種類 93.3% / 100%。

## 4. held-out での確認

| 指標（held-out 131 件、Pilot に構文エラーの無い 127 件） | 研究前 | 段階 D 後（初めて測った値） | 今（held-out を見て直した後） |
| --- | --- | --- | --- |
| 行 + 種類の再現率 / 適合率 | 3.4% / 21.7% | **81.4% / 84.9%** | 84.9% / 99.3% |
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

（表は 2026-10-22 の時点の値。その後の個別ルールの追加を含めた全体は 83.2% / 99.8%、正しいファイルの誤検出は 0 のまま。）

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

### 3 つ目の held-out の修正（2026-11-05）

3 つ目の held-out（公開リポジトリ 16 個、§1 の 5）の誤検出と見逃しを、リポジトリ × 種類 × メッセージで集計し、多いものから直した。
どの修正も、小さな例を Pilot 0.63.0 に通して境界を確かめた（`tests/test_pilot_parity_heldout3.py`）。

- **文法の穴（30 種類）**: KerML の短い名前を宣言名そのもの（`simpleName`）に持たせた（以前は part def・requirement などにだけ。
  `item <'DS-1'> c`・`enum <S> 'spoofing'`・`assert constraint <'C-1'> c`・`flow <'DF-01'> f of T`、短い名前だけの `part <p1>;`）。
  前置メタデータを修飾子の後（`abstract #x part def`・`derived #x attribute`・`end #x requirement ::> r`）、`view v : A::B::gv`、
  `perform action :>> g[1]`・`perform action g redefines g : T, U`、`frame Pkg::c;`・`frame c { ... }`、`first` の無い transition の始点
  （`transition Actions::Action::start then s;`。以前は名前として読んでいた）、`??`・前置の `istype`・`.metadata`・`->f({in o; ...})`、
  `render rendering : T :>> x`、`private doc`、`send "Command" via p`、`@tag : T`、定義の本体の中の定義（`viewpoint v { view def V; }`）など。
- **名前解決**: 解決できない前置メタデータ（`#feature`。import 先がフォルダに無い）で要素の中身を「不明」にしていた。参照実装と同じく
  何も足さないようにし、中の名前を確かめる。dependency の両端を確かめる（以前はまったく確かめていなかった）。同じ要求を 2 回 satisfy すると、
  satisfy 同士が同じ名前で互いに解決して型の判定を諦めていた。`frame c;` は参照する concern の型を持つ。`Base::Anything` の型は種類の判定から外す。
- **個別の規則**: `Must have a Natural value`・`Must redefine an owning-type feature`・`Must correspond to one feature of the instantiated type`（§8）。

| 指標（Pilot に構文エラーの無いファイルの行 + 種類） | 10-29 | 11-05 |
| --- | --- | --- |
| 開発（449 件） | 94.9% / 97.5% | **95.3% / 97.5%** |
| 最初の held-out（127 件） | 85.0% / 99.3% | **94.0% / 99.3%** |
| フォルダ単位（578 ファイル） | 83.5% / 99.8% | **90.5% / 99.8%** |
| 2 つ目の held-out（12 ファイル） | 92.7% / 100% | 92.7% / 100% |
| 3 つ目の held-out（464 ファイル） | 70.0% / 82.9% | **88.0% / 97.7%** |
| 3 つ目の held-out: Pilot がエラーを出さない 153 ファイルでの誤検出 | 43 ファイル | **2 ファイル** |
| xpect（Pilot 0.62.0 のテスト、同じ行・同じ種類） | 127 | **129** |

変異体は 112 / 112 のまま、開発・最初の held-out・フォルダ単位で Pilot がエラーを出さない unit での誤検出は 0 のまま。

### 4 つ目の held-out: Claude 以外の LLM が書いたモデル（2026-11-05）

2 つ目の held-out と同じ形式で、研究に使っていない 5 題材（`C:\test\sysml_models\eval\heldout4\SPECS.md`）を、OpenAI の
gpt-5.6-terra と gpt-5.4-mini に 1 回で書かせた（`generate_heldout4.py`。研究の文脈・検証ツールは渡さない）。10 モデル・50 ファイル。
3 つ目の held-out の修正を終えた時点のコードで、中身を見ずに測った（その後この held-out を見て規則は変えていない）。

| 指標 | 値 |
| --- | --- |
| Pilot に構文エラーのあるファイル | **50 / 50**（gpt-5.4-mini 368 件、gpt-5.6-terra 176 件） |
| 行 + 種類（全ファイル） | **80.9% / 86.4%** |
| 自作も構文エラーを出したファイル | 50 / 50 |
| 構文エラーの行（再現率 / 適合率） | 79.4% / 66.2% |
| Pilot の最初の構文エラーより後ろの意味の指摘（同じ行・同じ種類） | 適合率 91.9%・再現率 81.3% |

構文エラーの書き方は、可視性の無い import のほか、`state machine def`・`calculation def`・`event def`・`let x : T;`・`literal a;`・
`reference u : U;`・`input x = ...;`・`require constraint`、`connection a.b to c.d via l;` など SysML v2 に無い書き方。
Sonnet / Haiku（2 つ目の held-out、77%）より崩れ方が大きい。**Pilot に構文エラーの無いファイルが無いので、構文エラーの無いモデルでの汎化は
このデータでは測れない。**

### 確信度（`rule_confidence.json`）の作り直し（2026-11-05）

各指摘に付ける確信度を、730 件コーパスの「そのルールだけが error を出したファイルを参照実装も不正とした割合」（ファイル単位の一致の上限）から、
差分評価の全コーパスでの「このルールの指摘のうち、Pilot が同じ行に同じ種類のエラーを出した割合」（指摘単位）に作り直した
（`build_rule_confidence.py`。指摘 5 件以上のルール 18 個。Pilot に構文エラーの無いファイルだけの値 `value_without_syntax_errors` も持つ）。
主なもの: `_check_scoped_references` 0.916（構文エラー無し 0.986、16,806 件）、`_check_usage_kinds_scoped` 0.900（0.974）、
`_check_pilot_validations` 0.941（0.992）、`_check_accessible_features_scoped` 0.534（0.646）。低いもの（`_check_transition_trigger_type` 0 / 10、
`_check_event_references` 0 / 6、`_check_verify_requirement_placement` 0.278）は、Pilot と違う種類・違う行に出しているか誤検出で、見直しの候補。

## 7. 残る差

- **知らない書き方への汎化**: 3 つ目の held-out（公開リポジトリ）の誤検出は直したが、直したので汎化の証拠でなくなった。4 つ目の held-out（OpenAI の LLM）は全ファイルに構文エラーがあり、構文エラーの無いモデルでの汎化はまだ確かめられていない。3 つ目の held-out の再現率（88.0%）の残りは、書籍の例のメタデータの本体から別の feature を参照する書き方（`Must be model-level evaluable` 160 件）、アクセス範囲（`_check_accessible_features_scoped` は Pilot に構文エラーの無いファイルでも指摘の一致が 65%）など。

- **Pilot に構文エラーがある入力**: Pilot（Xtext）は回復でファイルを早く閉じて残りを捨てることがあり（AGV の probe で `missing EOF at 'then'`）、ANTLR は読み続ける。その先の未解決・種類の連鎖は一致しない。どこで閉じるかは Xtext の回復の細部によるので、合わせる確かな方法が無い。**扱い（2026-11-05）**: Pilot の最初の構文エラーより後ろの行で、自作の指摘が Pilot と同じ行・同じ種類だった割合は、2 つ目の held-out（Sonnet / Haiku）96.2%、4 つ目（OpenAI）91.9%、フォルダ単位のコーパスの構文エラーのある 18 ファイル 52.7%（大半は Pilot が要素をまとめて落とす書き方）。LLM の初稿では後ろの指摘もほとんど正しいので捨てず、MCP の lint で `after_syntax_error: true`（暫定）を付けて返す。構文エラーそのもの（自作の文法は寛容なので、可視性の無い import など参照実装では構文エラーになる書き方の指摘も含める）は `syntax_error: true`・`summary.syntax_errors` で数え、note で「先に構文エラーを直す」よう案内する（`sysml_v2_mcp_usage.md`）。
- **個別ルール**: 方向の食い違う再定義・束縛した値の上書き・constant の再定義は 2026-10-23 に入れた（開発の unit 単位の見逃し 17 → 12 件）。同じ日に `assign` の代入先と `Referent must be time varying`、呼び出しの引数、メタデータの annotatedElement、`include use case` の subject の位置も入れた。続けて variation の usage の variant を `.` でたどる形、意味的メタデータの baseType による種類、特化した定義の呼び出しも入れ、構文エラーの無い入力での unit 単位の見逃しは 0 になった（12 → 6 件、残りはすべて Pilot に構文エラーのあるもの）。Pilot の検証メッセージ 186 種類のうち、コーパスに現れないものの多くは未対応。2026-11-05 に、コーパスに現れていて未実装だった `Must have a Natural value`（多重度に単位を書く `attribute t : Real [s];`。LLM がよく書く）、`Must redefine an owning-type feature`（メタデータの本体の名前がメタデータの型に無い、型を import していない）、`Must correspond to one feature of the instantiated type`（`new T(...)` の T が無い、名前付きの引数が T に無い）を入れた。
- **さらに新しい held-out**: `entry action x;` の区別（新しい held-out の誤検出）と再定義の方向（同じく見逃し）を直したので、新しい held-out も汎化の証拠でなくなった。
- **警告は比べていない**（例: 自作の共役ポートの警告、Pilot の `Duplicate of inherited member name`）。

## 8. 妥当性への脅威

- **開発と評価のデータの重なり**: 段階 A〜D の規則は開発コーパスを見ながら作った。最初の held-out は段階 D の後に誤検出の修正に使ったので、修正後の数値は汎化の証拠にならない。フォルダ単位のコーパスの held-out 側も同じリポジトリ。**汎化の証拠になるのは、最初の held-out の段階 D 後の値、新しい held-out（LLM）の値、3 つ目の held-out（公開リポジトリ、`efe0e50` で測った値）、4 つ目の held-out（OpenAI の LLM）の値だけ。** 3 つ目の held-out の修正後の値（88.0% / 97.7%）は、その held-out を見て直したので汎化の証拠ではない。
- **新しい held-out の規模と偏り**: 構文エラーの無いファイル 12 件、正しいファイル 8 件と小さい。書き手は Opus ではないが同じ Claude の系統で、題材の仕様は私が書いた。
- **4 つ目の held-out**: 書き手は Claude 以外（OpenAI）だが、題材の仕様は Claude（このセッション）が書いた。全ファイルに構文エラーがあるので、行 + 種類の値は構文エラーの回復の違いを含む。最初に測ったあと、ほかのコーパスの誤検出（`attribute def A { attribute i : Integer; attribute x : A[i]; }`）を直して測り直したが、この held-out の値は変わらなかった（80.9% / 86.4%）。この held-out を見て直したものは無い。
- **確信度の表はすべてのコーパスで測った**: 規則づくりに使ったコーパスも含むので、値は新しいモデルでの精度より高めに出うる。
- **オラクルの版**: Pilot 0.62.0 の判定を正解とし、段階 E で 0.63.0 でも測った（数値は同じ）。xpect の期待エラーは 0.62.0 のソースのテストのまま。0.63.0 のラベルは、配布物の `sysml.library/.index.json`（継承した feature の解決を誤らせることがある）を含むライブラリで作った。版の差に未解決の増加は無く、影響は見つかっていない。
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
| `sysml_v2_checker_advanced/mcp_server.py` | `lint_sysml_file` / `lint_sysml_text` のフォルダ対応、構文エラーのあるテキストの返し方（`syntax_error`・`after_syntax_error`） |
| `sysml_v2_checker_advanced/rule_confidence.json` | 指摘単位の確信度の表（`eval/pilot_parity/build_rule_confidence.py` が作る） |
| `eval/pilot_parity/generate_heldout4.py` | 4 つ目の held-out の生成（OpenAI） |
| 文法（`SysMLMin.g4`）・変換（`antlr_transformer.py`） | 文法の穴、参照の形、端と accept の行、エラー回復の木の読み方 |
| `scripts/build_library_feature_names.py` | 標準ライブラリの型の本体で宣言される名前の表 |
| `scripts/build_metaclass_supertypes.py` | SysML・KerML のメタクラスの特化の表（`Cannot annotate` に使う） |
| `eval/pilot_parity/`（`build_corpus.py`・`build_heldout.py`・`build_folders.py`・`label_pilot*.py`・`run_local*.py`・`compare.py`・`analyze_*.py`） | 差分評価のハーネス |
| `tests/test_scope_resolver.py`・`test_validation_rules.py`・`test_multi_file.py`・`test_pilot_parity_stage_a.py`・`test_pilot_parity_more_rules.py`・`test_pilot_parity_heldout3.py`・`test_mcp_syntax_errors.py` ほか | 規則の単体テスト（Pilot で確かめた形） |

コミット（ブランチ `research/pilot-parity`）: `e54b426`（段階 A）、`dd1d8aa`・`0dad3de`（B）、`c0cf9e2`（C）、`ade1b60`（D）、`01a00dd`（まとめと held-out）、`9eca491`（held-out の誤検出の修正）、`07a03de`（複数ファイル対応）、`2ee3dbb`（フォルダ単位のコーパス）、`edca2ea`（`->` の呼び出し・文法の穴）、`6a1d61c`（frame）、`2e0ed0d`（新しい held-out）、`32d85dd`・`9322ca9`（段階 E）、`5d0c573`・`0d7f07e`・`efe0e50`（残った個別ルール）。MCP サーバの 0.63.0 への更新は SysMLv2_pilot の `14cd238`（ブランチ `mcp-multi-file`）。

## 10. 次の一手

2026-11-05 に、10-29 の次の一手の 1〜4（3 つ目の held-out の修正と 4 つ目の held-out、構文エラーのあとの扱い、コーパスに現れていた未実装のメッセージ、確信度の作り直し）を済ませた。

1. **構文エラーの無いモデルでの汎化を確かめる**: 4 つ目の held-out は全ファイルに構文エラーがあった。LLM に構文エラーを直させた版（自作の MCP の指摘で 1〜2 回直させる）を 5 つ目の held-out にすると、生成の検証の実際の流れにも近い。
2. **確信度の低いルールを見直す**: `_check_accessible_features_scoped`（構文エラーの無いファイルでも 65%）、`_check_transition_trigger_type`・`_check_event_references`（0 件一致）、`_check_verify_requirement_placement`。違う種類・違う行に出しているのか、誤検出なのかを Pilot の小さな例で確かめる。
3. 3 つ目の held-out の残りの見逃し（メタデータの本体から別の feature を参照する書き方の `Must be model-level evaluable`、アクセス範囲）と、コーパスに現れない Pilot の検証メッセージ。小さな例を Pilot に通して境界を確かめてから入れる。直すたびに、使った held-out は開発用に回す。
4. Pilot の新しい版が出るたびに段階 E を繰り返す（ダウンロード → `.index.json` を消したライブラリでラベルを作り直す → `diff_pilot_versions.py` → 差を直す → MCP サーバも同じ版にする）。xpect は新しい版のソースのテストで作り直す。

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

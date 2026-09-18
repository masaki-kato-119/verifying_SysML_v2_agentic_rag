# verifying SysML v2 agentic rag

**openai_call_mcp.py** を使って OpenAI と複数の MCP サーバを接続して対話できます。

---

## 概要

- 複数の MCP サーバ定義を JSON（デフォルト `mcp_servers.json`）で登録して起動時に読み込みます。
- **登録した全サーバのツールを同時に LLM へ提示します。** どのバックエンドを使うかは
  LLM がクエリに応じて選択し、1 回の応答内で複数バックエンドを併用できます。
  ツール名は `<サーバ識別子>__<ツール名>`（例: `hybrid_rag_mcp_server__hybrid_search`）に
  正規化され、衝突しません。
- 実行中にサーバ一覧表示と提示範囲の絞り込みが可能です
  （内部コマンド `/servers`, `/use <name>` で 1 サーバに限定、`/use all` で解除）。
- **NEW**: SysML v2 Advanced Checker を MCP サーバとして統合し、LLM から SysML ファイルの解析・構文チェックが可能です。

> **公開インターフェースについて**: このリポジトリが外部に対して保証する公開契約は、
> 下記の **3 つの MCP サーバ（stdio 経由）** と、SysML v2 Checker が別途エクスポートする
> Python API（`sysml_v2_checker_advanced.parse_sysml`/`lint_sysml`、
> `sysml_v2_checker_advanced.antlr_transformer.parse_sysml_with_semantic_model`、
> `sysml_v2_checker_advanced.semantic_model.build_semantic_model` 等、詳細は同パッケージの
> docstring 参照）です。`HybridRAG/rag/`・`GraphRAG/graphrag/` 配下の各モジュールは
> 内部実装であり、シグネチャの安定性は保証されません。

---

## 利用可能な MCP サーバ

### 1. Hybrid RAG MCP Server
- ハイブリッド RAG システム
- 文書検索と生成の組み合わせ

### 2. Graph RAG MCP Server  
- グラフベース RAG システム
- 知識グラフを活用した情報検索

### 3. **SysML v2 Checker MCP Server** 🆕
- SysML v2 ファイルのパース・構文チェック
- AST 生成と JSON 出力
- リアルタイム構文エラー検出
- RAG 用データ生成対応

#### SysML v2 Checker の機能
- **ファイル解析**: SysML ファイルの完全パース
- **テキスト解析**: SysML コードの直接解析
- **構文チェック**: エラー・警告・情報の検出
- **AST 生成**: JSON 形式での抽象構文木出力
- **完全解析**: パース + リント + AST を一括実行
- **Semantic Model 生成**: 要素の安定ID・元テキスト上の位置・参照関係（specialization/feature_typing/connection/satisfy/verify）を取得（`get_semantic_model_file`/`get_semantic_model_text`。詳細は `sysml_v2_mcp_usage.md`）

---

## 前提条件

- Python 3.x
- 環境変数 `OPENAI_API_KEY` を設定してください（必須）。
- `fastmcp` があれば stdio ベースのサーバ起動/接続が可能です（無ければ TCP を利用）。

---

## サーバ定義（JSON 例）

ファイル名: `mcp_servers.json`（デフォルト）

```json
{
  "mcpServers": {
    "Hybrid RAG MCP Server": {
      "command": "python",
      "args": ["HybridRAG/mcp_server.py"],
      "cwd": ".",
      "env": {"OPENAI_API_KEY": "$OPENAI_API_KEY"}
    },
    "Graph RAG MCP Server": {
      "command": "python", 
      "args": ["GraphRAG/mcp_server.py"],
      "cwd": ".",
      "env": {"OPENAI_API_KEY": "$OPENAI_API_KEY"},
      "expose_tools": ["smart_search", "search_graph", "find_path"]
    },
    "SysML v2 Checker": {
      "command": "python",
      "args": ["sysml_v2_checker_advanced/mcp_server.py"],
      "cwd": ".",
      "env": {}
    }
  }
}
```

- 各サーバ定義は `command` + `args`（stdio 起動）または `url`（tcp 接続）のいずれかを含めてください。
- **パスは相対パスで記述してください。** `args` と `cwd` の相対パスは、この JSON ファイルが置かれたディレクトリを基準に解決されます（プロセスの起動ディレクトリには依存しません）。絶対パスも指定できますが、環境間で使い回せなくなります。
- `expose_tools` を指定すると、そのサーバから **LLM に見せるツールを許可リストで絞れます**。
  未指定なら全ツールを提示します。GraphRAG は管理系を含め 31 ツールあるため、
  検索系だけに絞って選択ノイズを減らす用途を想定しています。
- `hide_tool_params` を指定すると、**ツールごとに個別のパラメータを LLM から隠せます**
  （`{"ツール名": ["パラメータ名", ...]}`）。隠したパラメータはサーバ側の既定値が
  使われます。`hybrid_search` は 24 個の引数を持ち、すべて見せると LLM が
  リランクやクエリ拡張などの重いオプションを軒並み有効化してしまうため、
  既定では安価なもの 12 個だけを提示しています。
- 起動時にサーバープロセスへ渡す環境変数がある場合は `env` オブジェクトを指定できます（例: `"env": {"OPENAI_API_KEY": "$OPENAI_API_KEY"}`）。
  - **セキュリティ推奨:** 実際のキーをファイルに埋め込まず、`"$OPENAI_API_KEY"` のように `$` で始めて **ホスト環境の変数を参照**する方法を推奨します。
- `cwd` を指定したい場合は各サーバ定義に "cwd": "path" を追加できます。

**重要:** 既に手動でサーバープロセスを起動している場合、CLIからの `env` 透過はその既存プロセスには適用されません。`env` を使って自動的に環境変数を注入したい場合は、サーバーを停止してから `openai_call_mcp.py` を実行してください。

---

## ▶️ 実行方法

1) 仮想環境を作る（推奨）:

Windows (PowerShell):
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

macOS/Linux:
```
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

依存関係は `pyproject.toml` に一元化されています（以前の 3 つの `requirements.txt` は廃止しました）。
開発用ツール（pytest / ruff）も入れる場合は `pip install -e ".[dev]"`、
ドキュメントビルド用は `pip install -e ".[docs]"` を使ってください。

`requires-python = ">=3.10"`（Python 3.10〜3.13 で動作確認済み）。

2) CLI を実行:
```
python openai_call_mcp.py
```

主なオプション:
- `--servers-file` : サーバ定義JSONのパス（デフォルト: `mcp_servers.json`）
- `--system-prompt-file` : システムプロンプトのパス（デフォルト: `openai.md`）
- `--no-mcp` : MCP を使わず純粋に LLM の応答のみ
- `--model` : OpenAI モデル名（デフォルト: `gpt-5.6-terra`）
- `--reasoning-effort` : reasoning モデルの推論量（デフォルト: `none`）
- `--log-dir` : ログ保存先（デフォルト: `logs`）

### 使用モデル

| 用途 | モデル | 環境変数で上書き |
|---|---|---|
| オーケストレータ（ツール選択・最終回答） | `gpt-5.6-terra` | `--model` |
| HybridRAG の要約・クエリ拡張 | `gpt-5.6-luna` | `RAG_LLM_MODEL` |
| HybridRAG のエンティティ抽出 | `gpt-5.6-luna` | `RAG_ENTITY_EXTRACTION_MODEL` |
| GraphRAG のクエリ拡張・ノード要約・経路説明 | `gpt-5.6-luna` | `GRAPHRAG_LLM_MODEL` |
| 埋め込み | `text-embedding-3-small` | （変更非推奨） |

埋め込みモデルは現行の推奨モデルであり廃止予定もないため据え置いています。
変更すると全チャンクの再インデックスが必要になります。

**GPT-5 系（reasoning モデル）の制約**（2026-08 に実 API で確認）:

- `temperature` は非対応（デフォルト 1 のみ）
- `max_tokens` は非対応。`max_completion_tokens` を使う
- `reasoning_effort` は `none` / `low` などに対応。`minimal` は非対応
- **`/v1/chat/completions` では function tools と reasoning を併用できない。**
  ツールを使う呼び出しでは `reasoning_effort='none'` が必須。推論とツールを
  両立させたい場合は `/v1/responses` への移行が必要

### システムプロンプトの選択

検証の厳格さが異なる 2 種類のプロンプトを同梱しています。`--system-prompt-file` で切り替えてください。

| ファイル | 方針 |
|---|---|
| `openai.md`（デフォルト） | 緩和版。探索段階での論点整理を許容し、断定時のみ RAG 根拠と使用 RAG 種別の明示を求める。 |
| `openai_strict.md` | 厳格版。全回答で RAG 根拠・出典・使用 RAG 種別の明示を必須とし、RAG 外の知識の利用を一切禁じる。 |

```
python openai_call_mcp.py --system-prompt-file openai_strict.md
```

### NLTK データの配置（テストを通すのに必要）

GraphRAG の英語形態素解析は NLTK のコーパスを使う。**venv 配下へ置くこと**:

```
python -m nltk.downloader -d .venv/nltk_data punkt punkt_tab averaged_perceptron_tagger averaged_perceptron_tagger_eng wordnet omw-1.4
```

`wordnet` と `omw-1.4` は zip のままダウンロードされることがあるので、
`.venv/nltk_data/corpora/` 配下に `wordnet.zip` しか無い場合は展開しておく。

**既定の置き場所（`~/AppData/Roaming/nltk_data`）ではいけない。** nltk 3.10.3 が
導入した `nltk/pathsec.py` の `validate_path` は、パスを `resolve()` してから
許可リストと突き合わせる。Windows のパッケージアプリ配下でプロセスを動かすと
`AppData\Roaming` が `AppData\Local\Packages\<app>\LocalCache\Roaming` へ
転送されるため、解決後のパスが許可リストと一致せず
`PermissionError: Security Violation ... Unauthorized path` になる。
データもコードも正常なのにテストだけが落ちるので原因が分かりにくい
（2026-09-14 に実際に12件が落ちた。`tests/test_graphrag_morphological_analyzer_en.py`
7件と `tests/test_graphrag_pipeline.py` 5件）。

`.venv/nltk_data` は nltk の既定探索パスに入っており、かつ転送の影響を受けない
ので、ここに置けば環境によらず解決する。

---

## ランタイム内部コマンド

- `/servers` — 登録済みMCPサーバ一覧と、現在の提示範囲を表示
- `/use <name>` — 指定したサーバのツールだけを提示する（絞り込み）
- `/use all` — 絞り込みを解除し、全サーバのツールを提示する（デフォルト）
- `/help` — ヘルプ表示
- `/paste` — 複数行入力モード（SysML コード貼り付けに便利）

---

## 使用例

### 🗂️ 初回セットアップ：ドキュメントを索引化する

HybridRAG・GraphRAGとも、索引データ（`HybridRAG/data/`・`GraphRAG/data/graphs/`）は
`.gitignore`対象でリポジトリに含まれません。**クローン直後は索引が空なので、
検索系ツールを使う前に一度ドキュメントを索引化してください。** 索引化もLLMに
自然文で依頼すれば該当ツールを自動選択します。

```
>> SysML_Language_Specification_v2.pdf をHybridRAGに索引化してください
   （→ HybridRAGの index_path ツールが選ばれる想定。txt/md/pdf/docx/xlsx/pptx/sysmlに対応）

>> SysML_Language_Specification_v2.pdf からGraphRAGのグラフを構築してください
   （→ GraphRAGの process_pdf_and_save ツールが選ばれる想定。
      大きいPDFは pages パラメータでページ範囲を絞ると高速に試せる）
```

直接ツール名を指定したい場合は `/use <サーバ名>` で絞り込んでから依頼してください。

- `index_path`（HybridRAG）: チャンク分割 + `text-embedding-3-small` での埋め込み生成のみ。
  LLM呼び出しは無し（安価）。
- `process_pdf_and_save`（GraphRAG）: デフォルト（`use_llm=False`）ではLLMを一切使わず、
  パターンベースでグラフを構築する（無料）。保存先は常に
  `GraphRAG/data/graphs/{PDFファイル名}.pkl`で、最初に登録したグラフが自動的に
  デフォルトグラフになる。

索引化後は「RAG システムの使用例」（下記）のクエリがヒットするようになります。

### SysML v2 Checker の使用例

```
>> test_sysml.sysml ファイルを解析して、構文エラーがあるかチェックしてください

>> 以下の SysML コードに問題がないか確認してください：
package TestPackage {
    part def Vehicle {
        attribute mass : Real;
        attribute speed : Real;
    }
}

>> SysML ファイルの AST を JSON 形式で取得して、RAG 用のデータとして使いたいです

>> /use SysML v2 Checker
>> /paste
package ComplexModel {
    part def Engine {
        attribute power : Real;
        port intake : IntakePort;
    }
}
.
```

### RAG システムの使用例

バックエンドの指定は不要です。クエリの性質に応じて LLM が選択します。

```
>> SysML v2 における attribute の定義を、原文を引用して説明してください
   （→ 横断検索が要るので hybrid 系ツールが選ばれる想定）

>> part definition と item definition の関係を、両者をつなぐ経路として説明してください
   （→ 経路探索なので graph 系ツールが選ばれる想定）
```

特定のバックエンドだけを試したい場合は `/use` で絞り込めます。

```
>> /use Graph RAG MCP Server
>> port に直接関係する概念を列挙してください
>> /use all
```

実際にどちらが選ばれたかは、会話ログを集計して確認できます。

```bash
python scripts/analyze_backend_usage.py
```

---

## SysML v2 Viewer

SysML v2 のテキストを書きながら、構造図・検証結果・影響範囲・修正候補を同じ画面で
確認するためのローカル Web アプリです。左にエディタ（Monaco）、右に SVG の図と
インスペクタが並びます。

> **位置づけ**: これは**ローカル開発ツール**であり、上記 3 つの MCP サーバのような
> 公開契約ではありません。レビュー状態の保存先がブラウザの `localStorage` だけである
> など、単一利用者を前提にした割り切りがいくつか入っています。何ができて何が
> できないかの完全な一覧は `viewer/COVERAGE.md` にあります。

### 起動

```bash
.venv/Scripts/python.exe -m uvicorn viewer.backend.app:app --port 8420
```

起動後 `http://localhost:8420` を開きます。Windows では同じ内容の `run_backend.bat`
でも起動できます。

> `--reload` は付けても**バックエンドの変更を取りこぼすことがあります**。
> `viewer/backend/` を編集したら、リロード任せにせずプロセスを止めて起動し直して
> ください。`viewer/frontend/app.js` を編集した場合は、ブラウザの再読み込みでは
> 古い JS が残ることがあるのでタブを閉じて開き直してください。

### できること

- **構造図の描画** — package / definition / usage など 35 種類以上の要素と、
  継承・型付け・接続・satisfy/verify・状態遷移などの関連を描きます。
  ビューは構造・要求トレーサビリティ・検証・状態遷移・アクティビティの 5 種類。
- **テキストと図の選択同期** — 図の要素をクリックすると対応するテキスト位置へ飛び、
  インスペクタに関連エッジ・重大度つきの指摘が出ます。
- **検証結果（Finding）のレビュー** — 指摘ごとに、
  **確信度**（730 件コーパスと OMG 公式 Pilot Implementation の比較で実測した
  ルール別一致率。未測定のルールは「未測定」と明示し、推定では埋めません）、
  **影響範囲**（その指摘を起点に、エッジ種別ごとの伝播方向に沿って 2 次まで）、
  **修正候補**を表示します。
- **修正候補の適用** — 候補は「適用した場合を確認」で先に**再パース・再検証済みの
  結果**（指摘が何件から何件になるか、適用するとパースできなくなる場合はその旨）を
  見せてから、利用者が確定します。候補は書き換え方が一意に決まるルールにだけ
  付けており、現在 3 ルールが持っています。
- **RAG 連携** — 選択要素に関連する概念を GraphRAG から引く（無料）ほか、
  要求に応じて LLM による説明を生成します（**実課金**。自動では走りません）。

### 図だけ欲しい場合

UI を立てずに SVG を書き出す CLI があります。

```bash
.venv/Scripts/python.exe scripts/sysml_to_svg.py test_sysml.sysml -o out.svg
```

### 描画の完全性について

この Viewer は SysML v2 の記法を完全再現することを目標にしていません。
人と AI がテキストを共同で育てる工程で「認識しなくてはいけないことが図で判断つく」
ところまでを担い、完成後の正式なグラフィカル表現は既存 MBSE ツールへ委ねる、
という役割分担を採っています。合成／共有集約の菱形、シーケンス図、ユースケース図の
専用記法などが未対応であるのはこの方針によるものです（`viewer/COVERAGE.md` §6・§7）。

---

## ログ

- 会話は `--log-dir` に日時入り Markdown ファイルとして保存されます（デフォルト `logs/`）。

---

## 注意事項

- stdio ベースでの自動起動は `fastmcp` のスタンドアロン stdio トランスポートに依存します。環境に `fastmcp` がない、または stdio トランスポートが利用できない場合は、`mcp_servers.json` に `url` を指定してサーバを手動で起動してください（例: `http://localhost:8765`）。
- 起動時に JSON が見つからない/空の場合は `http://localhost:8765` へフォールバックして単一サーバ接続を試みます（HTTP/SSE ベースの接続が標準です）。

---

## トラブルシュート

### 一般的な問題

- エラー例: `stdio接続が選択されましたが、fastmcpが見つかりません。` または `ImportError: cannot import name 'StdioClient'`
  - 対処:
    1. `fastmcp` の Client または stdio トランスポートが利用可能かを確認: `python -c "from fastmcp import Client; print('ok')"`
    2. 利用できない場合は、`fastmcp` の別バージョンを検討するか、次の手順でサーバを手動起動して `mcp_servers.json` に `url` を指定してください。
       - サーバを別端末で起動: `python HybridRAG/mcp_server.py`（または該当プロジェクトの `mcp_server.py`）
       - `mcp_servers.json` の該当サーバ定義を `"url": "http://localhost:8765"` のように書き換える
- エラー例: `Could not infer a valid transport from: tcp://localhost:8765`
  - 原因: 指定した URL スキームがクライアントが期待する形式と一致していません。HTTP または SSE（例: `http://localhost:8765` または `http://localhost:8765/sse`）を使ってください。

### SysML v2 Checker 固有の問題

- エラー例: `ImportError: No module named 'sysml_v2_checker_advanced'`
  - 対処: 作業ディレクトリが正しいか確認してください。`sysml_v2_checker_advanced` フォルダが存在する場所で実行してください。

- エラー例: `ファイル 'xxx.sysml' が見つかりません`
  - 対処: SysML ファイルのパスが正しいか確認してください。相対パスの場合は作業ディレクトリからの相対パスを指定してください。

- エラー例: `パースエラー: 構文エラー`
  - 対処: SysML v2 の構文に準拠しているか確認してください。エラーメッセージを参考に構文を修正してください。

---

## 詳細ドキュメント

- **SysML v2 Checker**: `sysml_v2_mcp_usage.md` - 詳細な API 仕様と使用方法
- **SysML v2 Viewer**: `viewer/COVERAGE.md` - 何を表示し何を表示しないか、
  検証結果に対して何ができるかの完全な一覧
- **チェッカーの精度**: `eval/SYSML_LINTER_REFERENCE_COMPARISON_REPORT.md` -
  OMG 公式 Pilot Implementation との 730 件比較（測定方法と限界を含む）
- **RAG の精度**: `eval/RAG_ACCURACY_REPORT.md` - 検索・回答精度の実測
  （正解ラベルが疎であるという前提つき。数値をそのまま外部へ提示しないこと）
- **テストファイル**: `test_sysml.sysml` - SysML v2 のサンプルファイル

## 開発

### Viewer フロントエンドの検証方針

`viewer/frontend/app.js` に JS のテスト基盤は**入れていない**（P2-G の判断、
2026-09-14）。Viewer は「ローカル開発ツール」という位置づけで、c5（レビュー状態の
サーバー側永続化）を見送ったのと同じ基準。Node のツールチェーン一式を
Python リポジトリへ持ち込み、1,200行超のクラシックスクリプトに export 境界を切る
リファクタリングまで行う価値は、現時点では見合わない。

代わりに**ロジックをバックエンドへ寄せて Python 側でテストする**方針を採った。
影響範囲の走査（エッジ種別ごとの伝播方向・BFS）は `viewer/impact.py` にあり、
`tests/test_viewer_impact.py` が方向づけの表ごと固定している。app.js 側は
`/api/model` が返す `impact` を描画するだけ。

したがって app.js に新しい**ロジック**を足す場合は、まずバックエンドへ置けないかを
検討すること。DOM の描画そのものはブラウザで確認する（`preview_start` →
`javascript_tool` で `textContent` を拾う方式）。

### pre-commit フック（任意だが推奨）

`ruff` と `pytest` をコミット前に自動実行する。**クローンごとに1回**有効化する:

```
git config core.hooksPath scripts/hooks
```

フック本体は `scripts/hooks/pre-commit`（リポジトリで追跡している）。
`.git/hooks` へ直接置くとクローンに付いてこないため、`core.hooksPath` を
リポジトリ内へ向ける方式にしてある。

挙動:

| 対象 | 実行 | 所要 |
|---|---|---|
| 常に | `ruff check .` | 0秒程度 |
| Python を変更したコミットのみ | `pytest -q`（全件） | 約175秒 |

Python を触らないコミット（レポート・ドキュメントのみ）では pytest を省略する。
**「速いサブセット」は用意していない** — 2026-09-14 の実測で、統合テストを除いても
112秒かかり、時間は1,400件超に分散していて短縮できる塊が無かった。恣意的に
一部だけ回すと誤った安心を与えるため、全件か省略かの二択にしている。

逃がし方:

```
git commit --no-verify              # フック全体を飛ばす
PRECOMMIT_SKIP_TESTS=1 git commit   # ruff だけ回す
```

**730件コーパスの回帰チェック（`scripts/recheck_local_only.py`、約4分）は
フックに入れていない。** 実行には `eval/sysml_samples/` と `eval/sysml_results/`
が要るが、どちらも再生成可能な大容量データとして gitignore してあり、
クローン直後には存在しないため。チェッカーの判定に関わる変更をしたときは
手動で回すこと。



```
python -m pip install -e ".[dev]"
python -m pytest -q        # テスト
python -m ruff check .     # Lint
python -m pytest --cov --cov-report=term-missing  # カバレッジ（対象は pyproject.toml [tool.coverage] 参照）
```

`scripts/manual_sysml_mcp_check.py` は SysML v2 Checker MCP サーバへ実際に接続して
動作を目視確認するための手動スクリプトです（pytest の収集対象外）。

---

## ライセンス

MIT License — 詳細は [LICENSE](LICENSE) を参照してください。

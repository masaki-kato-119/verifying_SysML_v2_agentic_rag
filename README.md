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
> Python API（`sysml_v2_checker_advanced.parse_sysml`/`lint_sysml` 等、詳細は同パッケージの
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

Note: NLTK を使うツールを実行する場合は NLTK データを追加でダウンロードしてください:
```
python -m nltk.downloader punkt
```

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
- **テストファイル**: `test_sysml.sysml` - SysML v2 のサンプルファイル

## 開発

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

# SysML v2 Checker MCP Server 使用方法

## 概要

SysML v2 Advanced CheckerをfastmcpでラップしたMCPサーバーです。OpenAI GPTなどのLLMから呼び出して、SysMLファイルの解析、構文チェック、AST生成を行うことができます。

## セットアップ

### 1. 依存関係のインストール

```bash
pip install fastmcp
```

### 2. MCP サーバー設定

`mcp_servers.json` に以下を追加：

```json
{
  "mcpServers": {
    "SysML v2 Checker": {
      "command": "python",
      "args": ["sysml_v2_checker_advanced/mcp_server.py"],
      "cwd": ".",
      "env": {}
    }
  }
}
```

### 3. 起動

```bash
python openai_call_mcp.py --servers-file mcp_servers.json
```

## 利用可能なツール

### 1. `parse_sysml_file`
SysMLファイルをパースしてASTを返します。

**パラメータ:**
- `file_path`: SysMLファイルのパス

**戻り値:**
- `success`: パース成功/失敗
- `error`: エラーメッセージ（失敗時）
- `ast`: 抽象構文木
- `file_path`: ファイルの絶対パス
- `file_size`: ファイルサイズ（バイト）

### 2. `parse_sysml_text`
SysMLテキストを直接パースしてASTを返します。

**パラメータ:**
- `sysml_text`: SysMLのテキスト内容

**戻り値:**
- `success`: パース成功/失敗
- `error`: エラーメッセージ（失敗時）
- `ast`: 抽象構文木
- `text_length`: テキスト長（文字数）

### 3. `lint_sysml_file`
SysMLファイルをリント（構文チェック）して問題を報告します。

**パラメータ:**
- `file_path`: SysMLファイルのパス

**戻り値:**
- `success`: リント成功/失敗
- `error`: エラーメッセージ（失敗時）
- `issues`: 検出された問題のリスト
- `summary`: 問題の集計（total, errors, warnings, info）

### 4. `lint_sysml_text`
SysMLテキストを直接リント（構文チェック）して問題を報告します。

**パラメータ:**
- `sysml_text`: SysMLのテキスト内容

**戻り値:**
- `success`: リント成功/失敗
- `error`: エラーメッセージ（失敗時）
- `issues`: 検出された問題のリスト
- `summary`: 問題の集計

### 5. `get_ast_json`
SysMLファイルのASTをJSON形式で取得します（RAG用）。

**パラメータ:**
- `file_path`: SysMLファイルのパス
- `pretty`: JSON整形するかどうか（デフォルト: true）

**戻り値:**
- `success`: 成功/失敗
- `error`: エラーメッセージ（失敗時）
- `ast_json`: AST JSON文字列

### 6. `analyze_sysml_complete`
SysMLファイルの完全解析（パース + リント + AST JSON）を行います。

**パラメータ:**
- `file_path`: SysMLファイルのパス

**戻り値:**
- `success`: 成功/失敗
- `error`: エラーメッセージ（失敗時）
- `ast`: 抽象構文木
- `issues`: 検出された問題のリスト
- `summary`: 問題の集計
- `ast_json`: AST JSON文字列

### 7. `get_server_info`
MCPサーバーの情報を取得します。

**戻り値:**
- `name`: サーバー名
- `version`: バージョン
- `description`: 説明
- `capabilities`: 機能一覧
- `tools`: 利用可能なツール一覧

## 使用例

### LLMからの呼び出し例

```
>> test_sysml.sysmlファイルを解析して、構文エラーがあるかチェックしてください

>> 以下のSysMLコードに問題がないか確認してください：
package TestPackage {
    part def Vehicle {
        attribute mass : Real;
    }
}

>> SysMLファイルのASTをJSON形式で取得して、RAG用のデータとして使いたいです
```

### プログラムからの直接呼び出し例

```python
from fastmcp import Client

async def analyze_sysml():
    client = Client("sysml_v2_checker_advanced/mcp_server.py")
    async with client:
        # ファイル解析
        result = await client.call_tool("analyze_sysml_complete", {
            "file_path": "my_model.sysml"
        })
        print(result)

asyncio.run(analyze_sysml())
```

## トラブルシューティング

### よくある問題

1. **ImportError**: `sysml_v2_checker_advanced`モジュールが見つからない
   - 作業ディレクトリが正しいか確認
   - Pythonパスに必要なディレクトリが含まれているか確認

2. **ファイルが見つからない**: 指定したSysMLファイルが存在しない
   - ファイルパスが正しいか確認
   - 相対パスの場合は作業ディレクトリからの相対パスを指定

3. **パースエラー**: SysML構文に問題がある
   - SysML v2の構文に準拠しているか確認
   - エラーメッセージを参考に構文を修正

## 技術仕様

- **フレームワーク**: FastMCP 2.14.1
- **トランスポート**: STDIO
- **対応言語**: SysML v2
- **出力形式**: JSON

## 関連ファイル

- `sysml_v2_checker_advanced/mcp_server.py`: MCPサーバー本体
- `mcp_servers.json`: MCPサーバー設定
- `openai_call_mcp.py`: LLM呼び出しクライアント
- `test_sysml.sysml`: テスト用SysMLファイル
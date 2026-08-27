# ANTLR4 文法（SysML v2 パーサー実装）

`sysml_v2_checker_advanced/parser.py`の`parse_sysml()`が使う、SysML v2の
パーサー実装。旧Lark/LALR実装（`grammar.py`/`transformer.py`）は削除済みで、
現在はANTLR4実装のみで動作する。

## なぜ ANTLR4 か（旧Lark実装からの移行理由）

Lark(LALR)では、SysML v2 文法の曖昧性（キーワードと識別子の衝突、オプション接頭辞の
先読み不足など）を回避するために旧`grammar.py`内で場当たり的なワークアラウンドが
積み重なっていた（Reduce/Reduce衝突回避コメントが8箇所）。また `Lark(parser='earley')`
への単純なエンジン切替も検証したが、200行程度のファイルで52秒かかり実用にならなかった。

ANTLR4 は adaptive LL(*) を採用しており、公式の SysML v2 Pilot Implementation
（Eclipse Xtext、内部的に ANTLR ベース）と同系統の解析戦略を素の Python で使える。

## 依存関係の注意（グローバルPython環境を汚染しない）

`antlr4-python3-runtime` は他のライブラリ（例: `hydra-core`/`omegaconf`）が別バージョンに
固定して依存していることがある。マシン全体のグローバル Python 環境に `pip install` すると、
そちらが読み込む生成済みANTLRコード（シリアライズされたATNのバージョン）と不整合を起こし
`Could not deserialize ATN with version ...` のような形で**無関係なパッケージが壊れる**。

**このプロジェクトの依存関係のインストール・実行は、必ずリポジトリ同梱の `venv/` で行うこと**
（`venv/Scripts/python.exe` on Windows）。グローバル環境には入れない。

## 実行時に Java は不要

**コード生成（`.g4` → Python）のときだけ** Java（ANTLR4ツール）が必要。生成された
`generated/*.py` は Git にコミットするので、これを使う側（CI、MCPサーバー、エンドユーザー）は
`pip install antlr4-python3-runtime`（純Python）だけで動く。

文法を変更した開発者だけが、以下の手順で再生成してコミットする。

## 文法を変更したときの再生成手順

### 前提
- Java（JDK 11+）がローカルにあること。このリポジトリでは確認済み（`java -version` → 21）。
- `pip install antlr4-tools`（ANTLR4ツール本体を自動ダウンロードして実行するラッパー）。

### 生成コマンド

`ANTLR4_TOOLS_ANTLR_VERSION` は `pyproject.toml` の `antlr4-python3-runtime` のバージョンと
**必ず一致させる**（ツールと実行時ランタイムのメジャー.マイナーが食い違うと生成コードが動かない）。
現在のピン留め: **4.13.2**。

```bash
cd sysml_v2_checker_advanced/antlr
ANTLR4_TOOLS_ANTLR_VERSION=4.13.2 antlr4 -Dlanguage=Python3 -visitor -no-listener -o generated <文法ファイル>.g4
```

`antlr4` コマンドが PATH にない場合（Windows で pip インストール先が PATH に無いことがある）は、
以下のように直接 Python 経由で呼び出す：

```bash
ANTLR4_TOOLS_ANTLR_VERSION=4.13.2 python -c "import sys,antlr4_tool_runner as r; sys.argv=['antlr4']+sys.argv[1:]; r.tool()" -Dlanguage=Python3 -visitor -no-listener -o generated <文法ファイル>.g4
```

初回はダウンロードした `antlr4-<version>-complete.jar` を `~/.m2/repository/org/antlr/antlr4/` に
キャッシュするので、2回目以降はネットワーク不要。

### 生成後にやること
1. `git status` で `generated/` 配下の差分を確認してコミットする。
2. 対応する Visitor（`sysml_v2_checker_advanced/antlr_transformer.py` 側）を更新する。
3. `tests/test_sysml_antlr_pipeline.py` および `tests/test_sysml_corpus.py` を実行し、
   既存ケースが壊れていないことを確認する。

## 現在のファイル

- `SysMLMin.g4` — SysML v2文法本体。
- `generated/` — 上記から生成された `SysMLMinLexer.py` / `SysMLMinParser.py` / `SysMLMinVisitor.py`。
  **手で編集しない**。文法を変えたら必ず再生成する。

#!/usr/bin/env python3
"""
SysML v2 Checker MCP Server のテストスクリプト
"""

import asyncio
import io
import sys
from pathlib import Path

# Windowsでの文字エンコーディング問題を回避（出力に絵文字を含むため）
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


async def test_sysml_mcp():
    """SysML v2 Checker MCP Serverをテストする"""
    try:
        from fastmcp import Client
        
        # MCPクライアントを作成（STDIOモードでサーバーを起動）
        client = Client("sysml_v2_checker_advanced/mcp_server.py")
        
        async with client:
            print("✅ SysML v2 Checker MCP Server に接続しました")
            
            # 利用可能なツールを取得
            tools = await client.list_tools()
            print(f"\n📚 利用可能なツール ({len(tools)}個):")
            for tool in tools:
                print(f"  - {tool.name}: {tool.description}")
            
            # サーバー情報を取得
            print("\n🔍 サーバー情報を取得中...")
            server_info_result = await client.call_tool("get_server_info", {})
            server_info = server_info_result.data

            print(f"サーバー名: {server_info.get('name', 'N/A')}")
            print(f"バージョン: {server_info.get('version', 'N/A')}")
            print(f"説明: {server_info.get('description', 'N/A')}")
            
            # テスト用SysMLファイルを解析
            test_file = "test_sysml.sysml"
            if Path(test_file).exists():
                print(f"\n🔍 {test_file} を解析中...")
                
                # ファイルをパース
                parse_result_raw = await client.call_tool("parse_sysml_file", {"file_path": test_file})
                parse_result = parse_result_raw.data
                
                if parse_result.get("success"):
                    print("✅ パース成功")
                    print(f"  ファイルサイズ: {parse_result.get('file_size')} bytes")
                else:
                    print(f"❌ パースエラー: {parse_result.get('error')}")
                
                # ファイルをリント
                lint_result_raw = await client.call_tool("lint_sysml_file", {"file_path": test_file})
                lint_result = lint_result_raw.data
                
                if lint_result.get("success"):
                    summary = lint_result.get("summary", {})
                    print(f"✅ リント完了: {summary.get('total', 0)}件の問題")
                    print(f"  エラー: {summary.get('errors', 0)}件")
                    print(f"  警告: {summary.get('warnings', 0)}件")
                    print(f"  情報: {summary.get('info', 0)}件")
                    
                    # 問題がある場合は詳細を表示
                    issues = lint_result.get("issues", [])
                    if issues:
                        print("\n📋 検出された問題:")
                        for issue in issues[:5]:  # 最初の5件のみ表示
                            print(f"  [{issue.get('severity', 'unknown').upper()}] {issue.get('message', 'N/A')}")
                        if len(issues) > 5:
                            print(f"  ... 他 {len(issues) - 5} 件")
                else:
                    print(f"❌ リントエラー: {lint_result.get('error')}")
                
                # 完全解析をテスト
                print(f"\n🔍 {test_file} の完全解析中...")
                complete_result_raw = await client.call_tool("analyze_sysml_complete", {"file_path": test_file})
                complete_result = complete_result_raw.data
                
                if complete_result.get("success"):
                    print("✅ 完全解析成功")
                    ast_json = complete_result.get("ast_json")
                    if ast_json:
                        # AST JSONの最初の部分を表示
                        ast_preview = ast_json[:200] + "..." if len(ast_json) > 200 else ast_json
                        print(f"  AST JSON (preview): {ast_preview}")
                else:
                    print(f"❌ 完全解析エラー: {complete_result.get('error')}")
            else:
                print(f"⚠️  テストファイル {test_file} が見つかりません")
            
            # テキスト直接解析をテスト
            print("\n🔍 SysMLテキストの直接解析をテスト中...")
            test_sysml_text = """
            package SimpleTest {
                part def SimplePart {
                    attribute name : String;
                }
                
                part testPart : SimplePart;
            }
            """
            
            text_result_raw = await client.call_tool("parse_sysml_text", {"sysml_text": test_sysml_text})
            text_result = text_result_raw.data
            
            if text_result.get("success"):
                print("✅ テキスト解析成功")
                print(f"  テキスト長: {text_result.get('text_length')} 文字")
            else:
                print(f"❌ テキスト解析エラー: {text_result.get('error')}")
            
            print("\n🎉 全てのテストが完了しました！")
            
    except ImportError as e:
        print(f"❌ fastmcpのインポートに失敗しました: {e}")
        print("pip install fastmcp でインストールしてください")
    # MCP呼び出し・JSON操作など多様な例外が想定されるため、手動チェックスクリプトとして
    # 原因を問わず捕捉しエラー内容を表示する（意図的な広範キャッチ）
    except Exception as e:  # noqa: BLE001
        print(f"❌ テスト中にエラーが発生しました: {e}")

if __name__ == "__main__":
    asyncio.run(test_sysml_mcp())
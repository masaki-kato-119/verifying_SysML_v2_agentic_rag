"""
SysML v2 Advanced Checker CLI

コマンドラインインターフェース
"""

import argparse
import io
import json
import sys
from pathlib import Path

from .constants import SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING
from .parser import lint_sysml, parse_sysml
from .utils import ast_to_json


def main():
    """コマンドラインインターフェース"""
    # Windowsでの文字エンコーディング問題を回避
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    parser = argparse.ArgumentParser(
        description="SysML v2 Advanced AST-based Linter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  # ファイルをチェック
  python -m sysml_v2_checker_advanced simple_sysml_model.sysml
  
  # JSON出力
  python -m sysml_v2_checker_advanced simple_sysml_model.sysml --json
  
  # ASTのみ出力（RAG用）
  python -m sysml_v2_checker_advanced simple_sysml_model.sysml --ast-only
        """
    )
    parser.add_argument("file", nargs="?", help="SysMLファイルのパス")
    parser.add_argument("--json", action="store_true", help="JSON形式で出力")
    parser.add_argument("--ast-only", action="store_true", help="ASTのみ出力（RAG用）")
    parser.add_argument("--no-lint", action="store_true", help="リンターを実行しない")
    
    args = parser.parse_args()
    
    # ファイル読み込み
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"エラー: ファイル '{args.file}' が見つかりません", file=sys.stderr)
            sys.exit(1)
        text = file_path.read_text(encoding="utf-8")
    else:
        # 標準入力から読み込み
        text = sys.stdin.read()
    
    # パース（SysML v2仕様準拠のSTRICT_GRAMMARを使用）
    ast = parse_sysml(text)
    
    if ast.get("type") == "error":
        print(f"パースエラー: {ast.get('message')}", file=sys.stderr)
        sys.exit(1)
    
    # ASTのみ出力
    if args.ast_only:
        json_output = ast_to_json(ast, pretty=True)
        print(json_output)
        return
    
    # リンター実行
    if not args.no_lint:
        issues = lint_sysml(ast)
        
        if args.json:
            # JSON形式で出力
            # ASTをJSONシリアライズ可能な形式に変換
            import json as json_module
            cleaned_ast = json_module.loads(ast_to_json(ast, pretty=False))
            
            output = {
                "ast": cleaned_ast,
                "issues": [issue.to_dict() for issue in issues],
                "summary": {
                    "total": len(issues),
                    "errors": len([i for i in issues if i.severity == "error"]),
                    "warnings": len([i for i in issues if i.severity == "warning"]),
                    "info": len([i for i in issues if i.severity == "info"])
                }
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            # テキスト形式で出力
            if issues:
                print("リンター結果:")
                print("=" * 60)
                for issue in issues:
                    severity_icon = {
                        SEVERITY_ERROR: "❌",
                        SEVERITY_WARNING: "⚠️",
                        SEVERITY_INFO: "ℹ️"
                    }.get(issue.severity, "•")
                    print(f"{severity_icon} [{issue.severity.upper()}] {issue.message}")
                print("=" * 60)
                error_count = len([i for i in issues if i.severity == SEVERITY_ERROR])
                warning_count = len([i for i in issues if i.severity == SEVERITY_WARNING])
                print(f"合計: {len(issues)}件 (エラー: {error_count}, 警告: {warning_count})")
                
                # エラーがある場合は終了コード1
                if error_count > 0:
                    sys.exit(1)
            else:
                print("✅ 問題なし")
    else:
        # ASTのみ出力
        json_output = ast_to_json(ast, pretty=True)
        print(json_output)


if __name__ == "__main__":
    main()
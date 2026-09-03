#!/usr/bin/env python3
"""SysML v2ファイルから構造図SVGを生成するCLIツール。

viewer/graph_ir.py・view_ir.py・svg_renderer.py単体で完結する、UIに依存しない
パイプライン（SysMLv2_Viewer_実装仕様書.md 5.4節）。デバッグ・回帰確認用途。

使い方:
    python scripts/sysml_to_svg.py <input.sysml> [-o <output.svg>]

出力先省略時は入力ファイルと同じ場所に拡張子だけ .svg に変えて書き出す。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sysml_v2_checker_advanced.semantic_model import build_semantic_model  # noqa: E402
from viewer.graph_ir import build_graph_ir  # noqa: E402
from viewer.view_ir import build_view_ir  # noqa: E402
from viewer.svg_renderer import render_svg  # noqa: E402


def sysml_text_to_svg(text: str) -> str:
    """SysMLテキストからSVG文字列を生成する（パースエラー時は例外を送出）。"""
    ast, semantic_model = build_semantic_model(text)
    if ast.get("type") == "error":
        raise ValueError(f"パースエラー: {ast.get('message')}")
    graph_ir = build_graph_ir(semantic_model)
    view_ir = build_view_ir(graph_ir)
    return render_svg(view_ir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="入力SysMLファイル")
    parser.add_argument("-o", "--output", type=Path, default=None, help="出力SVGファイル（省略時は入力と同じ場所）")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"エラー: ファイル '{args.input}' が見つかりません", file=sys.stderr)
        return 1

    text = args.input.read_text(encoding="utf-8")
    try:
        svg = sysml_text_to_svg(text)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    output_path = args.output or args.input.with_suffix(".svg")
    output_path.write_text(svg, encoding="utf-8")
    print(f"生成しました: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""公式 SysML v2 Pilot Implementation の標準ライブラリ（本物のSysML v2コーパス）に対して
sysml_v2_checker_advanced.parser.parse_sysml/lint_sysml を実行し、パース成功率と
lint診断（特にERROR）を集計する、公式実装とのコンフォーマンス評価（d6_conformance_testing）。

LLMは一切使わない決定的な評価のため、APIコストは発生しない。

前提: 公式リポジトリ（Systems-Modeling/SysML-v2-Pilot-Implementation）を別途
clone しておく必要がある（本リポジトリには含めない。GPLライセンスのXtext/Eclipse
プロジェクトであり、依存関係やビルド成果物を本プロジェクトに混在させないため）。

    git clone --depth 1 https://github.com/Systems-Modeling/SysML-v2-Pilot-Implementation.git

使い方::

    python scripts/run_conformance_eval.py --pilot-repo <cloneしたパス>
    python scripts/run_conformance_eval.py --pilot-repo <path> --show-errors
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_RESULTS_DIR = REPO_ROOT / "eval" / "results"
LIBRARY_SUBDIR = "sysml.library"


def find_library_files(pilot_repo: Path) -> list[Path]:
    library_dir = pilot_repo / LIBRARY_SUBDIR
    if not library_dir.is_dir():
        raise SystemExit(
            f"{library_dir} が見つかりません。--pilot-repo には "
            "Systems-Modeling/SysML-v2-Pilot-Implementation をcloneしたルートを指定してください。"
        )
    return sorted(library_dir.rglob("*.sysml"))


def classify_parse_error(message: str) -> str:
    """ANTLRのエラーメッセージから最初の衝突トークン近辺を抜き出し、原因構文を大まかに分類する。

    d18_bare_block_comment_support: 以前は`message`全文に対して`re.search`していたため、
    1ファイルが複数の独立したエラーを持つ場合、実際には「最初の」エラーが解消されて
    別の不整合に置き換わっていても、メッセージ全体のどこかに偶然同じトークン種別の
    部分文字列が残っていると「変化なし」に誤分類されることがあった
    （CONFORMANCE_REPORT_2026-08-20.md「追記12」参照）。`;`区切りの最初のセグメント
    （実際に最初に発生したエラー）だけを分類対象にすることで、この誤分類を防ぐ。
    """
    first_segment = message.split(";", 1)[0]
    m = re.search(r"mismatched input '([^']*)'", first_segment)
    if m:
        return f"mismatched:'{m.group(1)}'"
    m = re.search(r"extraneous input '([^']*)'", first_segment)
    if m:
        return f"extraneous:'{m.group(1)}'"
    m = re.search(r"token recognition error at: '([^']*)'", first_segment)
    if m:
        return f"unknown-token:'{m.group(1)}'"
    m = re.search(r"no viable alternative at input '([^']*)'", first_segment)
    if m:
        return f"no-viable-alt:'{m.group(1)}'"
    m = re.search(r"missing '([^']*)' at", first_segment)
    if m:
        return f"missing:'{m.group(1)}'"
    return "other"


def collect_exported_type_names(node: dict, names: set[str]) -> None:
    """d23_cross_file_type_resolution_implementation: ASTから「他ファイルから
    importされて型として参照されうる名前」を再帰的に収集する。`linter.py`の
    `_collect_symbols`・`type_system.py`の`_extract_types_from_ast`が型として
    扱うノード種別（`_def`で終わるもの）と、`alias`文の別名を対象とする
    （CONFORMANCE_REPORT_2026-08-20.md「追記15」参照）。
    """
    if not isinstance(node, dict):
        return
    node_type = node.get("type")
    name = node.get("name")
    if name and ((node_type and node_type.endswith("_def")) or node_type == "alias"):
        names.add(name)
    for key in ("children", "params", "attributes"):
        for child in node.get(key, []) or []:
            collect_exported_type_names(child, names)


def build_known_external_types(files: list[Path]) -> set[str]:
    """`sysml.library`全体を事前に一括パースし、各ファイルがエクスポートする
    型名をマージした集合を返す（1回のみ実行）。パースに失敗するファイルは
    単に寄与しないだけで、全体の収集は継続する。"""
    from sysml_v2_checker_advanced.parser import parse_sysml

    names: set[str] = set()
    for path in files:
        text = path.read_text(encoding="utf-8")
        ast = parse_sysml(text)
        if isinstance(ast, dict) and ast.get("type") == "error":
            continue
        collect_exported_type_names(ast, names)
    return names


def run_one(path: Path, repo_root: Path, known_external_types: set[str] | None = None) -> dict:
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    text = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(repo_root))
    ast = parse_sysml(text)
    if isinstance(ast, dict) and ast.get("type") == "error":
        message = ast.get("message", "")
        return {
            "file": rel,
            "status": "parse_error",
            "error_category": classify_parse_error(message),
            "error_message": message,
        }

    try:
        issues = lint_sysml(ast, known_external_types=known_external_types)
    except Exception as exc:  # noqa: BLE001 -- コンフォーマンス調査のため意図的に広く捕捉
        return {"file": rel, "status": "lint_crash", "error_message": f"{type(exc).__name__}: {exc}"}

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    return {
        "file": rel,
        "status": "parsed",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": [i.message for i in errors],
        "warnings": [i.message for i in warnings],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-repo", required=True, help="cloneしたSysML-v2-Pilot-Implementationのルートパス")
    parser.add_argument("--show-errors", action="store_true", help="parse_error/lint errorの詳細を全件表示する")
    parser.add_argument("--output-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()

    pilot_repo = Path(args.pilot_repo).resolve()
    files = find_library_files(pilot_repo)
    if not files:
        raise SystemExit(f"{pilot_repo / LIBRARY_SUBDIR} に .sysml ファイルが見つかりませんでした。")

    # d23_cross_file_type_resolution_implementation: sysml.library全体を事前に
    # 一括パースし、各ファイルがエクスポートする型名をマージした集合を作る
    # （1回のみ実行、以下のファイルごとのループとは独立）。
    known_external_types = build_known_external_types(files)
    print(f"クロスファイル型解決: ライブラリ全体から{len(known_external_types)}件の型名を収集しました。")

    results = [run_one(f, pilot_repo, known_external_types) for f in files]

    parsed = [r for r in results if r["status"] == "parsed"]
    parse_errors = [r for r in results if r["status"] == "parse_error"]
    lint_crashes = [r for r in results if r["status"] == "lint_crash"]
    clean = [r for r in parsed if r["error_count"] == 0]
    with_lint_errors = [r for r in parsed if r["error_count"] > 0]

    print(f"== 公式SysML v2標準ライブラリ（{LIBRARY_SUBDIR}）でのコンフォーマンス評価 ==")
    print(f"総ファイル数: {len(results)}")
    print(f"  パース成功: {len(parsed)} ({len(parsed) * 100 // len(results)}%)")
    print(f"    うちlintエラー0件: {len(clean)}")
    print(f"    うちlintエラーあり（要確認・偽陽性の疑い）: {len(with_lint_errors)}")
    print(f"  パース失敗: {len(parse_errors)} ({len(parse_errors) * 100 // len(results)}%)")
    print(f"  lint中にクラッシュ: {len(lint_crashes)}")

    if parse_errors:
        cat_counts = Counter(r["error_category"] for r in parse_errors)
        print("\n== パース失敗の原因構文別集計（上位20） ==")
        for cat, n in cat_counts.most_common(20):
            print(f"  {n:3d}件  {cat}")

    if with_lint_errors:
        print(f"\n== lintエラーが出たパース成功ファイル（{len(with_lint_errors)}件） ==")
        for r in with_lint_errors:
            print(f"  {r['file']}: {r['error_count']}件")
            if args.show_errors:
                for msg in r["errors"]:
                    print(f"      [error] {msg[:120]}")

    if lint_crashes:
        print(f"\n== lint中にクラッシュしたファイル（{len(lint_crashes)}件） ==")
        for r in lint_crashes:
            print(f"  {r['file']}: {r['error_message']}")

    if args.show_errors and parse_errors:
        print("\n== パース失敗の詳細 ==")
        for r in parse_errors:
            print(f"  {r['file']}")
            print(f"    {r['error_message'][:200]}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = output_dir / f"conformance_{ts}.json"
    out_path.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n結果を保存しました: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""eval/sysml_samples/manifest.json の全サンプルに対し、ローカルの
sysml_v2_checker_advanced（ANTLR4ベース、SysMLMin.g4という最小文法）と、
OMG公式のSysML v2 Pilot Implementation（eval/sysml_reference/reference_driver.py
経由）の両方を実行し、診断（エラー/警告）を比較可能な形式に正規化して
サンプル単位でJSONに永続化する。

LLMは一切使わない決定的な評価。ただし参照実装側はJavaプロセスをサンプルごとに
起動するため、実行時間はサンプル数に比例して長くなる（1ファイルあたり数秒程度）。

診断スキーマ（正規化後、両実装で共通）::

    {"severity": "error" | "warning" | "info", "line": int | None, "message": str}

サンプル単位の結果ファイル（eval/sysml_results/<sha256[:16]>.json）::

    {
      "sample": {"path": ..., "source_repo": ..., "category": ..., "sha256": ...},
      "local": {"parsed": bool, "crashed": bool, "crash_message": str|None,
                "diagnostics": [...], "duration_ms": float},
      "reference": {"parsed": bool, "crashed": bool, "raw_stderr_excerpt": str|None,
                    "diagnostics": [...], "duration_ms": float},
      "agreement": "both_clean" | "both_error" | "local_only_error" |
                   "reference_only_error" | "local_crash" | "reference_crash" |
                   "both_crash"
    }

再開可能: 既に結果ファイルが存在するサンプルはデフォルトでスキップする（--force で再実行）。

使い方::

    python scripts/run_reference_comparison_eval.py --limit 20          # 動作確認用の小規模実行
    python scripts/run_reference_comparison_eval.py                     # 全件実行（要 --yes は無し、時間がかかる旨だけ表示）
    python scripts/run_reference_comparison_eval.py --category official_library
    python scripts/run_reference_comparison_eval.py --force             # 既存結果を無視して再実行
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MANIFEST_PATH = REPO_ROOT / "eval" / "sysml_samples" / "manifest.json"
RESULTS_DIR = REPO_ROOT / "eval" / "sysml_results"
REFERENCE_DRIVER_PATH = REPO_ROOT / "eval" / "sysml_reference" / "reference_driver.py"

_LINE_RE = re.compile(r"\(line (\d+), column \d+\)")


def _load_reference_driver():
    """reference_driver.py はパッケージ外の単体スクリプトとして書かれているため、
    ファイルパスから直接importする（sys.path汚染を避けるためimportlibを使う）。"""
    spec = importlib.util.spec_from_file_location("sysml_reference_driver", REFERENCE_DRIVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_manifest() -> list[dict]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data["entries"]


def run_local_check(text: str) -> dict:
    """ローカルlinterを実行し、参照実装ドライバと同じ形の辞書に正規化する。"""
    from sysml_v2_checker_advanced.parser import lint_sysml, parse_sysml

    t0 = time.perf_counter()
    try:
        ast = parse_sysml(text)
    except Exception as exc:  # noqa: BLE001 -- 評価ハーネスなのでパーサのクラッシュも記録対象
        return {
            "parsed": False,
            "crashed": True,
            "crash_message": f"parse_sysml crashed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            "diagnostics": [],
            "duration_ms": (time.perf_counter() - t0) * 1000,
        }

    if isinstance(ast, dict) and ast.get("type") == "error":
        # 構文エラー。行番号はメッセージ中に "(line X, column Y)" として埋め込まれている
        # ことが多いので、比較しやすいよう抽出しておく（見つからなければNone）。
        msg = ast.get("message", "parse error")
        diagnostics = []
        for segment in msg.split("; "):
            line = None
            m = _LINE_RE.search(segment)
            if m:
                line = int(m.group(1))
            diagnostics.append({"severity": "error", "line": line, "message": segment})
        return {
            "parsed": False,
            "crashed": False,
            "crash_message": None,
            "diagnostics": diagnostics,
            "duration_ms": (time.perf_counter() - t0) * 1000,
        }

    try:
        issues = lint_sysml(ast)
    except Exception as exc:  # noqa: BLE001 -- lintのクラッシュそのものが評価対象
        return {
            "parsed": True,
            "crashed": True,
            "crash_message": f"lint_sysml crashed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            "diagnostics": [],
            "duration_ms": (time.perf_counter() - t0) * 1000,
        }

    diagnostics = [
        {"severity": (i.severity or "").lower(), "line": i.line, "message": i.message} for i in issues
    ]
    return {
        "parsed": True,
        "crashed": False,
        "crash_message": None,
        "diagnostics": diagnostics,
        "duration_ms": (time.perf_counter() - t0) * 1000,
    }


def run_reference_check_normalized(reference_module, text: str) -> dict:
    t0 = time.perf_counter()
    result = reference_module.run_reference_check(text)
    duration_ms = (time.perf_counter() - t0) * 1000
    diagnostics = [
        {"severity": (d.get("severity") or "").lower(), "line": d.get("line"), "message": d.get("message") or ""}
        for d in result.get("diagnostics", [])
    ]
    return {
        "parsed": not result.get("crashed", False),
        "crashed": bool(result.get("crashed", False)),
        "raw_stderr_excerpt": (result.get("raw_stderr") or "")[-2000:] or None,
        "diagnostics": diagnostics,
        "duration_ms": duration_ms,
    }


def classify_agreement(local: dict, reference: dict) -> str:
    if local["crashed"] and reference["crashed"]:
        return "both_crash"
    if local["crashed"]:
        return "local_crash"
    if reference["crashed"]:
        return "reference_crash"
    local_has_error = any(d["severity"] == "error" for d in local["diagnostics"])
    ref_has_error = any(d["severity"] == "error" for d in reference["diagnostics"])
    if local_has_error and ref_has_error:
        return "both_error"
    if local_has_error and not ref_has_error:
        return "local_only_error"
    if ref_has_error and not local_has_error:
        return "reference_only_error"
    return "both_clean"


def result_path(entry: dict) -> Path:
    return RESULTS_DIR / f"{entry['sha256'][:16]}.json"


def process_one(entry: dict, reference_module, timeout: float) -> tuple[dict, dict | None, str | None]:
    """1サンプルを処理する。戻り値は (entry, record_or_None, error_message_or_None)。
    ThreadPoolExecutorのワーカーから呼ばれるため、共有状態を書き換えない。"""
    file_path = REPO_ROOT / entry["path"]
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return entry, None, f"読み込み失敗: {exc}"

    local = run_local_check(text)
    try:
        reference = run_reference_check_normalized(reference_module, text)
    except reference_module.ReferenceSetupError as exc:
        return entry, None, f"参照実装セットアップエラー: {exc}"

    agreement = classify_agreement(local, reference)
    record = {
        "sample": {
            "path": entry["path"],
            "source_repo": entry["source_repo"],
            "category": entry["category"],
            "sha256": entry["sha256"],
        },
        "local": local,
        "reference": reference,
        "agreement": agreement,
    }
    return entry, record, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="先頭N件のみ処理する（動作確認用）")
    parser.add_argument("--category", default=None, help="manifestのcategoryで絞り込む")
    parser.add_argument("--force", action="store_true", help="既存の結果ファイルがあっても再実行する")
    parser.add_argument("--timeout", type=float, default=45.0, help="参照実装1ファイルあたりのタイムアウト秒数")
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="並列実行するJavaプロセス数（参照実装がボトルネックなので既定6で並列化。"
        "マシンのメモリに応じて調整可）",
    )
    args = parser.parse_args()

    reference_module = _load_reference_driver()

    entries = load_manifest()
    if args.category:
        entries = [e for e in entries if e["category"] == args.category]
    if args.limit:
        entries = entries[: args.limit]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    todo = []
    agreement_counter: Counter[str] = Counter()
    skipped = 0
    for entry in entries:
        out_path = result_path(entry)
        if out_path.exists() and not args.force:
            skipped += 1
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            agreement_counter[existing["agreement"]] += 1
            continue
        todo.append(entry)

    print(f"対象サンプル数: {len(entries)}（うち新規処理対象 {len(todo)}件、スキップ {skipped}件、並列数 {args.workers}）")
    processed = 0
    errors = 0
    t_start = time.time()

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_one, entry, reference_module, args.timeout): entry for entry in todo
        }
        for future in as_completed(futures):
            entry = futures[future]
            _, record, error = future.result()
            if error is not None:
                errors += 1
                print(f"  SKIP ({error}): {entry['path']}")
                continue

            agreement_counter[record["agreement"]] += 1
            processed += 1
            result_path(entry).write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            if processed % 10 == 0 or processed == len(todo):
                elapsed = time.time() - t_start
                rate = processed / elapsed if elapsed > 0 else 0
                print(
                    f"  [{processed}/{len(todo)}] "
                    f"({rate:.2f}件/秒, 経過{elapsed:.0f}秒) 直近: {record['agreement']} — {entry['path']}"
                )

    print("\n== 集計（このスクリプト実行分のみ、--forceなしなら既存分も含む累積） ==")
    total = sum(agreement_counter.values())
    for label, count in agreement_counter.most_common():
        pct = count * 100 // total if total else 0
        print(f"  {label:<22} {count:5d}件 ({pct}%)")
    print(f"\n合計: {total}件（新規処理 {processed}件 / スキップ {skipped}件 / 読み込み等エラー {errors}件）")
    print(f"サンプル毎の結果: {RESULTS_DIR}/<sha256[:16]>.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

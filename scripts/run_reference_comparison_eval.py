"""eval/sysml_samples/manifest.json の全サンプルに対し、ローカルの
sysml_v2_checker_advanced（ANTLR4ベース、SysMLMin.g4という最小文法）と、
OMG公式のSysML v2 Pilot Implementation（eval/sysml_reference/reference_driver.py
経由）の両方を実行し、診断（エラー/警告）を比較可能な形式に正規化して
サンプル単位でJSONに永続化する。

LLMは一切使わない決定的な評価。

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
    python scripts/run_reference_comparison_eval.py                     # 全件実行（batchモード。730件で約23分）
    python scripts/run_reference_comparison_eval.py --category official_library
    python scripts/run_reference_comparison_eval.py --force             # 既存結果を無視して再実行
    python scripts/run_reference_comparison_eval.py --mode serial       # 従来方式（1件1JVM）へ戻す

実行モード
----------
既定は ``--mode batch``。``RefDriver`` を ``--batch`` で常駐させ、標準入力へ
サンプルのパスを1行ずつ送って1行1JSONで受け取る。参照実装のライブラリロード
（1件あたり13秒前後を占める）が1回で済むため、730件が2時間強から**約23分**になる。

**バッチモードは並列化ではなく逐次化である**（JVMは1個、完全逐次）。下の
「並列実行の危険性」で書いたライブラリロード障害は複数JVMの同時実行が原因なので、
バッチ化はその問題を増やす方向ではない。

**2026-09-05、全730件でバッチモードと逐次モードの診断が完全に一致することを
確認済み**（crashedの一致と、診断の (severity, line, message) 多重集合の一致。
不一致0件）。検証は ``scripts/compare_reference_runs_batch_vs_serial.py`` で再現できる。
``SysMLInteractive`` はJupyterカーネルのセッションAPIで連続する ``process()`` は
同一セッションのセル相当なので、**参照実装のjarやサンプルコーパスを入れ替えたら、
batchを既定のまま使う前にこの検証をやり直すこと**（RefDriver側はファイルごとに
``removeResource()`` を呼んで前のリソースを外しているが、それで十分かは実測でしか
分からない）。

並列実行の危険性（2026-09-04に実測。既定を --workers 6 から 1 に変えた理由）
--------------------------------------------------------------------------
複数のJVMが同時に ``eval/sysml_reference/sysml.library`` を読むと、参照実装の
``si.loadLibrary()`` が標準ライブラリの一部を読み込めないことがある。完全に失敗すれば
``crashed`` として検出できるが、**部分的にしか失敗しないと診断0件のまま success として
返る**。これは「本当にクリーンなファイル」と区別が付かないため、``local_only_error`` を
不当に増やし ``both_error`` を減らす形で集計結果を静かに壊す。

実測: ``--workers 4`` で347件処理した時点で ``reference_crash`` が81件（23%）。
2026-08-28のベースラインでは 5件/730件（0.7%）だった。並列実行中に不正な入力
``package P { part def }`` を流すと、エラー0件が返ることが再現する。

対策として2つ入れてある:

1. **canary** — 実行開始前、``--canary-interval`` 件ごと、そして実行終了時に、
   参照実装へ既知の不正スニペットを流して error 診断が返ることを確認する。
   結果はcanaryが通るまでディスクへ書かず、落ちたら直前のcanary以降の分を
   まとめて破棄して中断する（書き出されていない分は未処理のまま残るので、
   ``--force`` 無しの再実行で続きから埋められる）。
2. ``reference_driver.py`` 側で、stderr にライブラリロード失敗のマーカーが出ていたら
   診断が空でなくても ``crashed`` として扱う。

したがって ``--workers`` を1より上げても壊れた結果が保存されることは無いが、
canaryで中断して進まなくなるだけなので、上げる意味は薄い。``--workers`` は
``--mode serial`` のときだけ効く。

高速化はバッチモード（上記）で行った。canaryはバッチ側にも入っている
（``ReferenceBatch.run_canary()``）ので、常駐JVMが途中で検証をやめた場合も
同じように検出して中断する。
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


def run_reference_check_normalized(reference_module, text: str, timeout: float) -> dict:
    t0 = time.perf_counter()
    # 2026-09-04: timeoutを渡し忘れており、--timeoutを何秒に指定してもドライバ側の
    # 既定30秒が使われていた（process_oneは受け取っていたが中継していなかった）。
    result = reference_module.run_reference_check(text, timeout=timeout)
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
        reference = run_reference_check_normalized(reference_module, text, timeout)
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


def process_one_batched(entry: dict, batch, reference_module) -> tuple[dict, dict | None, str | None]:
    """process_one のバッチ版。参照実装の呼び出しだけを常駐JVMへ差し替える。

    ローカル側は変わらない。参照実装へはテキストではなくファイルパスを渡す
    （常駐側が読む）ので、一時ファイルの作成も要らない。
    """
    file_path = REPO_ROOT / entry["path"]
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return entry, None, f"読み込み失敗: {exc}"

    local = run_local_check(text)

    t0 = time.perf_counter()
    result = batch.check_file(str(file_path))
    duration_ms = (time.perf_counter() - t0) * 1000
    reference = {
        "parsed": not result.get("crashed", False),
        "crashed": bool(result.get("crashed", False)),
        "raw_stderr_excerpt": (result.get("raw_stderr") or "")[-2000:] or None,
        "diagnostics": [
            {
                "severity": (d.get("severity") or "").lower(),
                "line": d.get("line"),
                "message": d.get("message") or "",
            }
            for d in result.get("diagnostics", [])
        ],
        "duration_ms": duration_ms,
    }

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
        default=1,
        help="並列実行するJavaプロセス数（既定1＝逐次。2026-09-04に並列実行が結果を"
        "静かに汚染することが判明したため既定を6から1へ変更した。docstringの"
        "「並列実行の危険性」を読んだうえでのみ上げること）",
    )
    parser.add_argument(
        "--canary-interval",
        type=int,
        default=25,
        help="このサンプル数ごとに参照実装の健全性チェック（canary）を挟む。0で無効化（非推奨）",
    )
    parser.add_argument(
        "--mode",
        choices=("batch", "serial"),
        default="batch",
        help="batch（既定）は常駐JVM1個へパスを送り続ける。serialはサンプル1件ごとに"
        "JVMを起動する従来方式。2026-09-05に全730件で両者の診断が完全一致することを"
        "確認済み（scripts/compare_reference_runs_batch_vs_serial.py）。"
        "参照実装のjarやサンプルを入れ替えたら、batchを使う前に再検証すること",
    )
    args = parser.parse_args()

    reference_module = _load_reference_driver()

    # 実行開始前の健全性チェック。参照実装が「不正な入力にエラーを返す」ことを
    # 確認できないうちは1件も処理しない（汚染された結果を書かないため）。
    # batchモードでは常駐JVM側でcanaryを回す必要があるので、後段で行う。
    if args.mode == "serial":
        ok, detail = reference_module.run_canary(timeout=max(args.timeout, 60.0))
        print(f"canary (実行前): {detail}")
        if not ok:
            print(
                "参照実装が健全でないため中断した。他のJavaプロセスが動いていないか確認し、"
                "--workers を下げて再実行すること。"
            )
            return 2

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

    mode_label = "batch（常駐JVM1個・逐次）" if args.mode == "batch" else f"serial（並列数 {args.workers}）"
    print(f"対象サンプル数: {len(entries)}（うち新規処理対象 {len(todo)}件、スキップ {skipped}件、{mode_label}）")
    processed = 0
    errors = 0
    t_start = time.time()

    from concurrent.futures import ThreadPoolExecutor, as_completed

    # canaryが通るまで結果をディスクへ書かない。canaryが落ちた時点で、直前のcanary
    # 以降に得た結果は「参照実装が健全だった」保証が無いため、まとめて破棄する。
    pending: list[tuple[dict, dict]] = []
    canary_failed = False

    def flush_pending() -> None:
        for pending_entry, pending_record in pending:
            result_path(pending_entry).write_text(
                json.dumps(pending_record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        pending.clear()

    def discard_pending() -> int:
        """破棄した件数を集計からも差し引く（書いていないものを処理済みに数えない）。"""
        for _, pending_record in pending:
            agreement_counter[pending_record["agreement"]] -= 1
            if agreement_counter[pending_record["agreement"]] <= 0:
                del agreement_counter[pending_record["agreement"]]
        discarded = len(pending)
        pending.clear()
        return discarded

    def note_progress(record: dict, entry: dict) -> None:
        if processed % 10 == 0 or processed == len(todo):
            elapsed = time.time() - t_start
            rate = processed / elapsed if elapsed > 0 else 0
            print(
                f"  [{processed}/{len(todo)}] "
                f"({rate:.2f}件/秒, 経過{elapsed:.0f}秒) 直近: {record['agreement']} — {entry['path']}"
            )

    if args.mode == "batch":
        # 常駐JVM1個へパスを送り続ける。並列化ではなく逐次化であることに注意
        # （複数JVMを同時に走らせると、docstringの「並列実行の危険性」にある
        # ライブラリロード障害が再発する）。
        with reference_module.ReferenceBatch(timeout=max(args.timeout, 300.0)) as batch:
            ok, detail = batch.run_canary()
            print(f"canary (実行前): {detail}")
            if not ok:
                print("参照実装が健全でないため中断した。他のJavaプロセスが動いていないか確認すること。")
                return 2

            for entry in todo:
                _, record, error = process_one_batched(entry, batch, reference_module)
                if error is not None:
                    errors += 1
                    print(f"  SKIP ({error}): {entry['path']}")
                    continue

                agreement_counter[record["agreement"]] += 1
                processed += 1
                pending.append((entry, record))

                if args.canary_interval and processed % args.canary_interval == 0:
                    ok, detail = batch.run_canary()
                    if not ok:
                        print(f"  canary NG ({detail})")
                        discarded = discard_pending()
                        processed -= discarded
                        print(
                            f"  直前のcanary以降の{discarded}件を破棄して中断する"
                            "（参照実装が健全だった保証が無いため）"
                        )
                        canary_failed = True
                        break
                    flush_pending()
                    print(f"  canary ok [{processed}/{len(todo)}]")

                note_progress(record, entry)

            if not canary_failed and pending:
                ok, detail = batch.run_canary()
                print(f"canary (実行後): {detail}")
                if ok:
                    flush_pending()
                else:
                    discarded = discard_pending()
                    processed -= discarded
                    print(f"最後の{discarded}件を破棄した（参照実装が健全だった保証が無いため）")
                    canary_failed = True
    else:
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
            pending.append((entry, record))

            if args.canary_interval and processed % args.canary_interval == 0:
                ok, detail = reference_module.run_canary(timeout=max(args.timeout, 60.0))
                if not ok:
                    print(f"  canary NG ({detail})")
                    discarded = discard_pending()
                    processed -= discarded
                    print(
                        f"  直前のcanary以降の{discarded}件を破棄して中断する"
                        "（参照実装が健全だった保証が無いため）"
                    )
                    canary_failed = True
                    for pending_future in futures:
                        pending_future.cancel()
                    break
                flush_pending()
                print(f"  canary ok [{processed}/{len(todo)}]")

            note_progress(record, entry)

    # 最後の部分バッチもcanaryで裏付けてから書き出す（serialパス用。batchは
    # 常駐JVMを閉じる前に上で済ませてある）。
    if args.mode == "serial" and not canary_failed and pending:
        ok, detail = reference_module.run_canary(timeout=max(args.timeout, 60.0))
        print(f"canary (実行後): {detail}")
        if ok:
            flush_pending()
        else:
            discarded = discard_pending()
            processed -= discarded
            print(f"最後の{discarded}件を破棄した（参照実装が健全だった保証が無いため）")
            canary_failed = True

    print("\n== 集計（このスクリプト実行分のみ、--forceなしなら既存分も含む累積） ==")
    total = sum(agreement_counter.values())
    for label, count in agreement_counter.most_common():
        pct = count * 100 // total if total else 0
        print(f"  {label:<22} {count:5d}件 ({pct}%)")
    print(f"\n合計: {total}件（新規処理 {processed}件 / スキップ {skipped}件 / 読み込み等エラー {errors}件）")
    print(f"サンプル毎の結果: {RESULTS_DIR}/<sha256[:16]>.json")

    if canary_failed:
        print(
            "\ncanaryが落ちたため実行を打ち切った。書き出されていない分は未処理として残るので、"
            "他のJavaプロセスを止めてから --force 無しで再実行すれば続きから埋められる。"
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""RefDriver のバッチモードが、逐次モード（1ファイル1JVM）と同じ診断を返すかを
全サンプルで突き合わせる。

## なぜこの検証が要るのか

バッチモードは `SysMLInteractive` の1インスタンスで連続して `process()` を呼ぶ。
これは Jupyter カーネルの対話セッションAPIであり、連続する `process()` は
「1つのセッションの各セル」に相当する。したがって前のファイルで宣言した名前が
次のファイルから見えてしまう恐れがあり、そうなると
**「他ファイル依存で未解決になるはずの参照が解決できてしまう」** 形で
`reference_only_error` が不当に減る。しかも診断結果としては正常に見えるため、
気づかないまま集計が壊れる（2026-09-04に実際に踏んだ、並列実行時の
「静かに空を返す」障害と同種の失敗モード）。

RefDriver はファイルごとに `si.removeResource()` を呼んで前のリソースを外して
いるが、それで十分かどうかは実測でしか分からない。**このスクリプトが通るまで
バッチモードを既定にしてはいけない。**

## 比較の対象

`eval/sysml_results/<sha>.json` に保存されている `reference` フィールド
（＝逐次モードで得た結果）を基準に、同じサンプルをバッチモードで流し直して
突き合わせる。比較するのは参照実装側だけで、ローカル側は見ない
（ローカルは文法・lintの変更で当然変わるため、ここでは無関係）。

一致の判定は「crashed が同じ」かつ「診断の (severity, line, message) の
多重集合が同じ」。順序の違いは許容する。

## 使い方

    python scripts/compare_reference_runs_batch_vs_serial.py
    python scripts/compare_reference_runs_batch_vs_serial.py --limit 50
    python scripts/compare_reference_runs_batch_vs_serial.py --json out.json

差分が1件でもあれば exit 1 を返す。
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import sys
import time
from pathlib import Path

# 進捗表示を出力のリダイレクト先に依存させない（2026-09-24）。
# Windowsではパイプへ書くときstdoutがロケールのcp932になり、出力文字列に
# 含まれるem dash等をエンコードできずに**実行そのものが落ちる**。
# 730件を23分かけて回すスクリプトが最初の進捗行で死ぬうえ、パイプ経由だと
# 終了コードがtail側のものになって成功と見分けが付かない（実際に踏んだ）。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RESULTS_DIR = REPO_ROOT / "eval" / "sysml_results"
REFERENCE_DRIVER_PATH = REPO_ROOT / "eval" / "sysml_reference" / "reference_driver.py"


def _load_reference_driver():
    spec = importlib.util.spec_from_file_location("sysml_reference_driver", REFERENCE_DRIVER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fingerprint(diagnostics) -> collections.Counter:
    """診断の多重集合。順序差は無視し、内容の差だけを見る。"""
    return collections.Counter(
        (
            (d.get("severity") or "").lower(),
            d.get("line"),
            (d.get("message") or ""),
        )
        for d in diagnostics
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR,
                        help="逐次モードの結果ディレクトリ（既定 eval/sysml_results）")
    parser.add_argument("--limit", type=int, default=None, help="先頭N件のみ（動作確認用）")
    parser.add_argument(
        "--fresh-serial", action="store_true",
        help="保存済みの結果を使わず、逐次モードを**その場で**走らせて比べる。"
        "参照実装のjarを入れ替えた直後はこちらを使うこと――保存済みの結果は"
        "古いjarで取ったものなので、そのまま比べると『バッチと逐次の差』と"
        "『バージョンの差』が混ざって判定できない。1件あたり13秒前後かかるので"
        "--limit と併用する",
    )
    parser.add_argument("--canary-interval", type=int, default=50,
                        help="このサンプル数ごとにバッチ側のcanaryを挟む。0で無効化（非推奨）")
    parser.add_argument("--json", type=Path, help="差分をJSONで書き出す")
    args = parser.parse_args()

    files = sorted(args.results_dir.glob("*.json"))
    if args.limit:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"{args.results_dir} に結果JSONがありません")

    reference_module = _load_reference_driver()

    matches = 0
    mismatches: list[dict] = []
    missing = 0
    started = time.time()

    with reference_module.ReferenceBatch() as batch:
        ok, detail = batch.run_canary()
        print(f"canary (実行前): {detail}")
        if not ok:
            print("バッチ側の参照実装が健全でないため中断した。")
            return 2

        for index, path in enumerate(files, 1):
            record = json.loads(path.read_text(encoding="utf-8"))
            sample = record["sample"]
            source = REPO_ROOT / sample["path"]
            if not source.exists():
                missing += 1
                continue

            if args.fresh_serial:
                # 現在のjarで逐次モードを走らせる（JVMを1件ごとに起こすので遅い）。
                serial = reference_module.run_reference_check(
                    source.read_text(encoding="utf-8", errors="replace")
                )
            else:
                serial = record["reference"]
            fresh = batch.check_file(str(source))

            same_crashed = bool(serial.get("crashed")) == bool(fresh.get("crashed"))
            serial_fp = _fingerprint(serial.get("diagnostics", []))
            fresh_fp = _fingerprint(fresh.get("diagnostics", []))

            if same_crashed and serial_fp == fresh_fp:
                matches += 1
            else:
                only_serial = serial_fp - fresh_fp
                only_batch = fresh_fp - serial_fp
                mismatches.append({
                    "path": sample["path"],
                    "category": sample.get("category", "?"),
                    "serial_crashed": bool(serial.get("crashed")),
                    "batch_crashed": bool(fresh.get("crashed")),
                    "serial_diagnostics": sum(serial_fp.values()),
                    "batch_diagnostics": sum(fresh_fp.values()),
                    "only_in_serial": [list(k) for k in list(only_serial)[:5]],
                    "only_in_batch": [list(k) for k in list(only_batch)[:5]],
                })

            if args.canary_interval and index % args.canary_interval == 0:
                ok, detail = batch.run_canary()
                if not ok:
                    print(f"  canary NG ({detail}) — {index}件目で中断")
                    return 2
                elapsed = time.time() - started
                print(f"  [{index}/{len(files)}] 一致{matches} 不一致{len(mismatches)} "
                      f"({elapsed:.0f}秒, {index / elapsed:.1f}件/秒) canary ok")

        ok, detail = batch.run_canary()
        print(f"canary (実行後): {detail}")
        if not ok:
            print("実行後のcanaryが落ちたため、上の結果は信用できない。")
            return 2

    total = matches + len(mismatches)
    elapsed = time.time() - started
    print(f"\n== 逐次モードとの突き合わせ: {total}件"
          f"（サンプル欠落 {missing}件を除外、{elapsed:.0f}秒）==")
    print(f"  一致   : {matches}")
    print(f"  不一致 : {len(mismatches)}")

    if mismatches:
        print("\n不一致の詳細（先頭20件）:")
        for item in mismatches[:20]:
            print(f"  [{item['category']}] {item['path']}")
            print(f"      crashed 逐次={item['serial_crashed']} バッチ={item['batch_crashed']}"
                  f" / 診断数 逐次={item['serial_diagnostics']} バッチ={item['batch_diagnostics']}")
            for sev, line, msg in item["only_in_serial"][:2]:
                print(f"      逐次のみ: [{sev}] line={line} {msg[:70]}")
            for sev, line, msg in item["only_in_batch"][:2]:
                print(f"      バッチのみ: [{sev}] line={line} {msg[:70]}")

    if args.json:
        args.json.write_text(json.dumps({
            "total": total,
            "matches": matches,
            "mismatch_count": len(mismatches),
            "elapsed_seconds": elapsed,
            "mismatches": mismatches,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSONを書き出した: {args.json}")

    if mismatches:
        print("\nバッチモードは逐次モードと一致しない。既定にしてはいけない。")
        return 1

    print("\nバッチモードは逐次モードと完全に一致した。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

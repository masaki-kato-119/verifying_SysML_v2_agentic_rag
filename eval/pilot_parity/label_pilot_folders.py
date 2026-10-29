"""フォルダ単位のコーパス（build_folders.py）の各ファイルに、Pilot（オラクル）の正解ラベルを付ける。

フォルダのファイルを一緒に読み込んで検証する（sysml-mcp-server の SysMLService.validate_files。MCP の
validate_sysml に directory を渡したときと同じ）。そのサーバの venv の Python で実行する:

    C:\\test\\SysMLv2_pilot\\sysml-mcp-server\\.venv\\Scripts\\python.exe -I eval/pilot_parity/label_pilot_folders.py

出力: folders/labels/pilot/<unit id>.json = {id, pilot_version, hidden, unindexed, issues: [...]}
（issues の形は label_pilot.py と同じ。hidden / unindexed は、そのファイルを Pilot がほかのファイルから
見えなくしたか。最上位のパッケージ名が標準ライブラリと重なる・構文エラーの回復で重なった）
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default="folders", help="コーパスの置き場所（folders / heldout2）")
    ap.add_argument("--out", type=Path, default=None, help="既定は <root>/labels/pilot")
    ap.add_argument("--force", action="store_true", help="ラベルがあるフォルダも付け直す")
    args = ap.parse_args()
    corpus = HERE / args.root / "corpus"
    args.out = args.out or HERE / args.root / "labels" / "pilot"

    from sysml_mcp.backend import Config, DaemonError, SysMLDaemon, SysMLFile, SysMLService

    config = Config.from_env()
    version = Path(config.jar).name if hasattr(config, "jar") else "unknown"
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    by_folder: dict[str, list[dict]] = {}
    for entry in manifest:
        by_folder.setdefault(entry["folder"], []).append(entry)
    args.out.mkdir(parents=True, exist_ok=True)
    daemon = SysMLDaemon(config)
    service = SysMLService(daemon)
    done = 0
    failed: list[str] = []
    try:
        for n, (folder, entries) in enumerate(sorted(by_folder.items()), 1):
            if not args.force and all((args.out / f"{e['id']}.json").exists() for e in entries):
                continue
            directory = corpus / "folders" / folder
            files = [SysMLFile(path=p.name, text=p.read_text(encoding="utf-8"))
                     for p in sorted(directory.glob("*.sysml"))]
            try:
                r = service.validate_files(files, targets=[e["file"] for e in entries])
            except DaemonError as error:
                # 時間切れ（大きなフォルダ）などは飛ばして記録する。ラベルの無い unit は compare.py が数えない
                print(f"skipped {folder}: {str(error)[:80]}", flush=True)
                failed.append(folder)
                continue
            results = {f["path"]: f for f in r["files"]}
            for e in entries:
                fr = results.get(e["file"], {"issues": []})
                issues = [{k: i.get(k) for k in ("severity", "line", "column", "syntax_error", "message")}
                          for i in fr.get("issues", [])]
                (args.out / f"{e['id']}.json").write_text(json.dumps({
                    "id": e["id"], "pilot_version": version,
                    "hidden": e["file"] in r.get("hiddenFiles", []),
                    "unindexed": e["file"] in r.get("unindexedFiles", []),
                    "issues": issues}, ensure_ascii=False), encoding="utf-8")
            done += 1
            if n % 20 == 0:
                print(f"{n}/{len(by_folder)}", flush=True)
    finally:
        daemon.close()
    if failed:
        (args.out.parent / "pilot_failed.json").write_text(json.dumps(failed, ensure_ascii=False, indent=1),
                                                          encoding="utf-8")
    print(f"labeled {done} folders ({len(by_folder)} in corpus, {len(failed)} skipped) -> {args.out}")


if __name__ == "__main__":
    main()

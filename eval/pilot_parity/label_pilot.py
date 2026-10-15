"""コーパスの各 unit を Pilot（オラクル）で検証し、正解ラベルを保存する。

sysml-mcp-server（C:\\test\\SysMLv2_pilot\\sysml-mcp-server）の SysMLService を使う。
そのサーバの venv の Python で実行すること:

    C:\\test\\SysMLv2_pilot\\sysml-mcp-server\\.venv\\Scripts\\python.exe -I eval/pilot_parity/label_pilot.py

出力: labels/pilot/<id>.json = {id, pilot_version, issues: [{severity, line, column, syntax_error, message}]}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, default=HERE / "corpus")
    ap.add_argument("--out", type=Path, default=HERE / "labels" / "pilot")
    ap.add_argument("--force", action="store_true",
                    help="ラベルがある unit も付け直す（既定は、無い unit だけ。unit の中身が変わったら付ける）")
    args = ap.parse_args()

    from sysml_mcp.backend import Config, SysMLDaemon, SysMLService

    config = Config.from_env()
    version = Path(config.jar).name if hasattr(config, "jar") else "unknown"
    manifest = json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    daemon = SysMLDaemon(config)
    service = SysMLService(daemon)
    try:
        for n, entry in enumerate(manifest, 1):
            if not args.force and (args.out / f"{entry['id']}.json").exists():
                continue
            text = (args.corpus / "units" / f"{entry['id']}.sysml").read_text(encoding="utf-8")
            r = service.validate(text)
            issues = [{k: i.get(k) for k in ("severity", "line", "column", "syntax_error", "message")}
                      for i in r.get("issues", [])]
            (args.out / f"{entry['id']}.json").write_text(
                json.dumps({"id": entry["id"], "pilot_version": version, "issues": issues}, ensure_ascii=False),
                encoding="utf-8")
            if n % 50 == 0:
                print(f"{n}/{len(manifest)}", flush=True)
    finally:
        daemon.close()
    print(f"labeled {len(manifest)} units -> {args.out}")


if __name__ == "__main__":
    main()

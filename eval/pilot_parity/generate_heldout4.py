"""4 つ目の held-out: Claude 以外の LLM（OpenAI）に、研究に使っていない題材で SysML v2 モデルを 1 回で書かせる。

2 つ目の held-out（Sonnet / Haiku、2026-10-23）と同じ条件にする: 研究の文脈を渡さない、検証ツールを使わせない、
1 回の応答の初稿をそのまま使う。題材は C:\\test\\sysml_models\\eval\\heldout4\\SPECS.md の 5 つ。

出力: C:\\test\\sysml_models\\eval\\heldout4\\<書き手>_<題材>\\*.sysml と、応答そのもの（raw_response.txt）。

    .venv\\Scripts\\python.exe eval\\pilot_parity\\generate_heldout4.py [--models gpt-5.6-terra gpt-5.4-mini]

OPENAI_API_KEY が要る。すでにフォルダがある組み合わせは飛ばす（--force で作り直す）。
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUT = Path(r"C:\test\sysml_models\eval\heldout4")
WRITERS = {"gpt-5.6-terra": "gpt56terra", "gpt-5.4-mini": "gpt54mini"}

PROMPT = """次の課題の SysML v2 モデルを、SysML v2 のテキスト記法（.sysml）で書いてください。

- ファイルは 4 つ以上に分け、すべて同じフォルダに置く前提で書いてください（ほかのファイルの要素は import して使う）。
- 標準ライブラリ（ScalarValues、ISQ、SI など）は必要に応じて import してください。
- 出力は各ファイルを次の形で並べ、ほかの説明は書かないでください。

=== file: <ファイル名>.sysml ===
<ファイルの中身>

課題:

{spec}
"""


def specs() -> dict[str, str]:
    text = (OUT / "SPECS.md").read_text(encoding="utf-8")
    head = text.split("\n## ", 1)[0]
    intro = "\n".join(line for line in head.splitlines()[3:] if line.strip())  # 形式の説明（タイトル・経緯を除く）
    out = {}
    for block in text.split("\n## ")[1:]:
        topic = block.split(":", 1)[0].strip()
        out[topic] = intro + "\n\n## " + block.strip()
    return out


def split_files(response: str) -> dict[str, str]:
    files: dict[str, str] = {}
    parts = re.split(r"^=== file: *(.+?\.sysml) *===\s*$", response, flags=re.M)
    for name, body in zip(parts[1::2], parts[2::2]):
        body = re.sub(r"^```[a-z]*\s*\n|\n```\s*$", "", body.strip())  # 念のためコードフェンスを外す
        files[Path(name.strip()).name] = body.strip() + "\n"
    return files


def generate(model: str, topic: str, spec: str, force: bool) -> str:
    import openai

    folder = OUT / f"{WRITERS[model]}_{topic}"
    if folder.exists() and not force:
        return f"skip {folder.name}"
    response = openai.OpenAI().responses.create(model=model, input=PROMPT.format(spec=spec))
    text = response.output_text
    files = split_files(text)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "raw_response.txt").write_text(text, encoding="utf-8")
    for name, body in files.items():
        (folder / name).write_text(body, encoding="utf-8")
    return f"{folder.name}: {len(files)} files"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", nargs="+", default=list(WRITERS))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    jobs = [(m, t, s) for m in args.models for t, s in specs().items()]
    with ThreadPoolExecutor(max_workers=5) as pool:
        for line in pool.map(lambda j: generate(*j, args.force), jobs):
            print(line, flush=True)


if __name__ == "__main__":
    sys.exit(main())

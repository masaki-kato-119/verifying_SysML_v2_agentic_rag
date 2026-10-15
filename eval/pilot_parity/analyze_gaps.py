"""Pilot との差を、Pilot のどの層が欠けているかに分けて集計する（P4 の材料）。

compare.py の結果（results/latest/units.json）と、コーパス・ラベルを読む。

  layers    Pilot のエラーの種類 → 層（文法 / 名前解決 / 種類の判定 / 個別の検証ルール）
  priority  LLM の誤りに近い入力（llm・mutant・probe）での件数 × 取りこぼし率
  grammar   Pilot に構文エラーが無い行で、自作だけがパースエラーを出したもの（文法の穴）
  messages  Pilot の検証メッセージごとの件数と、自作が同じ行・同じ種類で出した割合

    .venv\\Scripts\\python.exe -I eval/pilot_parity/analyze_gaps.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # python -I でも同じフォルダの compare.py を読む

from compare import category, is_error, load  # noqa: E402

LAYERS = {
    "syntax": "1 文法",
    "unresolved": "2 名前解決",
    "accessible_feature": "2 名前解決",
    "typing_kind": "3 種類の判定（解決結果を使う）",
    "must_reference": "3 種類の判定（解決結果を使う）",
    "invocation": "3 種類の判定（解決結果を使う）",
    "binding_override": "4 個別の検証ルール",
    "subject_first": "4 個別の検証ルール",
    "cardinality": "4 個別の検証ルール",
    "placement": "4 個別の検証ルール",
    "related_elements": "4 個別の検証ルール",
    "flow_end": "4 個別の検証ルール",
    "direction": "4 個別の検証ルール",
    "variant": "4 個別の検証ルール",
    "ownership": "4 個別の検証ルール",
    "individual": "4 個別の検証ルール",
    "annotation": "4 個別の検証ルール",
    "internal": "0 Pilot 内部エラー",
    "other": "4 個別の検証ルール",
}
LLM_LIKE = {"llm", "mutant", "probe"}


def normalize(message: str) -> str:
    return re.sub(r"'[^']*'", "'…'", message or "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, default=HERE / "corpus")
    ap.add_argument("--labels", type=Path, default=HERE / "labels")
    ap.add_argument("--out", type=Path, default=HERE / "results" / "latest")
    args = ap.parse_args()
    manifest = json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))

    layer_all, layer_hit = Counter(), Counter()
    cat_llm, cat_llm_hit = Counter(), Counter()
    msg_n, msg_hit, msg_layer = Counter(), Counter(), {}
    grammar = defaultdict(list)
    for entry in manifest:
        pilot, local = load(args.labels / "pilot", entry["id"]), load(args.labels / "local", entry["id"])
        if pilot is None or local is None:
            continue
        p_err = [i for i in pilot["issues"] if is_error(i)]
        l_keys = {(i.get("line"), category(i, "local")) for i in local["issues"] if is_error(i)}
        for i in p_err:
            cat = category(i, "pilot")
            hit = cat != "other" and (i.get("line"), cat) in l_keys
            layer = LAYERS.get(cat, "4 個別の検証ルール")
            layer_all[layer] += 1
            layer_hit[layer] += hit
            if entry["source"] in LLM_LIKE:
                cat_llm[cat] += 1
                cat_llm_hit[cat] += hit
            key = "syntax" if cat == "syntax" else normalize(i.get("message"))
            msg_n[key] += 1
            msg_hit[key] += hit
            msg_layer[key] = layer
        # 文法の穴: Pilot はその行に構文エラーを出していないのに、自作がパースエラーを出した
        p_syntax_lines = {i.get("line") for i in p_err if category(i, "pilot") == "syntax"}
        first_local_parse = next((i for i in local["issues"] if i.get("rule") == "parse"), None)
        if first_local_parse and first_local_parse.get("line") not in p_syntax_lines:
            line = first_local_parse.get("line")
            text = (args.corpus / "units" / f"{entry['id']}.sysml").read_text(encoding="utf-8").split("\n")
            src = text[line - 1].strip() if line and 0 < line <= len(text) else ""
            grammar[src].append({"id": entry["id"], "line": line, "message": first_local_parse["message"][:160],
                                 "pilot_clean_unit": not p_err})

    layers = {k: {"pilot_errors": n, "local_hit": layer_hit[k], "recall": round(layer_hit[k] / n, 3)}
              for k, n in sorted(layer_all.items())}
    priority = sorted(({"category": c, "layer": LAYERS.get(c, "4 個別の検証ルール"), "llm_like_errors": n,
                        "local_hit": cat_llm_hit[c], "missed": n - cat_llm_hit[c]}
                       for c, n in cat_llm.items()), key=lambda r: -r["missed"])
    messages = sorted(({"message": m, "layer": msg_layer[m], "pilot": n, "local_hit": msg_hit[m]}
                       for m, n in msg_n.items()), key=lambda r: -(r["pilot"] - r["local_hit"]))
    grammar_rows = sorted(({"source": s, "units": len(v), "pilot_clean_units": sum(x["pilot_clean_unit"] for x in v),
                            "example": v[0]} for s, v in grammar.items()), key=lambda r: -r["units"])
    result = {"layers": layers, "priority": priority, "messages": messages, "grammar_gaps": grammar_rows}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "gaps.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print("== layers")
    for k, v in layers.items():
        print(f"  {k}: {v}")
    print("== priority (llm-like)")
    for r in priority[:12]:
        print(f"  {r}")
    print(f"== grammar gaps: {len(grammar_rows)} distinct lines, "
          f"{sum(r['units'] for r in grammar_rows)} units ({sum(r['pilot_clean_units'] for r in grammar_rows)} Pilot-clean)")
    for r in grammar_rows[:25]:
        print(f"  [{r['units']}] {r['source'][:90]}  <- {r['example']['message'][:70]}")


if __name__ == "__main__":
    main()

"""Pilot（オラクル）と自作チェッカーの結果を突き合わせ、指標とレポートを作る。

比べる単位は 2 段:
  unit   その unit にエラーがあるか。見逃し（Pilot: エラー / 自作: エラーなし）が最重要の指標。
  issue  エラーを「行 + 種類」に正規化して突き合わせる（種類は CATEGORIES）。警告は除く。

種類は、Pilot はメッセージ、自作はルール名（パースエラーは syntax）から決める。
どちらにも当てはまらないものは other（other どうしは同じ行でも一致と数えない）。

    .venv\\Scripts\\python.exe -I eval/pilot_parity/compare.py [--out results/<name>]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Pilot のメッセージ → 種類（上から順に最初に当たったもの）
PILOT_CATEGORIES: list[tuple[str, re.Pattern[str]]] = [
    ("internal", re.compile(r"Internal error in the reference implementation")),
    ("syntax", re.compile(r"no viable alternative|mismatched input|extraneous input|missing '|missing EOF|token recognition")),
    ("accessible_feature", re.compile(r"accessible feature|Must be a valid feature")),
    ("unresolved", re.compile(r"Couldn't resolve reference")),
    ("typing_kind", re.compile(r"must be typed by|Must have a concrete type")),
    ("binding_override", re.compile(r"Cannot override a binding feature value|must be constant if")),
    ("subject_first", re.compile(r"Subject must be first")),
    ("must_reference", re.compile(r"^Must reference an? ")),
    ("related_elements", re.compile(r"at least two related elements")),
    ("flow_end", re.compile(r"Cannot identify flow end")),
    ("direction", re.compile(r"compatible direction")),
    ("individual", re.compile(r"individual")),
    ("variant", re.compile(r"[Vv]ariant|variation")),
    ("ownership", re.compile(r"Must be owned by|Owned usages of a port definition")),
    ("invocation", re.compile(r"Must invoke|model-level evaluable|input parameter of the invoked")),
    ("annotation", re.compile(r"Cannot annotate|metadata")),
]

# 自作のルール名 → 種類（ルール名の一部で判定。上から順）
LOCAL_CATEGORIES: list[tuple[str, re.Pattern[str]]] = [
    ("syntax", re.compile(r"^parse$|official_syntax|leading_then")),
    ("accessible_feature", re.compile(r"accessible|feature_chain|succession_ends")),
    ("unresolved", re.compile(r"type_exists|library_feature_references|annotation_reference|event_references|_check_import$")),
    ("typing_kind", re.compile(r"type_kinds|conjugated_port_typing|port_usage_conjugated")),
    ("binding_override", re.compile(r"binding_feature_override|satisfy_rebinds")),
    ("subject_first", re.compile(r"requirement_subject|include_use_case")),
    ("must_reference", re.compile(r"satisfy_requirement_usage|verify_requirement_placement")),
    ("related_elements", re.compile(r"at_least_two_related")),
    ("flow_end", re.compile(r"flow_end")),
    ("direction", re.compile(r"direction")),
    ("individual", re.compile(r"individual")),
    ("variant", re.compile(r"variation_variant")),
    ("ownership", re.compile(r"portion_usage_owner|port_def$")),
]


def category(issue: dict, side: str) -> str:
    if side == "pilot":
        if issue.get("syntax_error"):
            return "syntax"
        text = issue.get("message") or ""
        table = PILOT_CATEGORIES
    else:
        text = issue.get("rule") or ""
        table = LOCAL_CATEGORIES
    for name, pattern in table:
        if pattern.search(text):
            return name
    return "other"


def is_error(issue: dict) -> bool:
    return (issue.get("severity") or "").lower() == "error"


def load(dir_: Path, uid: str) -> dict | None:
    p = dir_ / f"{uid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def compare(corpus: Path, labels: Path) -> dict:
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    units = []
    for entry in manifest:
        pilot, local = load(labels / "pilot", entry["id"]), load(labels / "local", entry["id"])
        if pilot is None or local is None:
            continue
        p_err = [i for i in pilot["issues"] if is_error(i)]
        l_err = [i for i in local["issues"] if is_error(i)]
        p_keys = {(i.get("line"), category(i, "pilot")) for i in p_err}
        l_keys = {(i.get("line"), category(i, "local")) for i in l_err}
        matched = {k for k in p_keys & l_keys if k[1] != "other"}
        p_lines = {i.get("line") for i in p_err}
        l_lines = {i.get("line") for i in l_err}
        if local.get("crashed"):
            verdict = "local_crash"
        elif p_err and l_err:
            verdict = "both_error"
        elif p_err:
            verdict = "missed"           # 見逃し: Pilot はエラー、自作は問題なし
        elif l_err:
            verdict = "false_alarm"      # 誤検出: Pilot は問題なし、自作はエラー
        else:
            verdict = "both_clean"
        units.append({**entry, "verdict": verdict,
                      "pilot_keys": sorted(p_keys, key=str), "local_keys": sorted(l_keys, key=str),
                      "matched": len(matched), "pilot_n": len(p_keys), "local_n": len(l_keys),
                      "same_line_any_kind": len(p_lines & l_lines),
                      "pilot_first": min((k for k in p_keys if k[0] is not None), default=None),
                      "pilot_categories": sorted({k[1] for k in p_keys}),
                      "local_categories": sorted({k[1] for k in l_keys})})
    return {"units": units}


def mutant_deltas(units: list[dict]) -> list[dict]:
    """変異体を、元の unit（verified）との差分で評価する。

    元の unit に自作チェッカーの誤検出があると、変異体の判定にもそのまま混ざる。
    そこで「変異で新しく出たエラー（元の unit に無い 種類）」だけを比べる。
    行は変異で変わらない（削除は空行にしている）ので、元と同じキーは同じ指摘とみなす。
      injected        Pilot が新しいエラーを出したか（出さなければ、その変異は Pilot 上は誤りではない）
      detected        自作が新しいエラーを出したか
      detected_line   自作の新しいエラーが、変異を入れた行にあるか
    """
    base = {u["origin"]: u for u in units if u["source"] == "verified"}
    rows = []
    for u in units:
        if u["source"] != "mutant" or u["origin"] not in base:
            continue
        b = base[u["origin"]]
        p_new = {tuple(k) for k in u["pilot_keys"]} - {tuple(k) for k in b["pilot_keys"]}
        l_new = {tuple(k) for k in u["local_keys"]} - {tuple(k) for k in b["local_keys"]}
        rows.append({"id": u["id"], "operator": u["operator"], "line": u["line"],
                     "injected": bool(p_new), "detected": bool(l_new),
                     "detected_line": any(k[0] == u["line"] for k in l_new),
                     "pilot_new_categories": sorted({k[1] for k in p_new}),
                     "local_new_categories": sorted({k[1] for k in l_new})})
    return rows


def delta_table(rows: list[dict]) -> dict:
    out = {}
    for op in sorted({r["operator"] for r in rows}):
        rs = [r for r in rows if r["operator"] == op]
        inj = [r for r in rs if r["injected"]]
        out[op] = {"mutants": len(rs), "pilot_error": len(inj),
                   "detected": sum(r["detected"] for r in inj),
                   "detected_on_line": sum(r["detected_line"] for r in inj),
                   "pilot_clean_but_local_new_error": sum(1 for r in rs if not r["injected"] and r["detected"])}
    inj = [r for r in rows if r["injected"]]
    out["(total)"] = {"mutants": len(rows), "pilot_error": len(inj), "detected": sum(r["detected"] for r in inj),
                      "detected_on_line": sum(r["detected_line"] for r in inj),
                      "pilot_clean_but_local_new_error": sum(1 for r in rows if not r["injected"] and r["detected"])}
    return out


def summarize(units: list[dict]) -> dict:
    def block(rows: list[dict]) -> dict:
        v = Counter(r["verdict"] for r in rows)
        p_err_units = sum(1 for r in rows if r["pilot_n"])
        p_n, l_n, m = sum(r["pilot_n"] for r in rows), sum(r["local_n"] for r in rows), sum(r["matched"] for r in rows)
        return {"units": len(rows), **dict(v),
                "miss_rate": round(v["missed"] / p_err_units, 3) if p_err_units else None,
                "issue_recall": round(m / p_n, 3) if p_n else None,
                "issue_precision": round(m / l_n, 3) if l_n else None}

    by_source = defaultdict(list)
    by_operator = defaultdict(list)
    for r in units:
        by_source[r["source"]].append(r)
        if r["operator"]:
            by_operator[r["operator"]].append(r)
    # Pilot の種類ごとの再現率（その種類のエラーを、同じ行・同じ種類で自作が出したか）
    cat_total, cat_hit = Counter(), Counter()
    for r in units:
        local = {tuple(k) for k in r["local_keys"]}
        for k in r["pilot_keys"]:
            cat_total[k[1]] += 1
            if tuple(k) in local and k[1] != "other":
                cat_hit[k[1]] += 1
    return {"overall": block(units),
            "mutant_delta": delta_table(mutant_deltas(units)),
            "by_source": {k: block(v) for k, v in sorted(by_source.items())},
            "by_operator": {k: block(v) for k, v in sorted(by_operator.items())},
            "recall_by_pilot_category": {c: {"pilot": n, "hit": cat_hit[c], "recall": round(cat_hit[c] / n, 3)}
                                         for c, n in cat_total.most_common()}}


def markdown(summary: dict, units: list[dict]) -> str:
    out = ["# Pilot との差分（自動生成）", ""]
    o = summary["overall"]
    out += [f"- unit 数: {o['units']}、見逃し率（Pilot がエラーの unit のうち自作が問題なし）: {o['miss_rate']}",
            f"- 行＋種類単位: 再現率 {o['issue_recall']}、適合率 {o['issue_precision']}", ""]
    cols = ["units", "both_clean", "both_error", "missed", "false_alarm", "local_crash", "miss_rate", "issue_recall", "issue_precision"]
    for title, table in (("出どころ別", summary["by_source"]), ("変異の種類別", summary["by_operator"])):
        out += [f"## {title}", "", "| | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
        for k, b in table.items():
            out.append(f"| {k} | " + " | ".join(str(b.get(c, 0) if b.get(c) is not None else "—") for c in cols) + " |")
        out.append("")
    out += ["## 変異体（元の unit との差分で評価）", "",
            "入れた誤りに Pilot が新しいエラーを出した変異体のうち、自作も新しいエラーを出した数。",
            "", "| 変異 | 変異体 | Pilot がエラー | 自作も検出 | 同じ行で検出 | Pilot は問題なしなのに自作が新しいエラー |",
            "|---|---|---|---|---|---|"]
    for op, b in summary["mutant_delta"].items():
        out.append(f"| {op} | {b['mutants']} | {b['pilot_error']} | {b['detected']} | {b['detected_on_line']} | "
                   f"{b['pilot_clean_but_local_new_error']} |")
    out.append("")
    out += ["## Pilot のエラーの種類別の再現率", "", "| 種類 | Pilot 件数 | 自作が同じ行・同じ種類で出した | 再現率 |", "|---|---|---|---|"]
    for c, b in summary["recall_by_pilot_category"].items():
        out.append(f"| {c} | {b['pilot']} | {b['hit']} | {b['recall']} |")
    missed = [u for u in units if u["verdict"] == "missed"]
    out += ["", f"## 見逃した unit（{len(missed)} 件）", "", "| id | Pilot のエラーの種類 |", "|---|---|"]
    out += [f"| {u['id']} | {', '.join(u['pilot_categories'])} |" for u in missed]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, default=HERE / "corpus")
    ap.add_argument("--labels", type=Path, default=HERE / "labels")
    ap.add_argument("--out", type=Path, default=HERE / "results" / "latest")
    args = ap.parse_args()
    result = compare(args.corpus, args.labels)
    summary = summarize(result["units"])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "units.json").write_text(json.dumps(result["units"], ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out / "REPORT.md").write_text(markdown(summary, result["units"]), encoding="utf-8")
    print(json.dumps(summary["overall"], ensure_ascii=False))


if __name__ == "__main__":
    main()

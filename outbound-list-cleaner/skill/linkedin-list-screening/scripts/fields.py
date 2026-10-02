"""Stage 4 — clean job titles and company names (LinkedIn's free text).

Runs on the contacts that stay (Decision isn't "exclude") after the screening
review. Person names are NOT cleaned here: outbound-list-cleaner step 2 does
that for every list type.

  prepare   Writes <run_dir>/fields_review.json: every title and company name
            that would change, with the proposed clean value. "auto" ones are
            safe formatting fixes; the others need Claude's judgment (several
            roles in one title, ALL-CAPS names that may be acronyms, divisions
            or extras in brackets) — and the user's when unsure.
  apply     --decisions <json>: {"titles": {"<before>": "<after>"},
            "companies": {"<before>": "<after>"}} — usually the proposals,
            edited where judgment said so. Writes Title / Company (and the
            file's own title/company columns) in screening.csv and lists every
            change in fields_changes.json for the chat.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from screen import load, save  # noqa: E402

ACRONYMS = {"VP", "SVP", "EVP", "AVP", "CEO", "CFO", "COO", "CPO", "CIO", "CTO", "CSO", "CMO", "CHRO", "CXO",
            "IT", "HR", "MRO", "S&OP", "IBP", "EHS", "HSE", "R&D", "QA", "QC", "US", "USA", "UK", "EMEA", "APAC",
            "LATAM", "NA", "AP", "AR", "ERP", "SAP", "P2P", "S2P", "GM", "MBA", "PMP", "II", "III", "IV", "CPG",
            "B2B", "BU", "OEM", "3PL", "DC", "FP&A", "M&A", "PR", "SC", "SCM", "BI", "AI", "ML", "CX", "UX"}
SMALL = {"and", "of", "for", "the", "in", "at", "to", "a", "an", "on", "&"}
LEGAL = re.compile(r"[,\s]+(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|co|plc|gmbh|s\.a|sa|ag|bv|n\.v|nv|lp|llp|"
                   r"pty|pvt|srl|s\.r\.l|oy|ab|as|kg)\.?$", re.I)
SYMBOLS = re.compile(r"[®™©℠]")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def smart_case(text):
    """'DIRECTOR OF SUPPLY CHAIN' -> 'Director of Supply Chain', acronyms kept."""
    words = text.split(" ")
    out = []
    for i, w in enumerate(words):
        bare = re.sub(r"[^A-Za-z0-9&]", "", w).upper()
        if bare in ACRONYMS:
            out.append(re.sub(re.escape(re.sub(r"[^A-Za-z0-9&]", "", w)), bare, w, count=1) if bare else w)
        elif w.lower() in SMALL and i:
            out.append(w.lower())
        else:
            out.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(out)


def clean_title(title, company):
    """-> (clean, needs_judgment, why)"""
    t = EMOJI.sub("", SYMBOLS.sub("", title or "")).strip()
    t = re.sub(r"\s+", " ", t)
    why = []
    if company:  # 'Buyer at Acme' / 'Buyer @ Acme' / 'Buyer - Acme'
        m = re.search(rf"\s*(?:@|\bat\b|-|–|,)\s*{re.escape(company)}\.?$", t, re.I)
        if m:
            t, _ = t[:m.start()], why.append("company name removed from the title")
    t = re.sub(r"[\s,.;:|\-–/]+$", "", t)
    if t.isupper() and len(t) > 4:
        t, _ = smart_case(t), why.append("ALL CAPS")
    elif t.islower():
        t, _ = smart_case(t), why.append("all lower case")
    t = re.sub(r"\s*([|/])\s*", r" \1 ", t).replace("  ", " ")
    judgment = []
    if re.search(r"\s[|/]\s", t):
        judgment.append("several roles in one title — keep the one at this company / most relevant")
    if len(t) > 100:
        judgment.append("very long title — shorten to the role")
    if t != (title or "").strip() and not why and not judgment:
        why.append("spacing / punctuation")
    return t, bool(judgment), "; ".join(why + judgment)


def clean_company(name):
    n = EMOJI.sub("", SYMBOLS.sub("", name or "")).strip()
    n = re.sub(r"\s+", " ", n)
    why, judgment = [], []
    stripped = LEGAL.sub("", n).rstrip(" ,")
    while stripped != n:
        n, stripped = stripped, LEGAL.sub("", stripped).rstrip(" ,")
        why.append("legal suffix removed")
    if re.search(r"\(.*\)", n):
        judgment.append("text in brackets — drop it unless it's part of the name")
    if re.search(r"(&|and)\s+subsidiaries$|,\s*(north|south|central|latin)\b.*america$|,\s*(emea|apac|americas)$", n, re.I):
        judgment.append("looks like a division / group label — use the company's name")
    if n.isupper() and len(n.replace(" ", "")) > 4:
        judgment.append("ALL CAPS — keep only if it's how the company writes its name (acronym/brand)")
    if n != (name or "").strip() and not why:
        why.append("spacing / symbols")
    return n, bool(judgment), "; ".join(dict.fromkeys(why + judgment))


def prepare(args):
    _, rows = load(args.run_dir)
    live = [r for r in rows if r.get("Decision") != "exclude"]
    titles, companies = {}, {}
    for r in live:
        t, j, why = clean_title(r["Title"], r["Company"])
        if t != r["Title"] or j:
            e = titles.setdefault(r["Title"], {"before": r["Title"], "after": t, "auto": not j, "why": why,
                                               "companies": [], "rows": 0})
            e["rows"] += 1
            if r["Company"] not in e["companies"]:
                e["companies"].append(r["Company"])
        c, j, why = clean_company(r["Company"])
        if (c != r["Company"] or j) and r["Company"] not in companies:
            companies[r["Company"]] = {"before": r["Company"], "after": c, "auto": not j, "why": why}
    review = {"titles": list(titles.values()), "companies": list(companies.values())}
    (Path(args.run_dir) / "fields_review.json").write_text(json.dumps(review, indent=1, ensure_ascii=False))
    n = lambda xs, a: sum(1 for x in xs if x["auto"] == a)
    print(f"titles: {n(review['titles'], True)} safe fixes, {n(review['titles'], False)} to judge; "
          f"companies: {n(review['companies'], True)} safe fixes, {n(review['companies'], False)} to judge "
          f"-> fields_review.json")


def apply(args):
    run = Path(args.run_dir)
    fields, rows = load(run)
    dec = json.loads(Path(args.decisions).read_text())
    t_map, c_map = dec.get("titles", {}), dec.get("companies", {})
    changes = {"titles": [], "companies": []}
    seen_c = set()
    for r in rows:
        if r.get("Decision") == "exclude":
            continue
        new_t = t_map.get(r["Title"])
        if new_t is not None and new_t != r["Title"]:
            changes["titles"].append({"contact": r["Contact"], "company": r["Company"], "from": r["Title"], "to": new_t})
            r["Title"] = new_t
            for col in ("Job Title", "Current Job", "Title "):
                if col in fields:
                    r[col] = new_t
        new_c = c_map.get(r["Company"])
        if new_c is not None and new_c != r["Company"]:
            if r["Company"] not in seen_c:
                changes["companies"].append({"from": r["Company"], "to": new_c})
                seen_c.add(r["Company"])
            r["Company"] = new_c
            if "Company Name" in fields:
                r["Company Name"] = new_c
    save(run, fields, rows)
    (run / "fields_changes.json").write_text(json.dumps(changes, indent=1, ensure_ascii=False))
    print(f"screening.csv updated: {len(changes['titles'])} titles, {len(changes['companies'])} company names "
          f"-> fields_changes.json (show them in the chat)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--run-dir", required=True); p.set_defaults(func=prepare)
    p = sub.add_parser("apply"); p.add_argument("--run-dir", required=True); p.add_argument("--decisions", required=True)
    p.set_defaults(func=apply)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

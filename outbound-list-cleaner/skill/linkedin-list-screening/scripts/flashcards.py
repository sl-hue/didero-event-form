"""Build the flashcard review page from screening.csv.

  build   Writes <run_dir>/cards.json, companies.json and review.html — a
          single, self-contained page (no internet needed) in two steps:
          1 Companies (based in / present in; keep or exclude each), then
          2 Contacts of the kept companies, grouped under their company.
          Country rules in each step; Claude's suggestions filled in; changes
          highlighted. "Finish review" gives a code for
          `screen.py apply-decisions --code …`.

The page holds personal data: it stays on the user's device (shown in the
Cowork/Claude Code window) and is never published.
"""
import argparse
import csv
import hashlib
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from screen import AMBIGUOUS, CA_PROVINCES, CONFIG, COUNTRY_ALIASES, US_STATES, presence_of  # noqa: E402


def company_suggestion(rows, targets):
    """Keep / exclude / review for one company: is it based in or present in a target country,
    and is it a fit (company research)."""
    r = rows[0]
    presence = sorted(presence_of(r))
    fit, why = r.get("Company Fit") or "unclear", r.get("Company Reason") or "not researched yet"
    if fit == "no":
        return "exclude", f"not a fit: {why}"
    if not presence:
        return "review", "couldn't find where the company is based"
    if not set(presence) & set(targets):
        return "exclude", f"based in {r['Company Country'] or presence[0]}, no presence in {', '.join(targets)}"
    if fit != "fit":
        return "review", f"company fit unclear: {why}"
    return "keep", ""


def contact_suggestion(r, targets):
    """Keep / exclude / review for one contact: job title and where the person is."""
    title, cc = r.get("Title Fit") or "unclear", r["Contact Country"]
    notes = []
    if title != "fit":
        notes.append(f"title: {r.get('Title Reason', '')}")
    if not cc:
        notes.append("contact's country unknown")
    elif cc not in targets:
        notes.append(f"contact in {cc}")
    if title == "no" or (cc and cc not in targets):
        return "exclude", "; ".join(notes)
    return ("keep", "") if not notes else ("review", "; ".join(notes))


def build(args):
    run = Path(args.run_dir)
    with open(run / "screening.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    geo_file = run / "geo_settings.json"
    geo_set = json.loads(geo_file.read_text()) if geo_file.exists() else {
        "company_countries": CONFIG["default_company_countries"], "contact_countries": CONFIG["default_contact_countries"]}
    li_cols = ["LinkedIn Contact Profile URL", "Profile URL", "LinkedIn URL", "Person Linkedin Url", "linkedinUrl"]
    groups = {}
    for r in rows:
        groups.setdefault((r["Company"] or "(no company)").strip().lower(), []).append(r)
    companies, company_n = [], {}
    for i, (key, rs) in enumerate(groups.items(), 1):
        company_n[key] = i
        sug, why = company_suggestion(rs, geo_set["company_countries"])
        companies.append({"n": i, "name": rs[0]["Company"] or "(no company)", "hq": rs[0]["Company Country"],
                          "presence": sorted(presence_of(rs[0])), "about": rs[0].get("Company Reason", ""),
                          "suggestion": sug, "reason": why, "contacts": len(rs)})
    cards = []
    for n, r in enumerate(rows, 1):
        sug, why = contact_suggestion(r, geo_set["contact_countries"])
        cards.append({
            "n": n, "row_id": r["Row ID"], "name": r["Contact"], "title": r["Title"], "company": r["Company"],
            "company_n": company_n[(r["Company"] or "(no company)").strip().lower()],
            "contact_country": r["Contact Country"], "linkedin": next((r[c] for c in li_cols if r.get(c)), ""),
            "suggestion": sug, "reason": why, "decision": r.get("Decision", ""),
        })
    (run / "cards.json").write_text(json.dumps(cards, indent=1, ensure_ascii=False))
    (run / "companies.json").write_text(json.dumps(companies, indent=1, ensure_ascii=False))
    review_id = hashlib.sha1(json.dumps([c["row_id"] for c in cards]).encode()).hexdigest()[:10]
    js = lambda x: json.dumps(x, ensure_ascii=False).replace("</", "<\\/")
    geo = {"aliases": COUNTRY_ALIASES, "ambiguous": AMBIGUOUS, "states": sorted(US_STATES),
           "provinces": sorted(CA_PROVINCES)}
    page = TEMPLATE.replace("__TITLE__", html.escape(args.title or "List review")) \
                   .replace("__REVIEW_ID__", review_id).replace("__GEO__", js(geo)) \
                   .replace("__COMPANIES__", js(companies)).replace("__CARDS__", js(cards))
    (run / "review.html").write_text(page, encoding="utf-8")
    cs = {k: sum(1 for c in companies if c["suggestion"] == k) for k in ("keep", "review", "exclude")}
    ps = {k: sum(1 for c in cards if c["suggestion"] == k) for k in ("keep", "review", "exclude")}
    print(f"review.html: {len(companies)} companies (suggest {cs['keep']} keep, {cs['review']} review, "
          f"{cs['exclude']} exclude); {len(cards)} contacts (suggest {ps['keep']} keep, {ps['review']} review, "
          f"{ps['exclude']} exclude)")


TEMPLATE = (Path(__file__).with_name("review_template.html")).read_text(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--title", help="page title, e.g. the list name")
    p.set_defaults(func=build)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

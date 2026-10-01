"""Build the flashcard review page from screening.csv.

  build   Writes <run_dir>/cards.json and <run_dir>/review.html — a single,
          self-contained page (no internet needed), one layout: a Companies |
          Contacts switch, a country rules bar (include/exclude; the rule
          applies to company HQ or contact country depending on the view; any
          case or common spelling; asks when unsure), and one list with
          Claude's suggestion filled in — Keep all / Exclude all per company,
          Keep / Exclude per contact, changes highlighted. "Finish review"
          gives a code for `screen.py apply-decisions --code …`.

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
from screen import AMBIGUOUS, CA_PROVINCES, COUNTRY_ALIASES, US_STATES  # noqa: E402


def build(args):
    run = Path(args.run_dir)
    with open(run / "screening.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    li_cols = ["LinkedIn Contact Profile URL", "Profile URL", "LinkedIn URL", "Person Linkedin Url", "linkedinUrl"]
    cards = []
    for n, r in enumerate(rows, 1):
        cards.append({
            "n": n, "row_id": r["Row ID"], "name": r["Contact"], "title": r["Title"], "company": r["Company"],
            "contact_country": r["Contact Country"], "company_country": r["Company Country"],
            "linkedin": next((r[c] for c in li_cols if r.get(c)), ""),
            "verdicts": [
                {"label": "Title", "fit": r.get("Title Fit") or "unclear", "reason": r.get("Title Reason", "")},
                {"label": "Company", "fit": r.get("Company Fit") or "unclear",
                 "reason": r.get("Company Reason") or "not researched yet"},
                {"label": "Geography", "fit": r.get("Geo Fit") or "unclear", "reason": r.get("Geo Reason", "")},
            ],
            "recommendation": r.get("Recommendation") or "review",
            "decision": r.get("Decision", ""),
        })
    (run / "cards.json").write_text(json.dumps(cards, indent=1, ensure_ascii=False))
    review_id = hashlib.sha1(json.dumps([c["row_id"] for c in cards]).encode()).hexdigest()[:10]
    data = json.dumps(cards, ensure_ascii=False).replace("</", "<\\/")
    geo = json.dumps({"aliases": COUNTRY_ALIASES, "ambiguous": AMBIGUOUS,
                      "states": sorted(US_STATES), "provinces": sorted(CA_PROVINCES)}, ensure_ascii=False)
    page = TEMPLATE.replace("__TITLE__", html.escape(args.title or "List review")) \
                   .replace("__REVIEW_ID__", review_id).replace("__GEO__", geo).replace("__CARDS__", data)
    (run / "review.html").write_text(page, encoding="utf-8")
    counts = {k: sum(1 for c in cards if c["recommendation"] == k) for k in ("keep", "review", "exclude")}
    print(f"review.html: {len(cards)} contacts on {len({c['company'] for c in cards})} companies ({counts['keep']} recommended keep, {counts['review']} to review, "
          f"{counts['exclude']} recommended exclude)")


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

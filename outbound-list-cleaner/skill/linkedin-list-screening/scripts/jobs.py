"""Multiple current jobs: the user sets each person's real title and company.

LinkedIn exports (Sales Nav, Evaboot) give one "main" job per person and only
a count of current jobs (`Current Jobs Number`); the other jobs aren't in the
file. So everyone with more than one current job is checked on their LinkedIn
profile, one after another, before the company review.

  build    Writes <run_dir>/jobs.json and <run_dir>/jobs.html (self-contained,
           local only): one person at a time with the title and company from
           the file pre-filled, the number of current jobs, the headline, and
           an "Open LinkedIn" button. Confirm moves to the next person and
           opens their profile in the same LinkedIn tab. Finish gives a code.
  apply    --code <code>: preview of the changes (nothing saved).
           --confirm: after the user's OK, writes Title / Company / Jobs Check
           into screening.csv. When the company changes, the row's old company
           data (website, domain, size, industry, HQ…) is cleared so the
           company research fills it for the right company.

The page holds personal data: it stays on the user's device, never published.
"""
import argparse
import base64
import hashlib
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from screen import load, save  # noqa: E402

LI_COLS = ["Linkedin URL Public", "LinkedIn Contact Profile URL", "Profile URL", "LinkedIn URL",
           "Person Linkedin Url", "linkedinUrl", "Sales Navigator URL"]
HEADLINE_COLS = ["Profile Headline", "Headline"]
# Derived company columns that belong to the old company when a person's company changes.
DERIVED_COMPANY = ["Company Country", "Company Presence", "Company Fit", "Company Reason"]


def multi(r):
    v = (r.get("Current Jobs") or "").strip()
    return v.isdigit() and int(v) > 1


def build(args):
    run = Path(args.run_dir)
    _, rows = load(run)
    people = []
    for r in rows:
        if not multi(r) or r.get("Decision") == "exclude":
            continue
        people.append({"row_id": r["Row ID"], "name": r["Contact"], "title": r["Title"], "company": r["Company"],
                       "jobs": int(r["Current Jobs"]),
                       "headline": next((r[c] for c in HEADLINE_COLS if r.get(c)), ""),
                       "location": ", ".join(x for x in (r.get("Contact City"), r.get("Contact State"),
                                                         r.get("Contact Country")) if x),
                       "linkedin": next((r[c] for c in LI_COLS if r.get(c)), ""),
                       "done": r.get("Jobs Check", "")})
    (run / "jobs.json").write_text(json.dumps(people, indent=1, ensure_ascii=False))
    rid = hashlib.sha1(json.dumps([p["row_id"] for p in people]).encode()).hexdigest()[:10]
    page = TEMPLATE.replace("__TITLE__", html.escape(args.title or "Multiple jobs")) \
                   .replace("__ID__", rid) \
                   .replace("__PEOPLE__", json.dumps(people, ensure_ascii=False).replace("</", "<\\/"))
    (run / "jobs.html").write_text(page, encoding="utf-8")
    print(f"jobs.html: {len(people)} contacts with more than one current job")


def decode(code):
    code = code.strip()
    if not code.startswith("LJ1:"):
        raise SystemExit("that isn't a multiple-jobs code — ask the user to copy it again")
    try:
        return json.loads(base64.b64decode(code[4:]).decode("utf-8"))
    except Exception:
        raise SystemExit("the code is incomplete — ask the user to copy it again (Copy code button)")


def apply(args):
    run = Path(args.run_dir)
    fields, rows = load(run)
    by_id = {r["Row ID"]: r for r in rows}
    pending = run / "jobs_pending.json"
    if args.confirm:
        if not pending.exists():
            raise SystemExit("nothing pending — paste the code first (apply --code …)")
        data = json.loads(pending.read_text())
        company_cols = [f for f in fields if f.startswith("Company ") and f != "Company Name"]
        for rid, a in data["answers"].items():
            r = by_id[rid]
            if a["v"] == "exclude":
                r["Jobs Check"], r["Decision"] = "excluded", "exclude"
                if "Decision Note" in fields:
                    r["Decision Note"] = "multiple jobs: excluded by the reviewer"
                continue
            changed_company = a["company"].strip() != r["Company"].strip()
            r["Title"], r["Company"] = a["title"].strip(), a["company"].strip()
            for col in ("Job Title", "Current Job"):
                if col in fields:
                    r[col] = r["Title"]
            if "Company Name" in fields:
                r["Company Name"] = r["Company"]
            if changed_company:
                for col in company_cols + DERIVED_COMPANY:
                    if col in r and col not in ("Company Name",):
                        r[col] = ""
            r["Jobs Check"] = "company changed" if changed_company else (
                "title changed" if a.get("changed") else "confirmed")
        save(run, fields, rows)
        pending.rename(run / "jobs_applied.json")
        counts = {}
        for r in rows:
            if r.get("Jobs Check"):
                counts[r["Jobs Check"]] = counts.get(r["Jobs Check"], 0) + 1
        print(f"saved to screening.csv: {counts}")
        return
    if not args.code:
        raise SystemExit("give --code (preview) or --confirm (after the user approves)")
    answers = decode(args.code)
    people = {p["row_id"]: p for p in json.loads((run / "jobs.json").read_text())}
    out, lines = {}, []
    for rid, a in answers.items():
        if rid not in people:
            raise SystemExit("that code is from a different list — ask the user to copy it again")
        p = people[rid]
        a.setdefault("title", p["title"])
        a.setdefault("company", p["company"])
        a["changed"] = a["v"] != "exclude" and (a["title"] != p["title"] or a["company"] != p["company"])
        out[rid] = a
        if a["v"] == "exclude":
            lines.append(f"{p['name']} | {p['title']} @ {p['company']} | EXCLUDED")
        elif a["changed"]:
            lines.append(f"{p['name']} | {p['title']} @ {p['company']} | → {a['title']} @ {a['company']}"
                         + ("  (company changed: its company data will be cleared and researched again)"
                            if a["company"] != p["company"] else ""))
    open_ = [p["name"] for rid, p in people.items() if rid not in answers]
    pending.write_text(json.dumps({"code": args.code.strip(), "answers": out}, indent=1, ensure_ascii=False))
    kept = sum(1 for a in out.values() if a["v"] != "exclude" and not a["changed"])
    print(f"PREVIEW — nothing saved yet. {len(out)} answered: {kept} confirmed as in the file, "
          f"{sum(1 for a in out.values() if a['changed'])} changed, "
          f"{sum(1 for a in out.values() if a['v'] == 'exclude')} excluded; {len(open_)} not answered")
    if lines:
        print("Contact | In the file | Change")
        print("\n".join(lines))
    if open_:
        print("not answered: " + ", ".join(open_))
    print("\nShow this to the user. After they approve: jobs.py apply --run-dir … --confirm")


TEMPLATE = (Path(__file__).with_name("jobs_template.html")).read_text(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build"); p.add_argument("--run-dir", required=True); p.add_argument("--title")
    p.set_defaults(func=build)
    p = sub.add_parser("apply"); p.add_argument("--run-dir", required=True); p.add_argument("--code")
    p.add_argument("--confirm", action="store_true"); p.set_defaults(func=apply)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

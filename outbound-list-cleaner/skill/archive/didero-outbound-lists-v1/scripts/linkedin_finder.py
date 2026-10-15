"""Event lists — find LinkedIn URLs for people ZoomInfo couldn't match.

  build   --run-dir <run_dir> [--title "<list name>"]
          Writes <run_dir>/linkedin_finder.html (local page, never published):
          one person at a time — name, title, company, website, HQ — with
          "Search Google" / "Search LinkedIn" (opened in the same browser tab each
          time), a box for the profile URL, "Save and next" (Enter) and "Can't
          find". Finish gives a code. People with a LinkedIn URL already (from the
          list or a good ZoomInfo match) are skipped.
  apply   --run-dir <run_dir> --code <code>   preview (nothing saved)
          --confirm                           after the user's OK: writes the URLs
          to LinkedIn Contact Profile URL in working.csv. Not-found people stay
          unenriched (listed in linkedin_not_found.json).
"""
import argparse
import base64
import hashlib
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worksheet as ws  # noqa: E402

LI = "LinkedIn Contact Profile URL"


def needs(r):
    if (r.get(LI) or "").strip():
        return False
    return not (r.get("ZI Match") == "good" and (r.get("ZI LinkedIn URL") or "").strip())


def clean(u):
    m = re.search(r"linkedin\.com/in/([^/?#\s]+)", u or "", re.I)
    return f"https://www.linkedin.com/in/{m.group(1).rstrip('/')}" if m else ""


def build(args):
    run = Path(args.run_dir)
    _, rows = ws.load(run)
    people = [{"row": r[ws.CONTACT_ID], "first": r.get("First Name", ""), "last": r.get("Last Name", ""),
               "title": r.get("Job Title", ""), "company": r.get("Company Name", ""), "website": r.get("Website", ""),
               "hq": ", ".join(x for x in (r.get("Company City"), r.get("Company State"), r.get("Company Country")) if x),
               "note": r.get("ZI Match Note", "")} for r in rows if needs(r)]
    (run / "linkedin_finder.json").write_text(json.dumps(people, indent=1, ensure_ascii=False))
    rid = hashlib.sha1(json.dumps([p["row"] for p in people]).encode()).hexdigest()[:10]
    tpl = Path(__file__).with_name("linkedin_finder_template.html").read_text(encoding="utf-8")
    page = tpl.replace("__TITLE__", html.escape(args.title or "Find LinkedIn URLs")).replace("__ID__", rid) \
              .replace("__PEOPLE__", json.dumps(people, ensure_ascii=False).replace("</", "<\\/"))
    (run / "linkedin_finder.html").write_text(page, encoding="utf-8")
    print(f"linkedin_finder.html: {len(people)} people without a LinkedIn URL")


def apply(args):
    run = Path(args.run_dir)
    fields, rows = ws.load(run)
    pending = run / "linkedin_pending.json"
    if args.confirm:
        if not pending.exists():
            raise SystemExit("nothing pending — paste the code first (apply --code …)")
        found = json.loads(pending.read_text())
        by = {r[ws.CONTACT_ID]: r for r in rows}
        for rid, url in found.items():
            if url:
                by[rid][LI] = url
        ws.save(run, fields, rows)
        ws.log(run, {"action": "linkedin_finder", "found": sum(1 for u in found.values() if u),
                     "not_found": sum(1 for u in found.values() if not u)})
        (run / "linkedin_not_found.json").write_text(json.dumps([rid for rid, u in found.items() if not u], indent=1))
        pending.rename(run / "linkedin_applied.json")
        ws.snapshot_copy(run, "05b_linkedin")
        print(f"saved {sum(1 for u in found.values() if u)} LinkedIn URLs; "
              f"{sum(1 for u in found.values() if not u)} not found (stay unenriched)")
        return
    code = (args.code or "").strip()
    if not code.startswith("LF1:"):
        raise SystemExit("that isn't a LinkedIn-finder code — ask the user to copy it again")
    try:
        data = json.loads(base64.b64decode(code[4:]).decode("utf-8"))
    except Exception:
        raise SystemExit("the code is incomplete — ask the user to copy it again (Copy code button)")
    people = {p["row"]: p for p in json.loads((run / "linkedin_finder.json").read_text())}
    clean_data = {rid: clean(u) for rid, u in data.items() if rid in people}
    pending.write_text(json.dumps(clean_data, indent=1))
    print(f"PREVIEW — nothing saved yet: {sum(1 for u in clean_data.values() if u)} found, "
          f"{sum(1 for u in clean_data.values() if not u)} can't find, "
          f"{len(people) - len(clean_data)} not done")
    for rid, u in clean_data.items():
        p = people[rid]
        shown = u or "can't find"
        print(f"{p['first']} {p['last']} | {p['company']} | {shown}")
    print("Show this to the user. After they approve: linkedin_finder.py apply --run-dir … --confirm")


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

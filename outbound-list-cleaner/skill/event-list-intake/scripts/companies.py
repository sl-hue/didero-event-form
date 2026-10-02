"""Event lists — company website, then company HQ (city / state / country), by web research.

For event lists the order is: website first (it's what tells same-name
companies apart), then HQ — which is what makes the ZoomInfo match work later.

  plan     --run-dir <run_dir>  Writes companies_todo.json: each company still
           missing a website or HQ, with hints (corporate email domains seen on
           its attendees, any website/location already in the file).
  apply    --run-dir <run_dir> --file found.json
           found.json: {"<company as in event.csv>": {"website": "", "city": "", "state": "",
           "country": "", "source": "<url you used>", "confidence": "high|medium|low"}}
           Writes the values to every row of that company (website cleaned to the
           site itself). Low-confidence ones are listed for the user to confirm.
  export   --run-dir <run_dir> --out <file.csv>
           The file linkedin-list-screening reads (its column names), so the
           event list goes through the same company / contact review.
"""
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from intake import load, save

FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "live.com",
             "msn.com", "me.com", "comcast.net", "protonmail.com", "proton.me", "gmx.com", "mail.com", "ymail.com",
             "qq.com", "163.com", "139.com", "126.com"}
# Not a company website (same list as outbound-list-cleaner step 2's website cleaning).
NOT_A_WEBSITE = ("bit.ly", "bitly.com", "tinyurl.com", "lnkd.in", "t.co", "ow.ly", "linktr.ee", "linktree.com",
                 "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
                 "greenhouse.io", "lever.co", "myworkdayjobs.com", "indeed.com", "glassdoor.com", "wixsite.com")


def clean_site(url):
    host = re.sub(r"^[a-z]+://", "", (url or "").strip(), flags=re.I).split("/")[0].split("?")[0].lower()
    host = host.strip(".")
    bare = host[4:] if host.startswith("www.") else host
    if not host or "." not in host or any(bare == d or bare.endswith("." + d) for d in NOT_A_WEBSITE):
        return ""
    return re.sub(r"^(careers?|jobs)\.", "www.", host)


def plan(args):
    rows = load(args.run_dir)
    by_co = defaultdict(list)
    for r in rows:
        if r.get("Company"):
            by_co[r["Company"]].append(r)
    todo = []
    for co, rs in by_co.items():
        have = {c: next((r[c] for r in rs if r.get(c)), "") for c in
                ("Company Website", "Company City", "Company State", "Company Country")}
        if all(have.values()):
            continue
        domains = Counter(r["Email"].split("@")[-1].lower() for r in rs if "@" in r.get("Email", ""))
        todo.append({"company": co, "people": len(rs), "have": {k: v for k, v in have.items() if v},
                     "email_domains": [d for d, _ in domains.most_common() if d not in FREE_MAIL]})
    (Path(args.run_dir) / "companies_todo.json").write_text(json.dumps(todo, indent=1, ensure_ascii=False))
    print(f"{len(by_co)} companies; {len(todo)} need a website and/or HQ -> companies_todo.json")


def apply(args):
    rows = load(args.run_dir)
    found = json.loads(Path(args.file).read_text())
    done, low, unknown = 0, [], []
    names = {r["Company"] for r in rows}
    for co, f in found.items():
        if co not in names:
            unknown.append(co)
            continue
        site = clean_site(f.get("website", ""))
        for r in rows:
            if r["Company"] == co:
                if site:
                    r["Company Website"] = site
                for col, k in (("Company City", "city"), ("Company State", "state"), ("Company Country", "country")):
                    if f.get(k):
                        r[col] = f[k].strip()
        done += 1
        if f.get("confidence") == "low":
            low.append(f"{co}: {site or '(no site)'} — {f.get('city', '')}, {f.get('state', '')}, "
                       f"{f.get('country', '')} ({f.get('source', '')})")
    save(args.run_dir, rows)
    left = sorted({r["Company"] for r in rows if r.get("Company") and
                   not (r.get("Company Website") and r.get("Company Country"))})
    print(f"updated {done} companies; {len(left)} still missing a website or country")
    if low:
        print("low confidence — confirm with the user:\n  " + "\n  ".join(low))
    if unknown:
        print("not in event.csv (check the spelling): " + ", ".join(unknown))
    if left:
        print("still missing: " + ", ".join(left[:40]))


def export(args):
    rows = load(args.run_dir)
    out = []
    for r in rows:
        loc = ", ".join(x for x in (r.get("Company City"), r.get("Company State"), r.get("Company Country")) if x)
        out.append({"First Name": r["First Name"], "Last Name": r["Last Name"], "Job Title": r["Job Title"],
                    "Company Name": r["Company"], "Email": r.get("Email", ""), "Phone": r.get("Phone", ""),
                    "Linkedin URL Public": r.get("LinkedIn URL", ""), "Company Website URL": r.get("Company Website", ""),
                    "Company Location": loc, "Company Country": r.get("Company Country", ""),
                    "Event Name": r.get("Event Name", ""), "Event Source": r.get("Source", ""),
                    "Event Row ID": r["Row ID"]})
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{args.out}: {len(out)} people at {len({r['Company'] for r in rows})} companies, ready for "
          "linkedin-list-screening init")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("--run-dir", required=True); p.set_defaults(func=plan)
    p = sub.add_parser("apply"); p.add_argument("--run-dir", required=True); p.add_argument("--file", required=True)
    p.set_defaults(func=apply)
    p = sub.add_parser("export"); p.add_argument("--run-dir", required=True); p.add_argument("--out", required=True)
    p.set_defaults(func=export)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

"""Company-only event lists, branch B: companies with job titles but no names.

ZoomInfo is searched (free) at each company for each listed title; the user
chooses who to keep (several people with one title, a better title, or nobody
— always the user's call). Titles nobody was chosen for go to the finder page:
the user searches the web, pastes the LinkedIn URL and types the name.

  search-plan    --run-dir <run_dir>          zi/title_search_plan.json (search_contacts queries)
  search-ingest  --run-dir <run_dir> --target <T…> --response <file>
  candidates     --run-dir <run_dir>          candidates per company and title, to show the user
  choose         --run-dir <run_dir> --decisions <json>   {"<T…>": ["<personId>", …] or []}
  finder         --run-dir <run_dir> [--title "<event>"]  title_finder.html for titles with nobody chosen
  finder-apply   --run-dir <run_dir> --code <code> | --confirm
  enrich-plan    --run-dir <run_dir>          enrich_contacts batches (chosen personIds + finder people
                                              by name + company + LinkedIn) and the MAXIMUM credits
  enrich-ingest  --run-dir <run_dir> --batch <n> --response <file>
  build-contacts --run-dir <run_dir> --out <file.csv>
                 One contact file in ZoomInfo's column names (company data from the
                 web research, Event Name on every row) for outbound-list-cleaner:
                 worksheet.py init --contacts <file.csv>, then steps 1–6.
"""
import argparse
import base64
import csv
import hashlib
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from company_list import COMPANY_COLS, TARGET_COLS, number, p_companies, p_targets, read_csv  # noqa: E402

sys.path.insert(0, str(HERE.parents[1] / "outbound-list-cleaner" / "scripts"))
from zoominfo_merge import TITLE_ABBR, first_val, name_ok, paired_records, same_query, same_title, walk_records  # noqa: E402

BATCH = 10
ENRICH_FIELDS = ["firstName", "lastName", "email", "jobTitle", "companyName", "zoominfoCompanyId", "externalUrls",
                 "managementLevel", "jobFunction", "phone", "mobilePhone", "contactAccuracyScore"]


def zi(run):
    d = Path(run) / "zi"
    d.mkdir(exist_ok=True)
    return d


def live(run):
    cos = {c["Company ID"]: c for c in read_csv(p_companies(run), COMPANY_COLS) if c["Status"] != "excluded"}
    ts = [t for t in read_csv(p_targets(run), TARGET_COLS) if t["Company ID"] in cos]
    return cos, ts


def search_plan(args):
    cos, ts = live(args.run_dir)
    plan = []
    for t in ts:
        co = cos[t["Company ID"]]
        words = re.sub(r"[^A-Za-z ]", " ", t["Job Title"]).split()
        title = " ".join(TITLE_ABBR.get(w.lower(), w).title() if len(w) <= 4 and w.lower() in TITLE_ABBR else w for w in words)
        q = {"companyName": co["Company"], "jobTitleList": [title],
             "pageSize": 10}
        if co["Website"]:
            q["companyWebsite"] = co["Website"]
        plan.append({"target": t["Target ID"], "company": co["Company"], "title": t["Job Title"], "query": q})
    (zi(args.run_dir) / "title_search_plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False))
    print(f"{len(plan)} title searches (no credits) -> zi/title_search_plan.json. Run each with search_contacts "
          "(nothing back: retry once without companyWebsite), then search-ingest --target <T…> --response <file>.")


def search_ingest(args):
    data = json.loads(Path(args.response).read_text())
    (zi(args.run_dir) / f"tsearch_{args.target}.json").write_text(json.dumps(data, ensure_ascii=False))
    print(f"saved {args.target}: {len(walk_records(data, ('firstName', 'lastName')))} candidates")


def cand(z):
    a = z.get("attributes", z)
    co = a.get("company") if isinstance(a.get("company"), dict) else {}
    return {"personId": str(z.get("id") or a.get("id") or ""), "name": f"{a.get('firstName', '')} {a.get('lastName', '')}".strip(),
            "title": a.get("jobTitle", ""), "company": co.get("name") or a.get("companyName", ""),
            "accuracy": a.get("contactAccuracyScore", "")}


def candidates(args):
    cos, ts = live(args.run_dir)
    out, lines = {}, []
    for co_id, co in cos.items():
        mine = [t for t in ts if t["Company ID"] == co_id]
        if not mine:
            continue
        lines.append(f"\n## {co['Company']} ({co['City']}, {co['State']}, {co['Country']})")
        for t in mine:
            f = zi(args.run_dir) / f"tsearch_{t['Target ID']}.json"
            if not f.exists():
                lines.append(f"- {t['Target ID']} “{t['Job Title']}”: not searched yet")
                continue
            data = json.loads(f.read_text())
            items = data.get("data", data) if isinstance(data, dict) else data
            cs = [cand(z) for z in (items if isinstance(items, list) else [])]
            out[t["Target ID"]] = cs
            lines.append(f"- {t['Target ID']} “{t['Job Title']}”: " + ("no one found" if not cs else ""))
            for c in cs:
                tag = "same title" if same_title(t["Job Title"], c["title"]) else "different title"
                lines.append(f"    {c['personId']}: {c['name']} — {c['title']} ({tag}; accuracy {c['accuracy']})")
    (zi(args.run_dir) / "title_candidates.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print("\n".join(lines))
    print("\nShow these to the user company by company. They choose who to keep (more than one, someone with a "
          "better title, or nobody). Write {\"<T…>\": [\"<personId>\", …]} and run choose --decisions <file>.")


def choose(args):
    dec = json.loads(Path(args.decisions).read_text())
    cands = json.loads((zi(args.run_dir) / "title_candidates.json").read_text())
    known = {c["personId"]: c for cs in cands.values() for c in cs}
    bad = [p for ps in dec.values() for p in ps if p not in known]
    if bad:
        raise SystemExit(f"these personIds weren't among the candidates: {bad}")
    (zi(args.run_dir) / "title_choices.json").write_text(json.dumps(dec, indent=1))
    _, ts = live(args.run_dir)
    nobody = [t["Target ID"] for t in ts if not dec.get(t["Target ID"])]
    print(f"{sum(len(v) for v in dec.values())} people chosen; {len(nobody)} titles with nobody -> finder page")


def finder(args):
    cos, ts = live(args.run_dir)
    ch_file = zi(args.run_dir) / "title_choices.json"
    chosen = json.loads(ch_file.read_text()) if ch_file.exists() else {}
    items = [{"row": t["Target ID"], "title": t["Job Title"], "company": cos[t["Company ID"]]["Company"],
              "website": cos[t["Company ID"]]["Website"],
              "hq": ", ".join(x for x in (cos[t["Company ID"]]["City"], cos[t["Company ID"]]["State"],
                                          cos[t["Company ID"]]["Country"]) if x)}
             for t in ts if not chosen.get(t["Target ID"])]
    (zi(args.run_dir) / "title_finder.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    rid = hashlib.sha1(json.dumps([i["row"] for i in items]).encode()).hexdigest()[:10]
    page = (HERE / "title_finder_template.html").read_text(encoding="utf-8") \
        .replace("__TITLE__", html.escape(args.title or "Find the people")).replace("__ID__", rid) \
        .replace("__PEOPLE__", json.dumps(items, ensure_ascii=False).replace("</", "<\\/"))
    (Path(args.run_dir) / "title_finder.html").write_text(page, encoding="utf-8")
    print(f"title_finder.html: {len(items)} titles to find")


def finder_apply(args):
    d = zi(args.run_dir)
    pending = d / "title_finder_pending.json"
    if args.confirm:
        if not pending.exists():
            raise SystemExit("nothing pending — paste the code first")
        pending.rename(d / "title_finder_people.json")
        ppl = json.loads((d / "title_finder_people.json").read_text())
        print(f"saved {sum(1 for p in ppl.values() if p.get('linkedin'))} people; "
              f"{sum(1 for p in ppl.values() if not p.get('linkedin'))} not found (stay unenriched)")
        return
    code = (args.code or "").strip()
    if not code.startswith("LT1:"):
        raise SystemExit("that isn't a finder code — ask the user to copy it again")
    try:
        data = json.loads(base64.b64decode(code[4:]).decode("utf-8"))
    except Exception:
        raise SystemExit("the code is incomplete — ask the user to copy it again")
    items = {i["row"]: i for i in json.loads((d / "title_finder.json").read_text())}
    out = {}
    for rid, v in data.items():
        if rid not in items:
            continue
        m = re.search(r"linkedin\.com/in/([^/?#\s]+)", v.get("url", ""), re.I)
        out[rid] = {"linkedin": f"https://www.linkedin.com/in/{m.group(1).rstrip('/')}" if m else "",
                    "first": v.get("first", "").strip(), "last": v.get("last", "").strip()}
    pending.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print("PREVIEW — nothing saved yet:")
    for rid, p in out.items():
        i = items[rid]
        print(f"{i['title']} @ {i['company']} | " + (f"{p['first']} {p['last']} — {p['linkedin']}" if p["linkedin"]
                                                     else "can't find"))
    print(f"{len(items) - len(out)} not done. After the user's OK: finder-apply --confirm")


def enrich_plan(args):
    cos, ts = live(args.run_dir)
    d = zi(args.run_dir)
    chosen = json.loads((d / "title_choices.json").read_text()) if (d / "title_choices.json").exists() else {}
    found = json.loads((d / "title_finder_people.json").read_text()) if (d / "title_finder_people.json").exists() else {}
    tmap = {t["Target ID"]: t for t in ts}
    items = []
    for tid, pids in chosen.items():
        for pid in pids:
            items.append({"target": tid, "kind": "zoominfo", "query": {"personId": str(pid)}})
    for tid, p in found.items():
        if p.get("linkedin") and tid in tmap:
            q = {"firstName": p["first"], "lastName": p["last"], "companyName": cos[tmap[tid]["Company ID"]]["Company"],
                 "externalURL": p["linkedin"]}
            items.append({"target": tid, "kind": "finder", "query": q})
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
    (d / "title_enrich_plan.json").write_text(json.dumps({"batches": batches, "required_fields": ENRICH_FIELDS},
                                                         indent=1, ensure_ascii=False))
    todo = [i for i in range(len(batches)) if not (d / f"tenrich_{i}.json").exists()]
    print(f"{len(items)} people to enrich in {len(batches)} calls — MAXIMUM credits: {len(items)} (anyone enriched "
          f"in the last year is free). Get the user's OK first. Still to run: {todo or 'none'}")


def enrich_ingest(args):
    data = json.loads(Path(args.response).read_text())
    (zi(args.run_dir) / f"tenrich_{args.batch}.json").write_text(json.dumps(data, ensure_ascii=False))
    print(f"saved enrich batch {args.batch}: {len(paired_records(data))} answers")


OUT = ["ZoomInfo Contact ID", "First Name", "Last Name", "Job Title", "Management Level", "Job Function",
       "Email Address", "Email Domain", "Direct Phone Number", "Mobile phone", "LinkedIn Contact Profile URL",
       "ZoomInfo Company ID", "Company Name", "Website", "Employees", "Revenue (in USD)", "Company City",
       "Company State", "Company Country", "Event Name", "Source List Type"]


def build_contacts(args):
    cos, ts = live(args.run_dir)
    d = zi(args.run_dir)
    tmap = {t["Target ID"]: t for t in ts}
    plan = json.loads((d / "title_enrich_plan.json").read_text())
    found = json.loads((d / "title_finder_people.json").read_text()) if (d / "title_finder_people.json").exists() else {}
    rows, used_finder, n = [], set(), 0
    for i, batch in enumerate(plan["batches"]):
        f = d / f"tenrich_{i}.json"
        pairs = paired_records(json.loads(f.read_text())) if f.exists() else []
        for item in batch:
            t = tmap[item["target"]]
            co = cos[t["Company ID"]]
            z = next((dd for inp, dd in pairs if same_query(inp, item["query"])), None)
            z = z if z and z.get("success", True) is not False else None
            if item["kind"] == "finder":
                used_finder.add(item["target"])
                p = found[item["target"]]
                if z and name_ok(p["first"], p["last"], first_val(z, "firstName"), first_val(z, "lastName")) != "yes":
                    z = None  # ZoomInfo found someone else
            if item["kind"] == "zoominfo" and not z:
                continue  # chosen person couldn't be enriched
            n += 1
            title = t["Job Title"]
            if z and first_val(z, "jobTitle") and (item["kind"] == "zoominfo" or same_title(title, first_val(z, "jobTitle"))):
                title = first_val(z, "jobTitle")
            li = next((u for u in first_val(z, "externalUrls").split("; ") if "linkedin.com/in/" in u.lower()), "") if z else ""
            email = first_val(z, "email") if z else ""
            p = found.get(item["target"], {}) if item["kind"] == "finder" else {}
            rows.append({
                "ZoomInfo Contact ID": f"EVC-{item['target']}-{n}",
                "First Name": first_val(z, "firstName") if z else p.get("first", ""),
                "Last Name": first_val(z, "lastName") if z else p.get("last", ""),
                "Job Title": title, "Management Level": first_val(z, "managementLevel") if z else "",
                "Job Function": first_val(z, "jobFunction") if z else "",
                "Email Address": email, "Email Domain": email.split("@")[-1].lower() if "@" in email else "",
                "Direct Phone Number": "" if (z or {}).get("directPhoneDoNotCall") is True else (first_val(z, "phone") if z else ""),
                "Mobile phone": "" if (z or {}).get("mobilePhoneDoNotCall") is True else (first_val(z, "mobilePhone") if z else ""),
                "LinkedIn Contact Profile URL": p.get("linkedin") or li,
                "ZoomInfo Company ID": co["Company ID"], "Company Name": co["Company"], "Website": co["Website"],
                "Employees": number(co["Employees"], "emp"), "Revenue (in USD)": number(co["Revenue"], "rev"),
                "Company City": co["City"], "Company State": co["State"], "Company Country": co["Country"],
                "Event Name": co["Event Name"], "Source List Type": "Event"})
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT)
        w.writeheader()
        w.writerows(rows)
    print(f"{args.out}: {len(rows)} contacts at {len({r['Company Name'] for r in rows})} companies "
          f"({len(used_finder)} found through the finder page)")
    print(f"next: python3 <outbound-list-cleaner>/scripts/worksheet.py init --contacts {args.out} --out-dir <run_dir>, "
          "then steps 1–6")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, func in (("search-plan", search_plan), ("candidates", candidates), ("enrich-plan", enrich_plan)):
        p = sub.add_parser(name); p.add_argument("--run-dir", required=True); p.set_defaults(func=func)
    p = sub.add_parser("search-ingest"); p.add_argument("--run-dir", required=True); p.add_argument("--target", required=True)
    p.add_argument("--response", required=True); p.set_defaults(func=search_ingest)
    p = sub.add_parser("choose"); p.add_argument("--run-dir", required=True); p.add_argument("--decisions", required=True)
    p.set_defaults(func=choose)
    p = sub.add_parser("finder"); p.add_argument("--run-dir", required=True); p.add_argument("--title"); p.set_defaults(func=finder)
    p = sub.add_parser("finder-apply"); p.add_argument("--run-dir", required=True); p.add_argument("--code")
    p.add_argument("--confirm", action="store_true"); p.set_defaults(func=finder_apply)
    p = sub.add_parser("enrich-ingest"); p.add_argument("--run-dir", required=True); p.add_argument("--batch", type=int, required=True)
    p.add_argument("--response", required=True); p.set_defaults(func=enrich_ingest)
    p = sub.add_parser("build-contacts"); p.add_argument("--run-dir", required=True); p.add_argument("--out", required=True)
    p.set_defaults(func=build_contacts)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

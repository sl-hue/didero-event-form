"""Web research in parallel: split the list between helper agents, then merge what they found.

One helper researching a whole list one company after another was the slowest part of a run. This
script splits the research into helper briefs sized to the work (HELPERS — how much one helper takes;
the number of helpers follows from the list) and merges their answers into the file the step applies.
Lists of 20 contacts or fewer are done in the main chat, without helpers.

  brief --run-dir <run_dir> --kind <kind>    writes research/<kind>/brief_<k>.md and prints the helper
                                             briefs to start ALL AT ONCE (one message, every helper)
  merge --run-dir <run_dir> --kind <kind>    merges the helpers' result files into research/<kind>.json,
                                             lists anything missing (re-run brief: only those) and prints
                                             the apply command

  kinds            items from                                  apply with
  companies-screen screen/screening.csv (no Company Fit yet)   screen.py apply-research --file research/companies-screen.json
  companies-hq     companies_todo.json (companies.py /         companies.py apply (event lists) or
                   company_list.py plan)                       company_list.py apply (contact sourcing) --file research/companies-hq.json
  titles           screen/screening.csv (Title Fit not "fit")  screen.py set-title --file research/titles.json
"""
import argparse
import csv
import json
import math
import shlex
from pathlib import Path

HERE = Path(__file__).resolve().parent
SMALL = 20  # contacts: up to this many, the main chat does the work itself

# How much one helper takes for each kind of research — a size that one helper finishes well and
# quickly; the number of helpers follows from the list (never a fixed count).
HELPERS = {"companies-screen": 8, "companies-hq": 10, "titles": 40}

RULES = {
    "companies-screen": """For each company, research on the web (company site first, then reliable sources):
- what it does, HQ country, and **every country where it has a real presence** (offices, plants,
  warehouses, distribution — e.g. a Canadian company with US plants is present in the US), size;
- whether it fits Didero's ICP: manufacturers and physical-goods companies with real supply chains
  (distributors of physical goods count; pure software, services, retail stores, finance don't).
Answer per company: {"fit": "fit|unclear|no", "reason": "<one line>", "hq_country": "<country>",
"presence": ["<country>", ...]}. Unsure → "unclear" with the reason; never guess a country.""",
    "companies-hq": """For each company, find the **website** first (the company's own site — not a LinkedIn
page, Linktree, careers page or directory; same-name companies: the email domains given decide), then
the **HQ city, state and country** from the site (contact / about / locations page) or a reliable
source, and employees / revenue only if published (exact numbers; a range only if that's all there is).
Answer per company: {"website": "", "city": "", "state": "", "country": "", "employees": "",
"revenue": "", "source": "<url>", "confidence": "high|medium|low"}. Leave a field blank when unsure.""",
    "titles": """For each row, judge whether the job title is a Didero target role: procurement, purchasing,
sourcing, supply chain, operations, logistics, materials, MRO and related leadership, at manager level or
above (or a clear buyer / planner role). Many target roles use other words ("Integrated Supply",
"Commodities", "Procure to Pay", "MRO"). Answer per row: {"fit": "fit|unclear|no", "reason": "<one line>"}.""",
}


def contacts_in_run(run):
    try:
        import sys
        sys.path.insert(0, str(HERE))
        from setup import load_setup
        return int((load_setup(run) or {}).get("contacts") or 0) or rows_in_list(run)
    except Exception:  # noqa: BLE001
        return rows_in_list(run)


def rows_in_list(run):
    """Contacts in the list when run_setup.json doesn't say: the working / screening / event file's rows."""
    for name in ("working.csv", "screen/screening.csv", "event.csv", "companies.csv"):
        p = Path(run) / name
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return max(0, sum(1 for _ in csv.reader(f)) - 1)
    return 0


def helper_count(n_items, per, contacts):
    """No helpers for small lists (<= SMALL contacts); otherwise enough helpers that each takes about `per`."""
    size = contacts or n_items
    if size <= SMALL or n_items <= 1:
        return 0
    return max(2, math.ceil(n_items / per))


def items(run, kind):
    """[(key, context dict)] still to research."""
    if kind in ("companies-screen", "titles"):
        p = run / "screen" / "screening.csv"
        rows = list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []
        if kind == "titles":
            return [(r["Row ID"], {"title": r.get("Title", ""), "company": r.get("Company", "")})
                    for r in rows if r.get("Title Fit") != "fit"]
        seen = {}
        for r in rows:
            if r.get("Company") and not r.get("Company Fit") and r["Company"] not in seen:
                seen[r["Company"]] = {k: v for k, v in (("country_in_list", r.get("Company Country", "")),
                                                        ("example_title", r.get("Title", ""))) if v}
        return list(seen.items())
    todo = json.loads((run / "companies_todo.json").read_text())
    return [(t["company"], {k: v for k, v in t.items() if k != "company"}) for t in todo]


def out_dir(run, kind):
    d = run / "research" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def done_keys(d):
    keys = set()
    for f in d.glob("result_*.json"):
        try:
            keys |= set(json.loads(f.read_text()))
        except ValueError:
            pass
    return keys


def brief(args):
    run = Path(args.run_dir).resolve()
    d = out_dir(run, args.kind)
    todo = [x for x in items(run, args.kind) if x[0] not in done_keys(d)]
    for old in d.glob("brief_*.md"):
        old.unlink()
    if not todo:
        print(f"{args.kind}: nothing left to research — run merge.")
        return
    n = helper_count(len(todo), HELPERS[args.kind], contacts_in_run(run))
    groups = [todo] if n == 0 else [todo[k::n] for k in range(n)]
    start = len(list(d.glob("result_*.json")))
    files = []
    for k, g in enumerate(groups, start + 1):
        res = d / f"result_{k}.json"
        text = (f"# Research helper {k} — {len(g)} {args.kind.replace('-', ' ')} (read-only web research)\n\n"
                f"{RULES[args.kind]}\n\nWrite ONE JSON object to `{res}` with the Write tool: one entry per item "
                "below, keyed exactly as given. Then reply with one line only: how many you answered and how "
                "many are unclear (no company or contact details in the reply).\n\n## Items\n```json\n"
                + json.dumps({key: ctx for key, ctx in g}, indent=1, ensure_ascii=False) + "\n```\n")
        f = d / f"brief_{k}.md"
        f.write_text(text, encoding="utf-8")
        files.append((f, len(g)))
    if n == 0:
        print(f"{args.kind}: {len(todo)} items, a small list — do it yourself (no helpers): read {files[0][0]} and "
              f"follow it, then merge.")
        return
    print(f"{args.kind}: {len(todo)} items split between {len(files)} helpers (~{HELPERS[args.kind]} each). Start them "
          f"ALL AT ONCE — one message with {len(files)} helper (sub-agent) calls, each with this brief:")
    for f, c in files:
        print(f'  - "Read {f} and do exactly what it says. Reply with one line only." ({c} items)')
    print(f"When they're back: research_workers.py merge --run-dir {shlex.quote(str(run))} --kind {args.kind}")


def merge(args):
    run = Path(args.run_dir).resolve()
    d = out_dir(run, args.kind)
    merged = {}
    for f in sorted(d.glob("result_*.json")):
        try:
            merged.update(json.loads(f.read_text()))
        except ValueError as e:
            print(f"  {f.name}: not valid JSON ({e}) — that helper's items count as missing")
    wanted = [k for k, _ in items(run, args.kind)]
    missing = [k for k in wanted if k not in merged]
    out = run / "research" / f"{args.kind}.json"
    out.write_text(json.dumps(merged, indent=1, ensure_ascii=False))
    print(f"{args.kind}: {len(merged)} answers merged -> {out}" + (f"; {len(missing)} missing — re-run brief (it "
          "writes briefs for those only)" if missing else ""))
    rd = shlex.quote(str(run))
    apply = {"companies-screen": f"screen.py apply-research --run-dir {rd}/screen --file {shlex.quote(str(out))}",
             "titles": f"screen.py set-title --run-dir {rd}/screen --file {shlex.quote(str(out))}",
             "companies-hq": f"companies.py apply (event lists) / company_list.py apply (contact sourcing) "
                             f"--run-dir {rd} --file {shlex.quote(str(out))}"}[args.kind]
    print(f"then: python3 scripts/{apply}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, func in (("brief", brief), ("merge", merge)):
        p = sub.add_parser(name); p.add_argument("--run-dir", required=True)
        p.add_argument("--kind", required=True, choices=list(HELPERS)); p.set_defaults(func=func)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

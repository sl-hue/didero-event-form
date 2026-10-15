"""Step tracker: keeps the skill's instructions in front of Claude for the whole run.

In long chats Claude forgot the step instructions and skipped or improvised steps
(cleaning skipped, ZoomInfo URLs and import/Clay instructions left out). So the
order lives in a file and every step's instructions are printed fresh from the
reference pages, right when the step starts.

  start   --run-dir <run_dir> --list-type zoominfo|linkedin|event-contacts|event-companies|event-companies-titles|other
          Writes progress.json with the steps for that list type and prints step 1.
  next    --run-dir <run_dir>    Prints the current step: its full instructions (read from the
                                 reference page now), the HubSpot / Clay pages to open in the
                                 browser, and the standing rules.
  done    --run-dir <run_dir> --step <id> [--note "..."]   Marks it done and prints the next step.
  status  --run-dir <run_dir>    The checklist.
  skip    --run-dir <run_dir> --step <id> --reason "..."   Only when the user said to skip it.
"""
import argparse
import datetime
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "references"
END = re.compile(r"^(## |\*\*(\d+\.\s|Stage \d+|Branch [AB]|Mixed lists|ZoomInfo\*\*|LinkedIn URL finder|"
                 r"Job titles on event))")

# (file, line the section starts with)
S = {
    "z1": ("zoominfo-lists.md", "## Step 1 — Email domain cleaning"),
    "z2": ("zoominfo-lists.md", "## Step 2 — Normalization"),
    "z3": ("zoominfo-lists.md", "## Step 3 — HubSpot duplicate check"),
    "z4": ("zoominfo-lists.md", "## Step 4 — HubSpot import"),
    "z4b": ("zoominfo-lists.md", "## Step 4 (after the import)"),
    "z5": ("zoominfo-lists.md", "## Step 5 — Enrichment in Clay"),
    "z6": ("zoominfo-lists.md", "## Step 6 — Assign BDRs"),
    "zirun": ("zoominfo-lists.md", "## Running ZoomInfo calls"),
    "st7": ("zoominfo-lists.md", "**Stage 7 — ZoomInfo pull**"),
    "st8": ("zoominfo-lists.md", "**Stage 8 — pick the source per field**"),
    "st9": ("zoominfo-lists.md", "**Stage 9 — consistency**"),
    "st10": ("zoominfo-lists.md", "**Stage 10 — prune**"),
    "st11": ("zoominfo-lists.md", "**Stage 11 — steps 1–2 again.**"),
    "evzi": ("zoominfo-lists.md", "**ZoomInfo** (`zoominfo-puller`)"),
    "evlf": ("zoominfo-lists.md", "**LinkedIn URL finder**"),
    "evtitle": ("zoominfo-lists.md", "**Job titles on event lists:**"),
    "sc1": ("screening.md", "**1. Load the list**"),
    "sc2": ("screening.md", "**2. Multiple current jobs**"),
    "sc3": ("screening.md", "**3. Research and review companies"),
    "sc4": ("screening.md", "**4. Geography**"),
    "sc5": ("screening.md", "**5. User review"),
    "sc6": ("screening.md", "**6. Clean job titles and company names**"),
    "sc7": ("screening.md", "**7. Hand-off"),
    "ev1": ("event-lists.md", "**1. Every source first**"),
    "ev2": ("event-lists.md", "**2. Load the essentials**"),
    "ev3": ("event-lists.md", "**3. Company website, then HQ**"),
    "evhs": ("event-lists.md", "## HubSpot company lookup"),
    "ev4": ("event-lists.md", "**4. Hand over to screening**"),
    "ev5": ("event-lists.md", "**5. Event in HubSpot"),
    "co1": ("event-lists.md", "**1. Collect the companies**"),
    "co2": ("event-lists.md", "**2. HubSpot first, then web research**"),
    "co3": ("event-lists.md", "**3. Drop non-target countries**"),
    "co4": ("event-lists.md", "**4. Clean the company names**"),
    "coA": ("event-lists.md", "**Branch A — no job titles"),
    "coB": ("event-lists.md", "**Branch B — job titles but no names"),
}
HS = "https://app.hubspot.com"
OPEN = {  # pages to open in the browser window when the step starts ({p} = portal id)
    "z3": [("HubSpot companies (merges happen here)", HS + "/contacts/{p}/objects/0-2/views/all/list"),
           ("HubSpot contacts", HS + "/contacts/{p}/objects/0-1/views/all/list")],
    "z4": [("HubSpot import", HS + "/import/{p}")],
    "z4b": [("HubSpot segments", HS + "/contacts/{p}/objectLists/views/all")],
    "z5": [("Clay — Americas / global template", "{clay_americas}"), ("Clay — Europe template", "{clay_europe}")],
    "z6": [("HubSpot segments", HS + "/contacts/{p}/objectLists/views/all")],
}
TAIL = [("z1", "Step 1 — email domains", ["z1"]), ("z2", "Step 2 — normalization + cleaning (names, company names, "
         "titles, HubSpot values)", ["z2"]), ("z3", "Step 3 — HubSpot duplicate check", ["z3"]),
        ("z4", "Step 4 — HubSpot import (upload files + HOW_TO_IMPORT.md; the user imports)", ["z4"]),
        ("z4b", "Step 4 after import — segment, associations, leftover duplicates", ["z4b"]),
        ("z5", "Step 5 — Clay (clay_guide.py first)", ["z5"]), ("z6", "Step 6 — BDR assignment", ["z6"])]
SECOND = [("z1b", "Steps 1–2 again — only what's new", ["st11", "z1", "z2"])]
FLOWS = {
    "zoominfo": TAIL,
    "linkedin": [("sc1", "Load the list", ["sc1"]), ("sc2", "Multiple current jobs", ["sc2"]),
                 ("sc3", "Research + review companies, then contacts", ["sc3", "sc4", "sc5"]),
                 ("sc6", "Title and company name cleaning", ["sc6"]), ("sc7", "Hand-off into the working file", ["sc7"]),
                 ("z1a", "Steps 1–2 (email domains, normalization + cleaning)", ["z1", "z2"]),
                 ("st7", "ZoomInfo pull (max credits first; parallel)", ["st7", "zirun"]),
                 ("st8", "Pick the source per field", ["st8"]), ("st9", "Consistency", ["st9"]),
                 ("st10", "Prune columns", ["st10"])] + SECOND + TAIL[2:],
    "event-contacts": [("ev1", "Collect every source", ["ev1"]), ("ev2", "Load the essentials", ["ev2"]),
                       ("ev3", "Company website + HQ: HubSpot first, then web research", ["ev3", "evhs"]),
                       ("ev4", "Screening (companies, then contacts), cleaning, hand-off",
                        ["ev4", "sc1", "sc3", "sc4", "sc5", "sc6", "sc7"]),
                       ("z1a", "Steps 1–2 (email domains, normalization + cleaning)", ["z1", "z2"]),
                       ("evzi", "ZoomInfo: free search → pick → enrich (parallel)", ["evzi", "zirun", "evtitle"]),
                       ("evlf", "LinkedIn URL finder", ["evlf"]),
                       ("st8", "Source per field, consistency, prune", ["st8", "st9", "st10"])]
                      + SECOND + [("ev5", "Event in HubSpot: Lead Source + Lead Source Detail 1", ["ev5"])] + TAIL[2:],
    "event-companies": [("co1", "Collect the companies", ["co1"]),
                        ("co2", "HubSpot first, then web research", ["co2", "evhs"]),
                        ("co3", "Drop non-target countries", ["co3"]), ("co4", "Clean company names", ["co4"]),
                        ("coA", "Branch A: ZoomInfo upload + guide → export processed as a ZoomInfo list", ["coA"])]
                       + TAIL,
    "event-companies-titles": [("co1", "Collect the companies + titles", ["co1"]),
                               ("co2", "HubSpot first, then web research", ["co2", "evhs"]),
                               ("co3", "Drop non-target countries", ["co3"]), ("co4", "Clean company names", ["co4"]),
                               ("coB", "Branch B: ZoomInfo per title → user chooses → finder → enrich (parallel)",
                                ["coB", "zirun"])] + TAIL,
    "other": TAIL,
}
RULES = """STANDING RULES (every step):
- Do exactly what the instructions above say, in order. Don't work from memory; if this step's text
  and your memory disagree, the text wins.
- Never import or create list records in HubSpot through the connector. No creating or updating
  contacts/companies from the list with manage_crm_objects or any other tool: the user imports the
  upload files. The connector only reads, plus the two approved updates of step 4 (association
  fixes) and step 6 (owners), each after the user's OK.
- When the user has to do something in HubSpot or Clay, OPEN the page in the browser window
  (Claude in Chrome / the built-in browser), don't just paste a link. No browser tool -> paste the
  link and say the browser isn't available.
- ZoomInfo calls: zi_workers.py + sub-agents started at once.
- Show what changed and wait for the user's OK, then: progress.py done --step <id>."""


def section(key):
    f, start = S[key]
    lines = (REF / f).read_text(encoding="utf-8").splitlines()
    i = next((n for n, l in enumerate(lines) if l.startswith(start)), None)
    if i is None:
        return f"[section '{start}' not found in references/{f} — read the file]"
    out = [lines[i]]
    for l in lines[i + 1:]:
        if END.match(l):
            break
        out.append(l)
    return f"--- references/{f} ---\n" + "\n".join(out).strip()


def load(run):
    return json.loads((Path(run) / "progress.json").read_text())


def save(run, p):
    (Path(run) / "progress.json").write_text(json.dumps(p, indent=1))


def show(run):
    p = load(run)
    todo = [s for s in p["steps"] if s["state"] == "todo"]
    if not todo:
        print("All steps done. The workflow ends here.")
        return
    s = todo[0]
    n = p["steps"].index(s) + 1
    cfg = json.loads((ROOT / "config.json").read_text())
    fill = {"p": cfg.get("hubspot_portal_id", ""), "clay_americas": cfg["clay_workbooks"]["americas_global"]["url"],
            "clay_europe": cfg["clay_workbooks"]["europe"]["url"]}
    print(f"=== STEP {n} of {len(p['steps'])} [{s['id']}] — {s['title']} ===  (list type: {p['list_type']})\n")
    print("Read and follow these instructions exactly:\n")
    for k in s["refs"]:
        print(section(k) + "\n")
    opens = OPEN.get(s["id"], [])
    if opens:
        print("OPEN IN THE BROWSER WINDOW NOW (not just a link):")
        for label, url in opens:
            print(f"  - {label}: {url.format(**fill)}")
        print()
    print(RULES)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("start", "next", "done", "status", "skip"):
        x = sub.add_parser(name)
        x.add_argument("--run-dir", required=True)
        if name == "start":
            x.add_argument("--list-type", required=True, choices=list(FLOWS))
        if name in ("done", "skip"):
            x.add_argument("--step", required=True)
            x.add_argument("--note", default="")
            x.add_argument("--reason", default="")
    a = ap.parse_args()
    run = Path(a.run_dir)
    if a.cmd == "start":
        run.mkdir(parents=True, exist_ok=True)
        steps = [{"id": i, "title": t, "refs": r, "state": "todo"} for i, t, r in FLOWS[a.list_type]]
        save(run, {"list_type": a.list_type, "started": datetime.datetime.now().isoformat(timespec="seconds"),
                   "steps": steps})
        print(f"{len(steps)} steps for a {a.list_type} list:")
        for n, s in enumerate(steps, 1):
            print(f"  {n}. {s['title']}")
        print()
        show(run)
    elif a.cmd == "next":
        show(run)
    elif a.cmd == "status":
        for n, s in enumerate(load(run)["steps"], 1):
            mark = {"todo": "[ ]", "done": "[x]", "skipped": "[-]"}[s["state"]]
            print(f"{mark} {n}. {s['title']}" + (f" — {s.get('note')}" if s.get("note") else ""))
    else:
        p = load(run)
        s = next((x for x in p["steps"] if x["id"] == a.step), None)
        if not s:
            raise SystemExit(f"no step {a.step}; steps: {', '.join(x['id'] for x in p['steps'])}")
        first = next(x for x in p["steps"] if x["state"] == "todo") if any(x["state"] == "todo" for x in p["steps"]) else None
        if a.cmd == "done" and first and first["id"] != a.step:
            raise SystemExit(f"step {a.step} isn't the current one — the current step is {first['id']} "
                             f"({first['title']}). Finish it first (progress.py next).")
        if a.cmd == "skip" and not a.reason:
            raise SystemExit("skip needs --reason (only when the user asked to skip it)")
        s["state"] = "done" if a.cmd == "done" else "skipped"
        s["note"] = a.note or a.reason
        save(run, p)
        print(f"{a.step} {s['state']}.\n")
        show(run)


if __name__ == "__main__":
    main()

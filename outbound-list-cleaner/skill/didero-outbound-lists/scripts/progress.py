"""Step tracker: keeps the skill's instructions in front of Claude for the whole run.

In long chats Claude forgot the step instructions and skipped or improvised steps
(cleaning skipped, ZoomInfo URLs and import/Clay instructions left out). So the
order lives in a file and every step's instructions are printed fresh from the
reference pages, right when the step starts.

  start   --run-dir <run_dir>    Reads run_setup.json (the start answers: path, BDRs, ZoomInfo) and
                                 writes progress.json with the steps; prints step 1.
  next    --run-dir <run_dir>    Prints the current step: its full instructions (read from the
                                 reference page now), the HubSpot / Clay pages to open in the
                                 browser, and the standing rules.
  done    --run-dir <run_dir> --step <id> [--note "..."]   Marks it done and prints the next step.
  status  --run-dir <run_dir>    The checklist.
  There is no skip: every step in the plan runs, in order. `done` checks the step's own output
  (the run log / its files) and refuses a step that didn't actually run.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
REF = ROOT / "references"
END = re.compile(r"^(## |\*\*(\d+\.\s|Stage \d+|Branch [AB]|Mixed lists|ZoomInfo\*\*|LinkedIn URL finder|"
                 r"Job titles on named))")

# (file, line the section starts with)
S = {
    "z1": ("zoominfo-lists.md", "## Step 1 — Email domain cleaning"),
    "z2": ("zoominfo-lists.md", "## Step 2 — Normalization"),
    "z3": ("zoominfo-lists.md", "## Step 3 — HubSpot duplicate check"),
    "own": ("zoominfo-lists.md", "## Step 4 — BDR owners"),
    "z5": ("zoominfo-lists.md", "## Step 5 — HubSpot import"),
    "z6": ("zoominfo-lists.md", "## Step 6 — After the import"),
    "z7": ("zoominfo-lists.md", "## Step 7 — Enrichment in Clay"),
    "zirun": ("zoominfo-lists.md", "## Running ZoomInfo calls"),
    "st7": ("zoominfo-lists.md", "**Stage 7 — ZoomInfo pull**"),
    "st8": ("zoominfo-lists.md", "**Stage 8 — pick the source per field**"),
    "st9": ("zoominfo-lists.md", "**Stage 9 — consistency**"),
    "st10": ("zoominfo-lists.md", "**Stage 10 — prune**"),
    "st11": ("zoominfo-lists.md", "**Stage 11 — steps 1–2 again.**"),
    "evzi": ("zoominfo-lists.md", "**ZoomInfo** (`zoominfo-puller`)"),
    "evtitle": ("zoominfo-lists.md", "**Job titles on named-contact lists:**"),
    "sc1": ("screening.md", "**1. Load the list**"),
    "sc3": ("screening.md", "**2. Research companies and review titles**"),
    "sc4": ("screening.md", "**3. Countries and the decision**"),
    "sc7": ("screening.md", "**4. Hand-off"),
    "ev2": ("event-lists.md", "**1. Load the essentials**"),
    "ev3": ("event-lists.md", "**2. Company website, then HQ**"),
    "evhs": ("event-lists.md", "## HubSpot company lookup"),
    "ev4": ("event-lists.md", "**3. Screening and hand-off**"),
    "ev5": ("event-lists.md", "**4. Event in HubSpot"),
}
HS = "https://app.hubspot.com"
OPEN = {  # pages to open in the browser window when the step starts ({p} = portal id)
    "z5": [("HubSpot import", HS + "/import/{p}")],
    "z6": [("HubSpot segments", HS + "/contacts/{p}/objectLists/views/all")],
    "z7": [("Clay — Americas / global template", "{clay_americas}"), ("Clay — Europe template", "{clay_europe}")],
}
# Steps where the run stops because the user has to do something. Everything else runs straight on.
STOPS = {"z5": "the user imports the two files in HubSpot",
         "z6": "the user builds the segment (and fixes anything the read-only checks find)",
         "z7": "the user runs the Clay buttons"}
OWN = [("own", "Step 4 — BDR owners as upload columns", ["own"])]
TAIL = [("z5", "Step 5 — HubSpot import (USER ACTS)", ["z5"]),
        ("z6", "Step 6 — after the import: segment (USER ACTS) + read-only checks", ["z6"]),
        ("z7", "Step 7 — Clay (USER ACTS)", ["z7"])]
FIRST = [("z1", "Step 1 — email domains", ["z1"]),
         ("z2", "Step 2 — normalization + cleaning (names, company names, titles, HubSpot values)", ["z2"])]
DUPES = [("z3", "Step 3 — HubSpot duplicate check (read-only)", ["z3"])]
SECOND = [("z1b", "Steps 1–2 again (only what's new)", ["st11", "z1", "z2"])]
FLOWS = {
    "zoominfo": FIRST + DUPES,
    "linkedin": [("sc1", "Load the list", ["sc1"]),
                 ("sc3", "Research companies, titles, countries → keep / exclude (Claude decides)", ["sc3", "sc4"]),
                 ("sc7", "Hand-off into the working file", ["sc7"])]
                + [("z1a", "Steps 1–2 (email domains, normalization + cleaning)", ["z1", "z2"])]
                + [("st7", "ZoomInfo pull (credits approved at the start; parallel)", ["st7", "zirun"]),
                   ("st8", "Pick the source per field", ["st8"]), ("st9", "Consistency", ["st9"]),
                   ("st10", "Prune columns", ["st10"])] + SECOND + DUPES,
    "contacts": [("ev2", "Load the essentials", ["ev2"]),
                 ("ev3", "Company website + HQ: HubSpot first, then web research", ["ev3", "evhs"]),
                 ("ev4", "Screening (countries, titles) and hand-off", ["ev4", "sc3", "sc4", "sc7"]),
                 ("z1a", "Steps 1–2 (email domains, normalization + cleaning)", ["z1", "z2"]),
                 ("evzi", "ZoomInfo: free search → pick → enrich (parallel)", ["evzi", "zirun", "evtitle"]),
                 ("st8", "Source per field, consistency, prune", ["st8", "st9", "st10"])] + SECOND + DUPES,
}
RULES = """STANDING RULES (every step):
- Do exactly what the instructions above say, in order. Don't work from memory; if this step's text
  and your memory disagree, the text wins.
- The start questions are answered (run_setup.json). Don't ask the user anything else: judgment calls
  are yours — make them with the rules in the text, and write each one as a line in
  <run_dir>/decisions.md (what, why) for the end-of-run summary.
- Stop only at a USER ACTS step. Everywhere else: report what changed in a line or two and go
  straight on to the next step (progress.py done, then next) — no waiting for an OK.
- Claude never writes to HubSpot: the connector is read-only (no creating, updating, associating,
  merging or owner changes). Everything that changes HubSpot goes into the upload files or is
  done by the user.
- When the user has to do something in HubSpot or Clay, OPEN the page in the browser window
  (Claude in Chrome / the built-in browser), don't just paste a link.
- ZoomInfo calls: zi_workers.py + sub-agents started at once."""
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


# What each reference section leaves behind when it has really run: a run-log action (changes.jsonl;
# "count" = it must have run as many times as the steps so far that include it) or a file.
PROOF = {"z1": ("log", "step1"), "z2": ("log", "step2"), "st7": ("log", "zoominfo_attach"),
         "evzi": ("log", "zoominfo_attach"), "st8": ("log", "merge_sources"), "st9": ("log", "consistency"),
         "st10": ("log", "prune"), "z3": ("log", "step3_contacts"), "own": ("log", "owners"),
         "z5": ("file", "upload/contacts_upload.csv"), "z6": ("file", "segment_snapshot.json"),
         "sc1": ("file", "screen/screening.csv"), "sc4": ("file", "screen/screening_decisions.json"),
         "sc7": ("log", "init"), "ev2": ("file", "event.csv"), "evhs": ("file", "hs/matches.json"),
         "ev5": ("event", "")}


def verify(run, p, step):
    actions = []
    lp = run / "changes.jsonl"
    if lp.exists():
        actions = [json.loads(x).get("action") for x in lp.read_text(encoding="utf-8").splitlines() if x.strip()]
    upto = p["steps"][:p["steps"].index(step) + 1]
    for ref in step["refs"]:
        kind, what = PROOF.get(ref, (None, None))
        if kind == "log":
            need = sum(1 for x in upto if ref in x["refs"])
            if actions.count(what) < need:
                return f"its script hasn't run{' again' if need > 1 else ''} (no '{what}' in the run log)"
            if ref == "z3" and "step3_companies" not in actions:
                return "the company part of the duplicate check hasn't run"
        elif kind == "file" and not (run / what).exists():
            return f"{what} doesn't exist yet"
        elif kind == "event":
            import csv
            w = run / "working.csv"
            rows = list(csv.DictReader(open(w, encoding="utf-8"))) if w.exists() else []
            if rows and not all((r.get("Event Name") or "").strip() for r in rows):
                return "some rows have no Event Name (setup.py set --event-name, then re-run intake / handoff)"
        if ref == "z5" and "export" not in actions:
            return "the upload files weren't exported (hubspot_import.py prepare)"
    return ""


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
    if s["id"] in STOPS:
        print(f"THIS IS A STOP: {STOPS[s['id']]}. Give the user exactly what to do, then wait for them.\n")
    else:
        print("NO STOP: run it, report in a line or two, then progress.py done and go straight on.\n")
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
    for name in ("start", "next", "done", "status"):
        x = sub.add_parser(name)
        x.add_argument("--run-dir", required=True)
        if name == "done":
            x.add_argument("--step", required=True)
            x.add_argument("--note", default="")
    a = ap.parse_args()
    run = Path(a.run_dir)
    if a.cmd == "start":
        from setup import load_setup
        st = load_setup(run)
        if not st:
            raise SystemExit("no run_setup.json — do the start first (setup.py start, the questions, setup.py save)")
        path = st["path"]
        flow = FLOWS[path] + (OWN if st.get("bdr_pool") else []) + TAIL
        if path != "zoominfo" and not st.get("use_zoominfo"):
            flow = [f for f in flow if f[0] not in ("st7", "st8", "st9", "st10", "evzi", "z1b")]
        if st.get("detected") == "event-contacts" or st.get("event_name") or st.get("event_column"):
            flow.insert([x[0] for x in flow].index("z5"), ("ev5", "Event in HubSpot: Lead Source + Detail 1", ["ev5"]))
        steps = [{"id": i, "title": t, "refs": r, "state": "todo"} for i, t, r in flow]
        save(run, {"list_type": path, "started": datetime.datetime.now().isoformat(timespec="seconds"),
                   "steps": steps})
        print(f"{len(steps)} steps ({path} path). The run stops only at: "
              + "; ".join(f"{n}. {s['title']}" for n, s in enumerate(steps, 1) if s["id"] in STOPS))
        for n, s in enumerate(steps, 1):
            print(f"  {n}. {s['title']}")
        print()
        show(run)
    elif a.cmd == "next":
        show(run)
    elif a.cmd == "status":
        for n, s in enumerate(load(run)["steps"], 1):
            mark = {"todo": "[ ]", "done": "[x]"}[s["state"]]
            print(f"{mark} {n}. {s['title']}" + (f" — {s.get('note')}" if s.get("note") else ""))
    else:
        p = load(run)
        s = next((x for x in p["steps"] if x["id"] == a.step), None)
        if not s:
            raise SystemExit(f"no step {a.step}; steps: {', '.join(x['id'] for x in p['steps'])}")
        first = next((x for x in p["steps"] if x["state"] == "todo"), None)
        if a.cmd == "done" and first and first["id"] != a.step:
            raise SystemExit(f"step {a.step} isn't the current one — the current step is {first['id']} "
                             f"({first['title']}). Finish it first (progress.py next).")
        if a.cmd == "done":
            missing = verify(run, p, s)
            if missing:
                raise SystemExit(f"step {a.step} isn't finished — {missing}. Every step runs, in order: do it "
                                 "(progress.py next shows how), then mark it done.")
        s["state"] = "done"
        s["note"] = a.note
        save(run, p)
        print(f"{a.step} {s['state']}.\n")
        show(run)


if __name__ == "__main__":
    main()

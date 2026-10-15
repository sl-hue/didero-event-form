"""Run ZoomInfo calls in parallel: split what's left of a plan between sub-agents.

ZoomInfo calls were the slow part of a run (20–30 minutes each for companies
and contacts) because every call went through the main chat one at a time:
call, save the result, process it, then the next one. This script splits the
calls that are still to do into N instruction files, one per `zoominfo-puller`
sub-agent. The sub-agents run at the same time (contacts and companies
together), save each raw result and ingest it; the main chat only sees one line
per call.

  python3 zi_workers.py --run-dir <run_dir> --job enrich|search [--workers 4]

  enrich        zi/plan.json            (zoominfo_merge.py plan): enrich_contacts + enrich_companies
  search        zi/search_plan.json     (zoominfo_merge.py search-plan): search_contacts, free

Writes zi/workers/<job>_<k>.md and prints the brief to give each sub-agent.
Re-run it after the sub-agents finish: it lists what's still missing (e.g. a
call ZoomInfo refused) and writes new files for those only.
"""
import argparse
import json
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from zoominfo_merge import COMPANY_FIELDS_ZI, CONTACT_FIELDS  # noqa: E402


def tasks(run, job):
    """[(label, tool, arguments, done_file, ingest command with {resp})]"""
    d = run / "zi"
    zm = shlex.quote(str(HERE / "zoominfo_merge.py"))
    rd = shlex.quote(str(run))
    out = []
    if job == "enrich":
        p = json.loads((d / "plan.json").read_text())
        for kind, tool, batches, fields in (
                ("contacts", "enrich_contacts", "contact_batches", p.get("contact_required_fields", CONTACT_FIELDS)),
                ("companies", "enrich_companies", "company_batches", p.get("company_required_fields", COMPANY_FIELDS_ZI))):
            for i, batch in enumerate(p[batches]):
                out.append((f"{kind} batch {i}", tool, {kind: [x["query"] for x in batch], "requiredFields": fields},
                            d / f"{kind}_{i}.json",
                            f"python3 {zm} ingest --run-dir {rd} --kind {kind} --batch {i} --response {{resp}}"))
    elif job == "search":
        for x in json.loads((d / "search_plan.json").read_text()):
            out.append((f"search {x['row']}", "search_contacts", x["query"], d / f"search_{x['row']}.json",
                        f"python3 {zm} search-ingest --run-dir {rd} --row {x['row']} --response {{resp}}"))
    return out


HEAD = """# ZoomInfo worker {k} of {n} — {count} calls ({job})

Do these calls one after another. For each one:
1. Call the ZoomInfo connector tool named under "tool" with exactly the
   arguments shown (as JSON).
2. Save the tool's result **exactly as returned** to the "save to" file with
   the Write tool. Don't reformat, shorten, summarise or re-read it.
3. Run the "then run" command. It prints one line; keep it.
{search_note}
If ZoomInfo says to slow down (rate limit, 429, "too many requests"): wait
5 s and retry, then 15 s, then 45 s. If it still refuses, skip that call and
carry on; the main chat re-plans what's missing.

When all calls are done, reply with **only** the printed lines, one per call
(no contact data, no raw results).
"""
SEARCH_NOTE = """   If a search returns nothing, retry it once without "companyWebsite" and
   save that result instead.
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--job", required=True, choices=["enrich", "search"])
    ap.add_argument("--workers", type=int, default=4, help="sub-agents to run at the same time (default 4)")
    args = ap.parse_args()
    run = Path(args.run_dir).resolve()
    all_t = tasks(run, args.job)
    todo = [t for t in all_t if not t[3].exists()]
    wd = run / "zi" / "workers"
    raw = run / "zi" / "raw"
    wd.mkdir(parents=True, exist_ok=True)
    raw.mkdir(exist_ok=True)
    for old in wd.glob(f"{args.job}_*.md"):
        old.unlink()
    if not todo:
        print(f"{args.job}: all {len(all_t)} calls done — nothing left to run.")
        return
    n = max(1, min(args.workers, len(todo)))
    groups = [todo[k::n] for k in range(n)]  # round-robin: contacts and companies spread across workers
    files = []
    for k, g in enumerate(groups, 1):
        lines = [HEAD.format(k=k, n=n, count=len(g), job=args.job,
                             search_note=SEARCH_NOTE if "search" in args.job else "")]
        for j, (label, tool, arguments, _done, cmd) in enumerate(g, 1):
            resp = raw / (label.replace(" ", "_") + ".json")
            lines += [f"## Call {j} — {label}", f"tool: `{tool}`", "arguments:", "```json",
                      json.dumps(arguments, ensure_ascii=False), "```", f"save to: `{resp}`",
                      f"then run: `{cmd.format(resp=shlex.quote(str(resp)))}`", ""]
        f = wd / f"{args.job}_{k}.md"
        f.write_text("\n".join(lines), encoding="utf-8")
        files.append((f, len(g)))
    print(f"{args.job}: {len(todo)} of {len(all_t)} calls left, split between {n} sub-agents. Start them ALL AT "
          f"ONCE (one message, {n} sub-agent calls), each named zoominfo-puller with this brief:")
    for f, c in files:
        print(f'  - "Read {f} and do exactly what it says. Reply only with the printed lines." ({c} calls)')
    print("When they're back, re-run this command: it shows anything still missing.")


if __name__ == "__main__":
    main()

"""Requirements check, run at the start of every run — and logged.

Checks what the skill needs before any work starts and records the result, so
the team can see that every run (on anyone's device) was checked first.

Two kinds of checks:
- Checked by this script: Python version, openpyxl, every script and page
  template present and compiling, config.json readable with its keys, a
  writable run folder.
- Seen by Claude, passed in with --observed: the model and which connectors
  this chat has (HubSpot, ZoomInfo, web search, Clay). A script can't see
  those, so Claude reports what it sees and the log says so ("reported by
  Claude").

  python3 preflight.py --list-type zoominfo|linkedin|event-contacts|event-companies
      --run-dir <run_dir> --observed '<json>' [--user <name or email>]

  --observed '{"model": "...", "connectors": {"hubspot": true, "zoominfo": true,
              "web_search": true, "clay": false}}'

The result goes to:
- <run_dir>/preflight.json and ~/.didero-outbound-lists/preflight.jsonl (always)
- the team log, if backend.json is next to config.json (or DIDERO_LOG_URL /
  DIDERO_LOG_KEY are set): one row per run in a Supabase table. If sending
  fails (no network, Cowork blocks the domain) it says so and the run goes on;
  the local log still has it.

Exit code 1 if a required item is missing: stop and tell the user what to fix.
"""
import argparse
import datetime
import getpass
import hashlib
import importlib.util
import json
import os
import platform
import py_compile
import socket
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VERSION_FILE = ROOT / "VERSION"
LOCAL_LOG = Path.home() / ".didero-outbound-lists" / "preflight.jsonl"

SCRIPTS = ["worksheet.py", "email_domain.py", "normalize.py", "hubspot_match.py", "hubspot_import.py",
           "post_import.py", "bdr_assign.py", "zoominfo_merge.py", "linkedin_finder.py", "screen.py",
           "flashcards.py", "jobs.py", "location.py", "fields.py", "handoff.py", "intake.py", "companies.py",
           "company_list.py", "titles.py", "detect_list_type.py", "hubspot_companies.py"]
TEMPLATES = ["review_template.html", "jobs_template.html", "linkedin_finder_template.html",
             "title_finder_template.html", "zoominfo_guide_template.html"]
CONFIG_KEYS = ["hubspot_portal_id", "exclusion_lists", "bdr_pool", "target_countries", "zoominfo_filters"]
MODELS_OK = ("opus", "fable")
# connector -> list types that need it (Clay is run by hand, so it's never required)
EVENT = {"event-contacts", "event-companies", "event-companies-titles"}
NEEDS = {"hubspot": {"zoominfo", "linkedin"} | EVENT,
         "web_search": {"linkedin"} | EVENT,
         "zoominfo": {"linkedin"} | EVENT,
         "clay": set()}


def check(name, ok, detail, required=True, by="script"):
    return {"check": name, "ok": bool(ok), "required": required, "detail": detail, "checked_by": by}


def local_checks(run_dir):
    out = [check("python", sys.version_info >= (3, 9), platform.python_version() + " (needs 3.9+)")]
    out.append(check("openpyxl", importlib.util.find_spec("openpyxl") is not None,
                     "reads .xlsx lists (install: pip install openpyxl)"))
    missing, broken = [], []
    for s in SCRIPTS:
        p = HERE / s
        if not p.exists():
            missing.append(s)
            continue
        try:
            py_compile.compile(str(p), cfile=os.path.join(tempfile.gettempdir(), "didero_pf.pyc"), doraise=True)
        except py_compile.PyCompileError:
            broken.append(s)
    out.append(check("scripts", not missing and not broken,
                     f"{len(SCRIPTS) - len(missing) - len(broken)} of {len(SCRIPTS)} OK"
                     + (f"; missing: {', '.join(missing)}" if missing else "")
                     + (f"; don't compile: {', '.join(broken)}" if broken else "")))
    tmissing = [t for t in TEMPLATES if not (HERE / t).exists()]
    out.append(check("page templates", not tmissing,
                     f"{len(TEMPLATES) - len(tmissing)} of {len(TEMPLATES)} present"
                     + (f"; missing: {', '.join(tmissing)}" if tmissing else "")))
    try:
        cfg = json.loads((ROOT / "config.json").read_text())
        gone = [k for k in CONFIG_KEYS if k not in cfg]
        out.append(check("config.json", not gone, "all settings present" if not gone else f"missing: {', '.join(gone)}"))
    except (OSError, ValueError) as e:
        out.append(check("config.json", False, f"can't read: {e}"))
    try:
        Path(run_dir).mkdir(parents=True, exist_ok=True)
        t = Path(run_dir) / ".write_test"
        t.write_text("ok")
        t.unlink()
        out.append(check("run folder", True, f"writable: {run_dir}"))
    except OSError as e:
        out.append(check("run folder", False, f"can't write {run_dir}: {e}"))
    return out


def observed_checks(observed, list_type):
    out = []
    model = str(observed.get("model") or "")
    out.append(check("model", any(m in model.lower() for m in MODELS_OK), model or "not reported",
                     by="reported by Claude"))
    conns = observed.get("connectors") or {}
    for c, types in NEEDS.items():
        need = list_type in types
        have = conns.get(c)
        detail = ("connected" if have else "not connected" if have is False else "not reported") + \
                 ("" if need else " (not needed for this list)" if c != "clay" else " (Clay is run by hand)")
        out.append(check(f"connector: {c}", bool(have) or not need, detail, required=need, by="reported by Claude"))
    return out


def backend():
    url, key = os.environ.get("DIDERO_LOG_URL"), os.environ.get("DIDERO_LOG_KEY")
    f = ROOT / "backend.json"
    if not url and f.exists():
        try:
            b = json.loads(f.read_text())
            url, key = b.get("url"), b.get("key")
        except ValueError:
            pass
    return (url.rstrip("/"), key) if url and key else (None, None)


def send(record):
    url, key = backend()
    if not url:
        return "not set up (no backend.json) — saved on this device only"
    req = urllib.request.Request(f"{url}/rest/v1/preflight_runs", data=json.dumps(record).encode(), method="POST",
                                 headers={"apikey": key, "Content-Type": "application/json", "Prefer": "return=minimal",
                                          # a legacy anon key (a JWT) also goes in Authorization; a publishable key doesn't
                                          **({"Authorization": f"Bearer {key}"} if key.startswith("eyJ") else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return f"sent to the team log (HTTP {r.status})"
    except Exception as e:  # noqa: BLE001 — any failure: keep the local copy, carry on
        return f"NOT sent ({e.__class__.__name__}: {str(e)[:120]}) — saved on this device; the run can go on"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-type", required=True,
                    choices=["zoominfo", "linkedin", "event-contacts", "event-companies", "event-companies-titles", "unknown"])
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--observed", default="{}", help="JSON: what Claude sees (model, connectors)")
    ap.add_argument("--user", default="", help="who is running it (name or email, if known)")
    args = ap.parse_args()
    observed = json.loads(args.observed)
    checks = local_checks(args.run_dir) + observed_checks(observed, args.list_type)
    failed = [c for c in checks if c["required"] and not c["ok"]]
    host = socket.gethostname()
    record = {
        "run_id": str(uuid.uuid4()),
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "user_label": args.user or getpass.getuser(),
        "device": hashlib.sha256(host.encode()).hexdigest()[:12],  # same device = same code; no hostname stored
        "os": f"{platform.system()} {platform.release()}",
        "skill_version": VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "",
        "list_type": args.list_type,
        "passed": not failed,
        "failed": [c["check"] for c in failed],
        "checks": checks,
    }
    Path(args.run_dir, "preflight.json").write_text(json.dumps(record, indent=1))
    try:
        LOCAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOCAL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass
    for c in checks:
        mark = "OK  " if c["ok"] else ("MISSING" if c["required"] else "--  ")
        print(f"{mark} {c['check']}: {c['detail']}" + ("" if c["checked_by"] == "script" else f" [{c['checked_by']}]"))
    print(f"log: {send(record)}")
    if failed:
        print("STOP — fix before starting: " + ", ".join(c["check"] for c in failed))
        sys.exit(1)
    print(f"all requirements met ({args.list_type} list)")


if __name__ == "__main__":
    main()

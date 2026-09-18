#!/usr/bin/env python3
"""Create today's Substack draft from this Mac.

GitHub's runners are challenged by Substack's Cloudflare rules, so the draft is
created from here, where your session cookie is trusted. Runs every 15 minutes
via launchd (see scripts/install_mac.sh); exits immediately when there is
nothing new. Zero model tokens.

    python3 scripts/substack_local.py            # create today's draft if not done
    python3 scripts/substack_local.py --date 2026-09-17 --force
    python3 scripts/substack_local.py --check     # verify the cookie only
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from brief import substack  # noqa: E402
from brief.util import Settings  # noqa: E402

HOME_DIR = Path(os.environ.get("FURNITURE_BRIEF_HOME", Path.home() / ".furniture-brief"))
SID_FILE = HOME_DIR / "substack.sid"
STATE_FILE = HOME_DIR / "drafted.json"
LOG_FILE = HOME_DIR / "substack_local.log"
RAW = "https://raw.githubusercontent.com/kfopp-wonder/furniture-brief/main/docs/drafts/{date}.json"


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line)
    HOME_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def notify(title: str, text: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'display notification "{text}" with title "{title}"'], check=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--force", action="store_true", help="create even if already drafted today")
    ap.add_argument("--check", action="store_true", help="only verify the cookie")
    ap.add_argument("--open", action="store_true", help="open the draft in the browser afterwards")
    args = ap.parse_args()

    cfg = Settings.load()
    if not SID_FILE.exists():
        log(f"no cookie at {SID_FILE}; run scripts/install_mac.sh")
        return 1
    sid = SID_FILE.read_text().strip()
    if args.check:
        os.environ["SUBSTACK_SID"] = sid
        return substack.check_auth(cfg)

    d = date.fromisoformat(args.date) if args.date else datetime.now(cfg.tz).date()
    if d.weekday() >= 5 and not args.date:
        return 0
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    if d.isoformat() in state and not args.force:
        return 0

    r = requests.get(RAW.format(date=d.isoformat()), timeout=30)
    if r.status_code == 404:
        log(f"no edition published yet for {d}")
        return 0
    r.raise_for_status()
    ed = r.json()
    if ed.get("substack_draft_url") and not args.force:
        # GitHub already created the draft (via SUBSTACK_PROXY); nothing to do here
        state[d.isoformat()] = {"url": ed["substack_draft_url"], "generated_at": ed.get("generated_at"), "drafted_at": "github"}
        STATE_FILE.write_text(json.dumps(state, indent=1))
        return 0
    if d.isoformat() in state and state[d.isoformat()].get("generated_at") == ed.get("generated_at") and not args.force:
        return 0

    url, warn = substack.publish_draft(cfg, d, ed["content"], None, ed.get("card_url"), sid=sid)
    if not url:
        log(f"FAILED: {warn}")
        notify("The Furniture Brief", "Substack draft failed; see ~/.furniture-brief/substack_local.log")
        return 2
    state[d.isoformat()] = {"url": url, "generated_at": ed.get("generated_at"), "drafted_at": datetime.now().isoformat()}
    STATE_FILE.write_text(json.dumps(state, indent=1))
    (HOME_DIR / "latest_draft.txt").write_text(url + "\n")
    log(f"draft created: {url}")
    notify("The Furniture Brief", f"Draft ready: {ed['title'][:70]}")
    if args.open and sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Experiment: can a real headless Chromium on a GitHub runner clear Cloudflare for Substack?

Loads the publication with the session cookie, waits for any challenge to settle, then
calls the profile endpoint from inside the page (same IP, same browser fingerprint) and
prints what comes back. Zero model tokens.
"""
from __future__ import annotations

import os
import sys
import time

from playwright.sync_api import sync_playwright

sid = os.environ.get("SUBSTACK_SID", "").strip()
pub = "https://kfopp.substack.com"
if not sid:
    print("SUBSTACK_SID not set"); sys.exit(1)
if "=" in sid:
    sid = dict(p.strip().split("=", 1) for p in sid.split(";") if "=" in p).get("substack.sid", "")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900}, locale="en-US")
    ctx.add_cookies([{"name": "substack.sid", "value": sid, "domain": ".substack.com", "path": "/", "secure": True, "httpOnly": True}])
    page = ctx.new_page()
    for url in (f"{pub}/publish/home", "https://substack.com/home"):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        for i in range(12):
            title = page.title()
            if "just a moment" not in title.lower():
                break
            time.sleep(2.5)
        print(f"{url} -> title={title!r} final={page.url}")
        names = [c["name"] for c in ctx.cookies()]
        print("cookies:", sorted(set(names)))
        try:
            res = page.evaluate("""async () => { const r = await fetch('/api/v1/user/profile/self', {credentials:'include'}); const t = await r.text(); return {status: r.status, body: t.slice(0,200)}; }""")
            print("profile via page fetch:", res)
            if res.get("status") == 200:
                break
        except Exception as e:  # noqa: BLE001
            print("page fetch error:", e)
    browser.close()

"""Seed state/history.jsonl from every past Substack edition. Zero model tokens.

    python scripts/backfill_history.py            # all posts
    python scripts/backfill_history.py --limit 30 # newest 30 only

Uses Substack's public archive endpoint, then reads each post's body for the
headlines and source links. Safe to re-run: posts already recorded are skipped.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from brief.dedupe import HISTORY  # noqa: E402
from brief.util import Settings, append_jsonl, normalize_title, normalize_url, read_jsonl  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (FurnitureBrief backfill)"}
SECTION_TITLES = {
    "Top Stories": "top_stories", "Industry Moves": "industry_moves",
    "Retail & Consumer Trends": "retail_trends", "Supply Chain & Trade": "supply_chain",
    "AI & Tech Watch": "ai_tech", "Industry Pulse": "industry_moves", "Retail Tech": "retail_trends",
    "AI Frontline": "ai_tech",
}


def archive(base: str, limit: int | None) -> list[dict]:
    posts, offset = [], 0
    while True:
        r = requests.get(f"{base}/api/v1/archive", params={"sort": "new", "offset": offset, "limit": 12}, headers=UA, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        posts.extend(batch)
        offset += len(batch)
        if limit and len(posts) >= limit:
            break
        time.sleep(0.4)
    return posts[:limit] if limit else posts


def parse_post(body_html: str) -> list[dict]:
    """Walk the post body; assign each source link to the section heading above it."""
    rows, section = [], "unknown"
    plain_headline = ""
    for m in re.finditer(r'<h2[^>]*>(.*?)</h2>|<h3[^>]*>(.*?)</h3>|<strong>(.*?)</strong>|<a[^>]+href="(https?://[^"]+)"', body_html, re.S):
        if m.group(1):
            t = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
            section = SECTION_TITLES.get(t, section)
        elif m.group(2):
            plain_headline = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
            plain_headline = re.sub(r"^\d+\.\s*", "", plain_headline)
        elif m.group(3):
            t = html.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
            if len(t.split()) >= 4:
                plain_headline = t
        else:
            url = m.group(4)
            if "substack" in url or "substackcdn" in url:
                continue
            rows.append({"section": section, "headline": plain_headline, "source_url": url})
            plain_headline = ""
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    cfg = Settings.load()
    base = cfg.settings["newsletter"]["substack_url"].rstrip("/")
    existing = read_jsonl(HISTORY)
    seen = {h.get("post_url") for h in existing}
    posts = archive(base, args.limit)
    print(f"{len(posts)} posts in archive, {len(seen)} already recorded")
    added = 0
    for p in posts:
        url = p.get("canonical_url")
        if not url or url in seen:
            continue
        d = (p.get("post_date") or "")[:10]
        body = p.get("body_html") or ""
        if not body:
            try:
                r = requests.get(f"{base}/api/v1/posts/{p['slug']}", headers=UA, timeout=30)
                r.raise_for_status()
                body = r.json().get("body_html") or ""
            except Exception as e:  # noqa: BLE001
                print(f"  skip {p.get('slug')}: {e}")
                continue
        rows = []
        for it in parse_post(body):
            rows.append({"date": d, "section": it["section"], "headline": it["headline"], "status": "published",
                         "post_url": url, "source_url": it["source_url"],
                         "norm_url": normalize_url(it["source_url"]), "norm_title": normalize_title(it["headline"])})
        rows.append({"date": d, "section": "post", "headline": p.get("title", ""), "status": "published",
                     "post_url": url, "source_url": "", "norm_url": "", "norm_title": normalize_title(p.get("title", ""))})
        append_jsonl(HISTORY, rows)
        added += len(rows)
        print(f"  {d}  {p.get('title', '')[:60]}  ({len(rows) - 1} links)")
        time.sleep(0.4)
    print(f"added {added} rows to {HISTORY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Fetch RSS feeds, filter to the time window, score relevance, merge duplicates.

Zero model tokens. Output: a list of candidate dicts with a short stable id.
"""
from __future__ import annotations

import concurrent.futures as cf
import html
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

from .util import Settings, log, normalize_title, normalize_url, stable_id

UA = "Mozilla/5.0 (compatible; FurnitureBrief/1.0; +https://kfopp.substack.com)"


def _parse_date(entry) -> datetime | None:
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if not val:
            continue
        try:
            if re.match(r"\d{4}-\d{2}-\d{2}T", val):
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt.astimezone(timezone.utc)
        except ValueError:
            pass
        try:
            dt = parsedate_to_datetime(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _excerpt(entry) -> str:
    for key in ("summary", "description"):
        if entry.get(key):
            return _strip_html(entry[key])[:600]
    content = entry.get("content") or []
    if content and content[0].get("value"):
        return _strip_html(content[0]["value"])[:600]
    return ""


def _gnews_publisher(entry) -> str | None:
    src = entry.get("source")
    if isinstance(src, dict):
        return src.get("title")
    return None


def _slug_title(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[-_]+", " ", slug).strip().capitalize()


def fetch_sitemap(feed: dict, timeout: int = 25) -> tuple[list, str | None]:
    """WordPress sites with RSS disabled (Furniture Today) still publish a Yoast post
    sitemap. Read the newest post-sitemap file(s) and turn <url> entries into
    feedparser-like entries. Titles come from the slug; extraction fills in the rest."""
    try:
        r = requests.get(feed["url"], headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code >= 400:
            return [], f"HTTP {r.status_code}"
        parts = re.findall(r"<loc>([^<]*post-sitemap(\d*)\.xml)</loc>", r.text)
        if parts:
            parts.sort(key=lambda m: int(m[1] or 1), reverse=True)
            files = [m[0] for m in parts[:2]]
        else:
            files = [feed["url"]]
        entries = []
        for f in files:
            rr = requests.get(f, headers={"User-Agent": UA}, timeout=timeout)
            if rr.status_code >= 400:
                continue
            for loc, lastmod in re.findall(r"<url>\s*<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", rr.text):
                if not lastmod:
                    continue
                entries.append({"title": _slug_title(loc), "link": loc, "published": lastmod, "summary": ""})
        return entries, None
    except requests.RequestException as e:
        return [], f"{type(e).__name__}: {e}"


def fetch_feed(feed: dict, timeout: int = 25) -> tuple[list, str | None]:
    """Return (entries, error)."""
    if feed.get("sitemap"):
        return fetch_sitemap(feed, timeout)
    try:
        r = requests.get(feed["url"], headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code >= 400:
            return [], f"HTTP {r.status_code}"
        parsed = feedparser.parse(r.content)
        if parsed.bozo and not parsed.entries:
            return [], f"parse error: {getattr(parsed, 'bozo_exception', 'unknown')}"
        return list(parsed.entries), None
    except requests.RequestException as e:
        return [], f"{type(e).__name__}: {e}"


def check_feeds(cfg: Settings) -> list[dict]:
    """--check-feeds: fetch each feed and report counts/errors."""
    rows = []
    for feed in cfg.feeds["feeds"]:
        t = time.time()
        entries, err = fetch_feed(feed)
        newest = None
        if entries:
            dts = [d for d in (_parse_date(e) for e in entries) if d]
            newest = max(dts).isoformat() if dts else None
        rows.append({
            "id": feed["id"], "name": feed["name"], "count": len(entries),
            "newest": newest, "error": err, "seconds": round(time.time() - t, 1),
        })
    return rows


def score_item(title: str, excerpt: str, feed: dict, kw: dict) -> tuple[float, bool]:
    text = f" {title} {excerpt} ".lower()
    score = 0.0
    is_ai = False
    for term in kw.get("strong", []):
        if term.lower() in text:
            score += 3
    for term in kw.get("medium", []):
        if term.lower() in text:
            score += 1.5
    for term in kw.get("ai", []):
        if term.lower() in text:
            score += 1.5
            is_ai = True
    for term in kw.get("negative", []):
        if term.lower() in text:
            score -= 4
    score *= float(feed.get("weight", 1.0))
    return round(score, 2), is_ai


def collect(cfg: Settings, now: datetime, hours: int) -> tuple[list[dict], list[dict]]:
    """Fetch all feeds in parallel. Returns (candidates, feed_reports)."""
    cutoff = now - timedelta(hours=hours)
    kw = cfg.feeds.get("keywords", {})
    feeds = cfg.feeds["feeds"]
    reports: list[dict] = []
    items: list[dict] = []

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_feed, f): f for f in feeds}
        for fut in cf.as_completed(futures):
            feed = futures[fut]
            entries, err = fut.result()
            kept = 0
            for e in entries:
                dt = _parse_date(e)
                if dt is None or dt < cutoff or dt > now + timedelta(hours=6):
                    continue
                title = _strip_html(e.get("title", "")).strip()
                url = (e.get("link") or "").strip()
                if not title or not url:
                    continue
                excerpt = _excerpt(e)
                score, is_ai = score_item(title, excerpt, feed, kw)
                if feed.get("sitemap"):
                    score = max(score, 3.0 * float(feed.get("weight", 1.0)))  # trade source, no excerpt to score
                    is_ai = is_ai or bool(re.search(r"\bai\b|artificial intelligence", title, re.I))
                if score <= 0:
                    continue
                publisher = feed["name"]
                if feed.get("google_news"):
                    publisher = _gnews_publisher(e) or publisher
                    # Google News appends " - Publisher" to titles
                    title = re.sub(r"\s+-\s+[^-]+$", "", title)
                items.append({
                    "title": title,
                    "url": url,
                    "norm_url": normalize_url(url),
                    "norm_title": normalize_title(title),
                    "published": dt.isoformat(),
                    "age_hours": round((now - dt).total_seconds() / 3600, 1),
                    "source": publisher,
                    "feed_id": feed["id"],
                    "paywalled": bool(feed.get("paywalled")),
                    "google_news": bool(feed.get("google_news")),
                    "excerpt": excerpt,
                    "score": score,
                    "is_ai": is_ai,
                    "sections_hint": feed.get("sections", []),
                    "slug_title": bool(feed.get("sitemap")),
                })
                kept += 1
            reports.append({"id": feed["id"], "name": feed["name"], "fetched": len(entries),
                            "in_window": kept, "error": err})

    merged = merge_duplicates(items)
    merged.sort(key=lambda x: (-x["score"], x["age_hours"]))
    for it in merged:
        it["id"] = stable_id(it["norm_url"] or it["norm_title"])
    log.info("collected %d items from %d feeds, %d after merge", len(items), len(feeds), len(merged))
    return merged, sorted(reports, key=lambda r: r["id"])


def _title_tokens(t: str) -> set[str]:
    stop = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "with", "at", "by", "is", "as", "its", "it"}
    return {w for w in t.split() if len(w) > 2 and w not in stop}


def merge_duplicates(items: list[dict]) -> list[dict]:
    """Merge items with the same URL or near-identical titles. Keeps the best-scored,
    prefers non-Google-News, non-paywalled versions; records alternates."""
    items = sorted(items, key=lambda x: (x["google_news"], x["paywalled"], -x["score"]))
    out: list[dict] = []
    for it in items:
        dup = None
        toks = _title_tokens(it["norm_title"])
        for o in out:
            if it["norm_url"] and it["norm_url"] == o["norm_url"]:
                dup = o
                break
            otoks = _title_tokens(o["norm_title"])
            if toks and otoks:
                j = len(toks & otoks) / len(toks | otoks)
                if j >= 0.6:
                    dup = o
                    break
        if dup:
            dup.setdefault("alternates", []).append({"source": it["source"], "url": it["url"]})
            dup["score"] = max(dup["score"], it["score"]) + 0.5  # covered by more than one outlet
            dup["is_ai"] = dup["is_ai"] or it["is_ai"]
        else:
            out.append(it)
    return out

"""Drop candidates already covered in past editions.

The corpus is state/history.jsonl: one row per published item
{"date","section","headline","source_url","norm_url","norm_title"}.
Also refreshes the corpus from the live Substack feed so a story published
manually (or by the old Perplexity workflow) is still caught.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import feedparser
import requests

from .collect import _title_tokens
from .util import STATE, Settings, append_jsonl, log, normalize_title, normalize_url, read_jsonl

HISTORY = STATE / "history.jsonl"


def load_history() -> list[dict]:
    return read_jsonl(HISTORY)


def _links_from_html(html: str) -> list[str]:
    return re.findall(r'href="(https?://[^"]+)"', html or "")


def refresh_from_substack(cfg: Settings, history: list[dict]) -> int:
    """Pull the public Substack feed; add source links from any post we have not seen."""
    url = cfg.settings["newsletter"].get("substack_feed")
    if not url:
        return 0
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "FurnitureBrief/1.0"})
        parsed = feedparser.parse(r.content)
    except Exception as e:  # noqa: BLE001
        log.warning("substack feed unavailable: %s", e)
        return 0
    seen_posts = {h.get("post_url") for h in history if h.get("post_url")}
    new_rows: list[dict] = []
    substack_host = url.split("/")[2]
    for e in parsed.entries:
        post_url = e.get("link", "")
        if not post_url or post_url in seen_posts:
            continue
        body = ""
        if e.get("content"):
            body = e["content"][0].get("value", "")
        body = body or e.get("summary", "")
        pub = e.get("published", "")[:16]
        for link in _links_from_html(body):
            if substack_host in link or "substackcdn" in link or "substack.com" in link:
                continue
            new_rows.append({
                "date": pub, "section": "unknown", "headline": "", "post_url": post_url,
                "source_url": link, "norm_url": normalize_url(link), "norm_title": "",
            })
        if not new_rows or new_rows[-1]["post_url"] != post_url:
            new_rows.append({"date": pub, "section": "post", "headline": e.get("title", ""),
                             "post_url": post_url, "source_url": "", "norm_url": "",
                             "norm_title": normalize_title(e.get("title", ""))})
    if new_rows:
        append_jsonl(HISTORY, new_rows)
        history.extend(new_rows)
        log.info("history: added %d rows from Substack feed", len(new_rows))
    return len(new_rows)


def filter_candidates(candidates: list[dict], history: list[dict], lookback_days: int = 21,
                      edition: date | None = None) -> tuple[list[dict], list[dict]]:
    """Return (kept, dropped). Matches on normalized URL, or high title overlap
    with a headline published within `lookback_days`."""
    # Rows drafted today (an earlier run of the same edition) do not count as published,
    # so a "regenerate with notes" rerun can reuse the same stories.
    today = (edition or date.today()).isoformat()
    history = [h for h in history if not (h.get("status") == "draft" and (h.get("date") or "")[:10] == today)]
    seen_urls = {h["norm_url"] for h in history if h.get("norm_url")}
    cutoff = ((edition or date.today()) - timedelta(days=lookback_days)).isoformat()
    recent_titles = [h["norm_title"] for h in history
                     if h.get("norm_title") and (h.get("date") or "")[:10] >= cutoff]
    recent_tokens = [_title_tokens(t) for t in recent_titles]
    kept, dropped = [], []
    for c in candidates:
        reason = None
        if c["norm_url"] in seen_urls:
            reason = "url already published"
        else:
            toks = _title_tokens(c["norm_title"])
            for rt in recent_tokens:
                if toks and rt and len(toks & rt) / len(toks | rt) >= 0.55:
                    reason = "title matches a recent headline"
                    break
        if reason:
            c["dropped_reason"] = reason
            dropped.append(c)
        else:
            kept.append(c)
    log.info("dedupe: kept %d, dropped %d", len(kept), len(dropped))
    return kept, dropped


def recent_headlines(history: list[dict], days: int = 7, limit: int = 60,
                     edition: date | None = None) -> list[str]:
    ed = edition or date.today()
    cutoff = (ed - timedelta(days=days)).isoformat()
    heads = [h["headline"] for h in history
             if h.get("headline") and h.get("section") not in ("post", "unknown")
             and cutoff <= (h.get("date") or "")[:10] < ed.isoformat()]
    return heads[-limit:]


def record_edition(d: date, content: dict, articles: dict[str, dict], post_url: str = "") -> None:
    rows = []
    for sec, items in content.get("sections", {}).items():
        for it in items:
            art = articles.get(it.get("article_id"), {})
            rows.append({
                "date": d.isoformat(), "section": sec, "headline": it.get("headline", ""),
                "status": "draft", "post_url": post_url, "source_url": art.get("url", ""),
                "norm_url": normalize_url(art.get("url", "")),
                "norm_title": normalize_title(art.get("title", "")),
            })
    append_jsonl(HISTORY, rows)

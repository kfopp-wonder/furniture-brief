"""Full-text and lead-image extraction for the selected articles only (trafilatura)."""
from __future__ import annotations

import concurrent.futures as cf
import re

import requests
import trafilatura
from trafilatura.settings import use_config

from .util import Settings, log

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _trim_words(text: str, n: int) -> str:
    words = text.split()
    if len(words) <= n:
        return text
    return " ".join(words[:n]) + " ..."


def resolve_google_news(url: str, timeout: int) -> str:
    """Google News RSS links redirect to the publisher; follow them when possible."""
    if "news.google.com" not in url:
        return url
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout, allow_redirects=True)
        if r.url and "news.google.com" not in r.url:
            return r.url
        m = re.search(r'data-n-au="(https?://[^"]+)"', r.text) or re.search(r'href="(https?://(?!news\.google)[^"]+)"', r.text)
        if m:
            return m.group(1)
    except requests.RequestException:
        pass
    return url


def _lead_image(html: str) -> str | None:
    for pat in (r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
                r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
                r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"'):
        m = re.search(pat, html, re.I)
        if m:
            u = m.group(1).strip()
            if u.startswith("http") and not re.search(r"logo|icon|avatar|default|placeholder", u, re.I):
                return u
    return None


def extract_one(article: dict, max_words: int, timeout: int) -> dict:
    """Mutates and returns the article with text/image/extraction fields."""
    url = article["url"]
    if article.get("google_news"):
        resolved = resolve_google_news(url, timeout)
        if resolved != url:
            article["resolved_url"] = resolved
            url = resolved
    cfg = use_config()
    cfg.set("DEFAULT", "DOWNLOAD_TIMEOUT", str(timeout))
    text, image, err = "", None, None
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code < 400 and r.text:
            html = r.text
            image = _lead_image(html)
            text = trafilatura.extract(html, include_comments=False, include_tables=False,
                                       favor_precision=True, config=cfg) or ""
        else:
            err = f"HTTP {r.status_code}"
    except requests.RequestException as e:
        err = type(e).__name__
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"

    text = re.sub(r"\s+\n", "\n", text).strip()
    words = len(text.split())
    # A paywall usually yields a stub (< 120 words). Fall back to the RSS excerpt.
    if words < 120:
        article["text"] = article.get("excerpt", "")
        article["excerpt_only"] = True
        article["extract_error"] = err or f"only {words} words extracted (paywall?)"
    else:
        article["text"] = _trim_words(text, max_words)
        article["excerpt_only"] = False
        article["extract_error"] = None
    article["image"] = image
    article["full_words"] = words
    return article


def extract_many(cfg: Settings, picks: dict[str, int], by_id: dict[str, dict]) -> dict[str, dict]:
    """picks: {article_id: max_words}. Returns {id: article}."""
    timeout = int(cfg.settings["extract"]["timeout_seconds"])
    out: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(extract_one, dict(by_id[i]), n, timeout): i for i, n in picks.items() if i in by_id}
        for f in cf.as_completed(futs):
            a = f.result()
            out[a["id"]] = a
    ok = sum(1 for a in out.values() if not a["excerpt_only"])
    log.info("extracted %d/%d full texts", ok, len(out))
    return out

"""Validate the model's JSON, attach sources, and render HTML (Substack paste + review email)."""
from __future__ import annotations

import html
import json
import re
from datetime import date

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .util import TEMPLATES, Settings, long_date, word_count

DASHES = "—–"  # em, en
BANNED = ["game-changer", "delve", "in today's fast-paced", "it's worth noting", "at the end of the day",
          "seamless", "robust", "elevate", "unlock", "landscape", "navigate"]


def _clean(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("—", ", ").replace("–", "-")
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return s


def validate_and_attach(cfg: Settings, content: dict, articles: dict[str, dict]) -> tuple[dict, list[str]]:
    """Normalise the writer output in place. Returns (content, warnings)."""
    warnings: list[str] = []
    for k in ("title", "subtitle", "greeting", "closing"):
        content[k] = _clean(content.get(k, ""))
        if not content[k]:
            warnings.append(f"Missing {k}.")
    ot = content.get("one_thing") or {}
    content["one_thing"] = {"headline": _clean(ot.get("headline", "")), "body": _clean(ot.get("body", ""))}

    sections = content.get("sections") or {}
    if isinstance(sections, str):
        try:
            sections = json.loads(sections)
        except json.JSONDecodeError:
            sections = {}
    if not isinstance(sections, dict):
        sections = {}
    out_sections: dict[str, list[dict]] = {}
    used: set[str] = set()
    for s in cfg.sections:
        items = []
        lo, hi = s["words"]
        for raw in sections.get(s["key"], []) or []:
            aid = raw.get("article_id")
            art = articles.get(aid)
            if not art:
                warnings.append(f'{s["title"]}: item "{raw.get("headline", "")[:50]}" references unknown article {aid}; dropped.')
                continue
            if aid in used:
                warnings.append(f'{s["title"]}: article {aid} used twice; second use dropped.')
                continue
            used.add(aid)
            item = {
                "headline": _clean(raw.get("headline", "")),
                "summary": _clean(raw.get("summary", "")),
                "article_id": aid,
                "source_name": art["source"],
                "source_url": art.get("resolved_url") or art["url"],
                "excerpt_only": bool(art.get("excerpt_only")),
                "google_news": "news.google.com" in (art.get("resolved_url") or art["url"]),
            }
            wc = word_count(item["summary"])
            if wc < lo * 0.8 or wc > hi * 1.2:
                warnings.append(f'{s["title"]}: "{item["headline"][:50]}" is {wc} words (target {lo}-{hi}).')
            if item["excerpt_only"]:
                warnings.append(f'{s["title"]}: "{item["headline"][:50]}" was written from an RSS excerpt only (paywall). Fact-check.')
            if item["google_news"]:
                warnings.append(f'{s["title"]}: "{item["headline"][:50]}" links through Google News; swap in the publisher URL.')
            if art.get("unresolved_link"):
                warnings.append(f'{s["title"]}: "{item["headline"][:50]}" still links through a newsletter tracking URL ({art.get("via", "")}); swap in the publisher URL.')
            if art.get("is_video"):
                warnings.append(f'{s["title"]}: "{item["headline"][:50]}" links to a video; the summary was written from the newsletter blurb only.')
            low = (item["summary"] + " " + item["headline"]).lower()
            for b in BANNED:
                if b in low:
                    warnings.append(f'{s["title"]}: "{item["headline"][:50]}" uses "{b}".')
            if "!" in item["summary"] or "?" in item["headline"]:
                warnings.append(f'{s["title"]}: "{item["headline"][:50]}" has an exclamation or a question headline.')
            items.append(item)
        if len(items) < s["min"]:
            warnings.append(f'{s["title"]}: only {len(items)} items (minimum {s["min"]}).')
        out_sections[s["key"]] = items
    content["sections"] = out_sections

    hero_id = content.get("hero")
    hero = articles.get(hero_id) if hero_id else None
    if not (hero and hero.get("image")):
        hero = next((articles[i["article_id"]] for i in out_sections.get("top_stories", [])
                     if articles.get(i["article_id"], {}).get("image")), None)
        if hero is None:
            warnings.append("No lead image available; edition renders without a hero image.")
    content["hero_image"] = None
    if hero and hero.get("image"):
        content["hero_image"] = {"url": hero["image"], "alt": hero["title"], "source_url": hero.get("resolved_url") or hero["url"]}

    for k in ("greeting", "closing"):
        wc = word_count(content[k])
        if k == "greeting" and not (50 <= wc <= 110):
            warnings.append(f"Greeting is {wc} words (target 60-95).")
    if any(ch in (content["title"] + content["subtitle"]) for ch in DASHES):
        warnings.append("Dash found in title or subtitle after cleaning (should not happen).")
    return content, warnings


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["e"] = html.escape
    return env


def render_newsletter(cfg: Settings, d: date, content: dict, card_url: str | None) -> str:
    tpl = _env().get_template("newsletter.html.j2")
    sections = [{"key": s["key"], "title": s["title"], "kind": s["kind"], "entries": content["sections"].get(s["key"], [])}
                for s in cfg.sections]
    return tpl.render(date_long=long_date(d), content=content, sections=sections, card_url=card_url,
                      footer=cfg.settings["newsletter"]["footer"])


def render_review_email(cfg: Settings, d: date, content: dict, newsletter_html: str, checks: list[str],
                        feed_reports: list[dict], usage: dict, card_url: str | None, run_url: str | None,
                        notes: str, draft_url: str | None = None) -> str:
    tpl = _env().get_template("review_email.html.j2")
    feed_errors = [f'{r["name"]}: {r["error"]}' for r in feed_reports if r.get("error")]
    return tpl.render(date_long=long_date(d), content=content, newsletter_html=newsletter_html,
                      checks=checks, feed_errors=feed_errors, usage=usage, card_url=card_url,
                      run_url=run_url, notes=notes, draft_url=draft_url)


def title_subtitle_txt(content: dict) -> str:
    return (f"TITLE (paste into title field):\n{content['title']}\n\n"
            f"SUBTITLE (paste into subtitle field):\n{content['subtitle']}\n")

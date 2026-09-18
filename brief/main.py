"""Entry point.

    python -m brief.main                       # today's edition, emails the review draft
    python -m brief.main --force               # run even on a weekend/skip date, no email
    python -m brief.main --mock --date 2026-09-17   # fixtures only, zero tokens, no network
    python -m brief.main --check-feeds         # print feed health
    python -m brief.main --notes "Lead with the Fed hike"
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone

from . import card as card_mod
from . import collect, dedupe, extract, llm, market, notify, render, substack
from .util import DOCS, FIXTURES, OUT, STATE, Settings, edition_date, env, log, setup_logging, short_date, window_hours


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="The Furniture Brief daily pipeline")
    p.add_argument("--date", help="edition date YYYY-MM-DD (default: today in the newsletter timezone)")
    p.add_argument("--notes", default="", help="editor notes passed to both model calls")
    p.add_argument("--mock", action="store_true", help="use fixtures for feeds, extraction, models and market data")
    p.add_argument("--force", action="store_true", help="run on weekends/skip dates; implies --no-email")
    p.add_argument("--no-email", action="store_true", help="build everything but do not send")
    p.add_argument("--check-feeds", action="store_true", help="fetch each feed and report")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


def _load_fixture(name: str):
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def run(args) -> int:
    cfg = Settings.load()
    d = edition_date(cfg, args.date)
    date_str = d.isoformat()
    weekday = d.strftime("%A")
    notes = (args.notes or env("BRIEF_NOTES") or "").strip()

    if args.check_feeds:
        rows = collect.check_feeds(cfg)
        print(f"{'feed':20} {'items':>5} {'secs':>5}  newest / error")
        for r in rows:
            print(f"{r['id']:20} {r['count']:5} {r['seconds']:5}  {r['error'] or r['newest']}")
        return 0 if all(not r["error"] for r in rows) else 1

    if not args.force and not args.mock:
        if d.weekday() >= 5:
            log.info("%s is a weekend; nothing to do", date_str)
            return 0
        if date_str in [str(x) for x in cfg.settings.get("skip_dates", [])]:
            log.info("%s is a skip date; nothing to do", date_str)
            return 0

    out_dir = OUT / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    usage = llm.Usage()
    checks: list[str] = []
    now = datetime.now(timezone.utc)

    # 1. collect (Python)
    if args.mock:
        candidates = _load_fixture("candidates.json")
        feed_reports = [{"id": "fixture", "name": "fixture", "fetched": len(candidates), "in_window": len(candidates), "error": None}]
    else:
        candidates, feed_reports = collect.collect(cfg, now, window_hours(cfg, d))
    (out_dir / "candidates.json").write_text(json.dumps(candidates, indent=1, ensure_ascii=False))

    # 2. dedupe (Python)
    history = [] if args.mock else dedupe.load_history()   # fixtures ARE a past edition; skip history in mock
    if not args.mock:
        dedupe.refresh_from_substack(cfg, history)
    candidates, dropped = dedupe.filter_candidates(candidates, history, edition=d)
    max_c = int(cfg.settings["window"]["max_candidates"])
    candidates = candidates[:max_c]
    by_id = {c["id"]: c for c in candidates}
    if len(candidates) < 12:
        checks.append(f"Only {len(candidates)} candidate articles after filtering; the edition may be thin.")
    recent = dedupe.recent_headlines(history, edition=d)

    # 3. select (Haiku)
    picks = llm.select(cfg, candidates, recent, notes, date_str, usage,
                       mock=_load_fixture("select_response.json") if args.mock else None)
    (out_dir / "picks.json").write_text(json.dumps(picks, indent=1))

    # 4. extract full text for picks only (Python)
    ex = cfg.settings["extract"]
    wanted: dict[str, int] = {}
    for s in cfg.sections:
        n = ex["story_words"] if s["kind"] == "story" else ex["bullet_words"]
        for i in picks.get(s["key"], []):
            wanted[i] = n
    for i in picks.get("backups", []):
        wanted[i] = ex["backup_words"]
    if args.mock:
        fx = _load_fixture("extracted.json")
        articles = {i: {**by_id[i], **fx.get(i, {"text": by_id[i]["excerpt"], "excerpt_only": True, "image": None})}
                    for i in wanted if i in by_id}
    else:
        articles = extract.extract_many(cfg, wanted, by_id)
    backups = [articles[i] for i in picks.get("backups", []) if i in articles]

    # 5. write (Sonnet)
    content = llm.write(cfg, date_str, weekday, picks, articles, backups, notes, usage,
                        mock=_load_fixture("write_response.json") if args.mock else None)
    (out_dir / "content_raw.json").write_text(json.dumps(content, indent=1, ensure_ascii=False))

    # 6. validate + attach sources (Python)
    content, warnings = render.validate_and_attach(cfg, content, articles)
    checks.extend(warnings)
    (out_dir / "content.json").write_text(json.dumps(content, indent=1, ensure_ascii=False))

    # 7. market data + card
    mkt = market.build_market(cfg, fixture=_load_fixture("market.json") if args.mock else None)
    checks.extend(mkt["flags"])
    (out_dir / "market.json").write_text(json.dumps(mkt, indent=1, default=str))
    card_path = card_mod.render_card(mkt, out_dir / "market_pulse_card.png")
    # Unique filename per run so reruns of the same date never hit a cached image.
    card_name = f"{date_str}-{hashlib.sha1(card_path.read_bytes()).hexdigest()[:8]}.png"
    pages = cfg.settings["assets"]["pages_base_url"].rstrip("/")
    card_url = None
    if "REPLACE-ME" in pages:
        checks.append("assets.pages_base_url is not set in config/settings.yaml; the Market Pulse image will not resolve.")
    else:
        card_url = f"{pages}/pulse/{card_name}"
    shutil.copy(card_path, DOCS / "pulse" / card_name)

    # 8. render
    newsletter_html = render.render_newsletter(cfg, d, content, card_url)
    (out_dir / "paste.html").write_text(newsletter_html, encoding="utf-8")
    (out_dir / "title_subtitle.txt").write_text(render.title_subtitle_txt(content), encoding="utf-8")
    (DOCS / "drafts" / f"{date_str}.html").write_text(
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{content['title']}</title></head><body>{newsletter_html}</body></html>",
        encoding="utf-8")
    # 8b. Substack draft (skipped in mock mode; never fatal)
    draft_url = None
    if not args.mock:
        draft_url, warn = substack.publish_draft(cfg, d, content, card_path, card_url)
        if warn:
            checks.append(warn)
    run_url = None
    if env("GITHUB_SERVER_URL") and env("GITHUB_REPOSITORY") and env("GITHUB_RUN_ID"):
        run_url = f"{env('GITHUB_SERVER_URL')}/{env('GITHUB_REPOSITORY')}/actions/runs/{env('GITHUB_RUN_ID')}"
    usage_d = {"total": usage.total, "calls": usage.calls}
    review_html = render.render_review_email(cfg, d, content, newsletter_html, checks, feed_reports,
                                             usage_d, card_url, run_url, notes, draft_url)
    (out_dir / "review_email.html").write_text(review_html, encoding="utf-8")
    # In the emailed copy, show the freshly rendered card inline (cid) instead of the Pages URL,
    # which only goes live a few minutes after the run and can be cached by mail clients.
    email_html = review_html.replace(card_url, "cid:market_pulse_card") if card_url else review_html

    # 9. state: history + costs
    dedupe.record_edition(d, content, articles)
    costs = STATE / "costs.csv"
    new = not costs.exists()
    with open(costs, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["run_at_utc", "edition", "cost_usd", "calls", "notes"])
        w.writerow([now.strftime("%Y-%m-%dT%H:%MZ"), date_str, f"{usage.total:.4f}",
                    json.dumps(usage.calls), notes[:120]])

    log.info("edition %s built: %s  (cost $%.3f, %d checks)", date_str, content["title"], usage.total, len(checks))
    for c in checks:
        log.info("  check: %s", c)

    # 10. email
    if args.no_email or args.force or args.mock:
        log.info("email skipped; open %s", out_dir / "review_email.html")
    else:
        subject = f"{cfg.settings['email']['subject_prefix']} · {short_date(d)} · {content['title']}"
        notify.send_review(cfg, subject, email_html,
                           [out_dir / "paste.html", out_dir / "title_subtitle.txt"], inline_png=card_path)
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)
    try:
        return run(args)
    except Exception:
        log.exception("pipeline failed")
        return 2


if __name__ == "__main__":
    sys.exit(main())

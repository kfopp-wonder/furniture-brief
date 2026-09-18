# The Furniture Brief: daily pipeline

Generates each weekday's edition of [The Furniture Brief](https://kfopp.substack.com), renders the Market Pulse card, and emails you a paste-ready review draft before 7am. Runs free on GitHub Actions. Expected model cost: **about $0.10 per edition (~$2/month)** with Sonnet 5 as the writer, or **about $0.04 (~$1/month)** with Haiku.

## Why this is cheap

An agent (Perplexity Computer, or any "go research and write" loop) re-reads everything it has done at every step: browsing, deciding, fetching, re-reading, rendering. Tokens compound. This pipeline inverts that: **code does all the mechanical work, and the model is called exactly twice with a pre-assembled, trimmed input.**

| Step | Done by | Tokens |
|---|---|---|
| Fetch 10 sources (9 RSS + Furniture Today's post sitemap), filter to last 36h (84h on Mondays) | Python | 0 |
| Score relevance with keywords, merge duplicate stories | Python | 0 |
| Drop anything already published (your own Substack feed + history) | Python | 0 |
| **Pick stories for each section** from ~60 one-line candidates | **Haiku 4.5** | ~7k in / ~0.3k out |
| Pull full text + lead image for the ~18 picks only | Python (trafilatura) | 0 |
| **Write the whole edition** in one pass, returned as structured JSON | **Sonnet 5** | ~15k in / ~3k out |
| Insert source names/URLs, check counts, word lengths, em dashes | Python | 0 |
| Market Pulse data (stocks, crude, 10-yr, gas, diesel, mortgage, WCI) | yfinance + FRED | 0 |
| Render the card PNG | Pillow | 0 |
| Build Substack HTML and review email, send | Jinja + SMTP | 0 |

Other savings built in: the model returns article ids instead of URLs (fewer output tokens, and links can't be hallucinated); backup articles are sent as 220-word excerpts; the style guide is written once (by Opus, in `config/style_guide.md`) so the daily model never has to infer your voice; no images are generated.

It is also more reliable than the current card: every quote is checked (a price under $0.50 or a move over 25% is flagged in the email rather than published silently; the current card shows SNBR at $0.02 and blanks for the 10-yr and Kirkland's). Kirkland's now trades as The Brand House Collective (TBHC), which is already swapped in.

## One-time setup (about 20 minutes)

1. **Create a GitHub repo** (e.g. `furniture-brief`) and push this folder. A public repo gives unlimited free Actions minutes and free Pages; nothing secret lives in the code.
2. **Turn on GitHub Pages**: Settings → Pages → Deploy from branch → `main` / `/docs`. Put the resulting URL in `config/settings.yaml` → `assets.pages_base_url`. This hosts the Market Pulse PNG; when you paste into Substack, Substack copies the image to its own CDN, just like today.
3. **Add repository secrets** (Settings → Secrets and variables → Actions):
   - `ANTHROPIC_API_KEY`: from platform.claude.com. Consider a dedicated key with a monthly spend limit of $10.
   - `FRED_API_KEY`: free at fred.stlouisfed.org (10-yr, gas, diesel, 30-yr mortgage).
   - `SMTP_USER`, `SMTP_PASS`: a Gmail address and a Gmail [app password](https://myaccount.google.com/apppasswords).
   - `MAIL_FROM`, `MAIL_TO`: sender and your inbox.
4. **Seed the dedupe history** from all past editions (zero tokens): Actions → Maintenance → Run workflow → `backfill-history`. It reads the public Substack archive and commits `state/history.jsonl`. (Locally: `python scripts/backfill_history.py`.) The repo ships pre-seeded with the Sept 11–17 editions.
5. **Verify feeds**: Actions → Maintenance → `check-feeds` prints how many items each feed returned. Fix or remove any that show errors in `config/feeds.yaml`. (Locally: `python -m brief.main --check-feeds`.)
6. **Dry run**: Actions → Daily Brief → Run workflow. You'll get the review email in about 2 minutes.
7. Cancel the Perplexity task once you're happy with two or three editions.

## Daily routine

At ~5:45am ET (09:45 UTC; GitHub's scheduler can lag 5–15 minutes) the workflow runs and emails **"Review: The Furniture Brief · Thu Sep 17 · {title}"** containing the title and subtitle, a yellow **Check before publishing** box (feed errors, paywalled stories written from excerpts, odd quotes, Google News links to replace), the run cost, the full rendered edition, and attachments: `paste.html`, `title_subtitle.txt`, and the card PNG.

To publish: open Substack → New post → paste title and subtitle → copy the edition from the email (or open `paste.html` in a browser, select all, copy) → paste into the body → publish.

**Regenerate with direction:** Actions → Daily Brief → Run workflow, enter notes such as *"Lead with the Fed hike. Drop the Lowe's item."* Both model calls receive the notes. Cost per rerun: the same ~$0.10.

## Tuning without code

| Want to... | Edit |
|---|---|
| Change voice, lengths, headline style | `config/style_guide.md` |
| Add/remove sources or weight them | `config/feeds.yaml` |
| Change tickers or market rows | `config/tickers.yaml` |
| Change section counts or names | `config/settings.yaml` → `sections` |
| Cheaper writer | `settings.yaml` → `models.writer: claude-haiku-4-5-20251001` |
| Skip holidays | `settings.yaml` → `skip_dates` |

## Known limits

- **Substack has no publishing API**, so the final paste stays manual (as it is today). This is also your human review gate, which is worth keeping.
- **Drewry WCI** has no API; the scraper is best-effort. If it breaks, the email says so; copy `state/wci_manual.example.yaml` to `state/wci_manual.yaml` and update the three numbers on Thursdays.
- **Paywalled sources** (some Furniture Today pieces) fall back to the RSS excerpt and are flagged for fact-checking.
- **Google News items** link through news.google.com; they are flagged so you can swap in the publisher URL.
- Model prices in `settings.yaml` are for the cost line in the email only; verify them against Anthropic's pricing page.
- **Dedupe timing**: each run records its picks as `draft` rows in `state/history.jsonl`. Reruns on the same date can reuse those stories; from the next day on they count as published. The live Substack feed is also checked every run, so anything you actually published is caught regardless.
- **Hero image**: the pipeline uses the lead (og:image) photo from one of the Top Stories. If none of the picks has a usable image, the edition renders without one and the email says so.

## Local development

```bash
pip install -r requirements.txt
python tests/test_offline.py                         # unit tests, no network, no tokens
python -m brief.main --mock --date 2026-09-17        # full pipeline on fixtures, no tokens
open out/2026-09-17/review_email.html
export ANTHROPIC_API_KEY=... FRED_API_KEY=...
python -m brief.main --force                         # real run, writes out/, doesn't email
python -m brief.main --notes "Lead with the Fed hike" --no-email
```

Every run writes `out/{date}/`: `candidates.json` (what was collected), `picks.json` (call 1), `content_raw.json` (call 2), `content.json` (after validation), `market.json`, `market_pulse_card.png`, `paste.html`, `title_subtitle.txt`, `review_email.html`. On GitHub the same folder is attached to the workflow run as an artifact for 14 days.

## Layout

```
brief/        collect · dedupe · extract · llm (the 2 calls) · market · card · render · notify · main
config/       settings, feeds, tickers, style_guide.md
templates/    newsletter.html.j2 (your current Substack markup), review_email.html.j2
scripts/      backfill_history.py
tests/        test_offline.py + fixtures/ (a real edition, used by --mock)
state/        history.jsonl (dedupe corpus), costs.csv (per-run spend), wci.json
docs/         GitHub Pages: pulse/{date}.png, drafts/{date}.html
.github/workflows/daily.yml (weekday schedule + manual run with notes)
.github/workflows/maintenance.yml (check-feeds · backfill-history · test-offline · mock-run)
```

"""The only two model calls: select (Haiku) and write (Sonnet).

Both return structured JSON. Articles are referenced by id, never by URL, so
links cannot be hallucinated and output tokens stay small.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .util import Settings, log

try:
    import anthropic
except ImportError:  # tests without the SDK installed
    anthropic = None


@dataclass
class Usage:
    calls: list[dict] = field(default_factory=list)

    def add(self, model: str, inp: int, out: int, prices: dict) -> None:
        p = prices.get(model, {"input": 0, "output": 0})
        cost = inp / 1e6 * p["input"] + out / 1e6 * p["output"]
        self.calls.append({"model": model, "input_tokens": inp, "output_tokens": out, "cost_usd": round(cost, 4)})

    @property
    def total(self) -> float:
        return round(sum(c["cost_usd"] for c in self.calls), 4)


def _client():
    if anthropic is None:
        raise RuntimeError("anthropic SDK not installed")
    return anthropic.Anthropic()


def _json_from(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start:end + 1])


def call_model(cfg: Settings, model: str, system: str, user: str, max_tokens: int, usage: Usage,
               mock: dict | None = None) -> dict:
    if mock is not None:
        usage.add(model, len(system + user) // 4, len(json.dumps(mock)) // 4, cfg.settings["models"]["prices_per_mtok"])
        return mock
    client = _client()
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, temperature=0.4,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    usage.add(model, resp.usage.input_tokens, resp.usage.output_tokens, cfg.settings["models"]["prices_per_mtok"])
    log.info("%s: %d in / %d out", model, resp.usage.input_tokens, resp.usage.output_tokens)
    return _json_from(text)


# ---------------------------------------------------------------- call 1: select

SELECT_SYSTEM = """You are the editor of The Furniture Brief, a weekday newsletter for furniture, mattress and home-furnishings retailers and brands. You will receive one-line candidate articles and must choose which go in each section of today's edition. Return only JSON."""


def select_prompt(cfg: Settings, candidates: list[dict], recent: list[str], notes: str, date_str: str) -> str:
    secs = []
    for s in cfg.sections:
        secs.append(f'- "{s["key"]}" ({s["title"]}): pick {s["count"]} (minimum {s["min"]})')
    lines = []
    for c in candidates:
        flags = []
        if c.get("paywalled"):
            flags.append("paywall")
        if c.get("google_news"):
            flags.append("gnews")
        if c.get("alternates"):
            flags.append(f"+{len(c['alternates'])} outlets")
        ex = (c.get("excerpt") or "")[:160]
        lines.append(f'{c["id"]} | {c["source"]} | {c["age_hours"]:.0f}h | {c["title"]} | {ex}'
                     + (f' | [{", ".join(flags)}]' if flags else ""))
    recent_block = "\n".join(f"- {h}" for h in recent) if recent else "(none)"
    notes_block = f"\nEDITOR NOTES FOR TODAY (follow these):\n{notes}\n" if notes else ""
    return f"""Edition date: {date_str}

SECTIONS (choose distinct articles; an article may appear in only one section):
{chr(10).join(secs)}

Guidance:
- Top Stories: the five items a furniture or mattress retailer most needs today. Prefer furniture-specific reporting (Furniture Today, Home News Now, BedTimes) and stories covered by more than one outlet. Order by importance.
- Industry Moves: people moves, earnings, openings/closings, bankruptcies, M&A, trade shows, macro that hits the category.
- Retail & Consumer Trends: consumer behavior, merchandising, financing, store formats, DTC and marketplace moves from any retail category that a home-furnishings operator can learn from.
- Supply Chain & Trade: only genuinely about tariffs, freight, sourcing, logistics. Return [] if nothing fits.
- AI & Tech Watch: AI tools, agentic commerce, retail tech, AI shopping studies. Skip AI stories with no plausible retail angle (model research, chip news, politics).
- Skip anything that duplicates a recently covered headline unless it has clearly new facts.
- Also choose "backups": 4 spare article ids, best first, in case a pick cannot be extracted.
- Choose "hero": the article id whose lead image should top the edition (a Top Story with a likely photo).
{notes_block}
RECENTLY COVERED HEADLINES (avoid repeats):
{recent_block}

CANDIDATES (id | source | age | title | excerpt | flags):
{chr(10).join(lines)}

Return JSON exactly like:
{{"top_stories": ["id", ...], "industry_moves": [...], "retail_trends": [...], "supply_chain": [...], "ai_tech": [...], "backups": [...], "hero": "id"}}"""


def select(cfg: Settings, candidates: list[dict], recent: list[str], notes: str, date_str: str,
           usage: Usage, mock: dict | None = None) -> dict:
    m = cfg.settings["models"]
    raw = call_model(cfg, m["selector"], SELECT_SYSTEM,
                     select_prompt(cfg, candidates, recent, notes, date_str),
                     int(m["selector_max_tokens"]), usage, mock)
    valid = {c["id"] for c in candidates}
    out: dict = {}
    used: set[str] = set()
    for s in cfg.sections:
        ids = []
        for i in raw.get(s["key"], []) or []:
            if i in valid and i not in used:
                ids.append(i)
                used.add(i)
        out[s["key"]] = ids[: s["count"]]
    out["backups"] = [i for i in raw.get("backups", []) or [] if i in valid and i not in used][:cfg.settings["extract"]["backups"]]
    hero = raw.get("hero")
    out["hero"] = hero if hero in valid else (out["top_stories"][0] if out["top_stories"] else None)
    return out


# ----------------------------------------------------------------- call 2: write

WRITE_SYSTEM_TEMPLATE = """You write The Furniture Brief. Follow the style guide exactly. You will receive the selected articles with their full text (or an excerpt when marked). Reference articles ONLY by their id. Return only JSON.

STYLE GUIDE
===========
{style_guide}"""


def write_prompt(cfg: Settings, date_str: str, weekday: str, picks: dict, articles: dict[str, dict],
                 backups: list[dict], notes: str) -> str:
    parts = [f"Edition date: {date_str} ({weekday})"]
    if notes:
        parts.append(f"\nEDITOR NOTES FOR TODAY (these override the defaults):\n{notes}")
    parts.append("\nSECTION TARGETS:")
    for s in cfg.sections:
        lo, hi = s["words"]
        parts.append(f'- {s["key"]} ({s["title"]}): {len(picks.get(s["key"], []))} items assigned, {lo}-{hi} words each')
    parts.append("\nASSIGNED ARTICLES:")
    for s in cfg.sections:
        for i in picks.get(s["key"], []):
            a = articles.get(i)
            if not a:
                continue
            tag = " [EXCERPT ONLY - paywalled; write only what this supports]" if a.get("excerpt_only") else ""
            img = " [has lead image]" if a.get("image") else ""
            parts.append(f'\n--- id: {i} | section: {s["key"]} | source: {a["source"]} | published: {a["published"][:16]}{tag}{img}\n'
                         f'TITLE: {a["title"]}\nTEXT:\n{a["text"]}')
    if backups:
        parts.append("\nBACKUP ARTICLES (use one only to replace an assigned article that is too thin; keep its section):")
        for a in backups:
            parts.append(f'\n--- id: {a["id"]} | source: {a["source"]}\nTITLE: {a["title"]}\nEXCERPT: {a["text"]}')
    parts.append("""
Return JSON with exactly this shape (article_id values must come from the ids above):
{
  "title": "...",
  "subtitle": "...",
  "greeting": "...",
  "hero": "article_id",
  "sections": {
    "top_stories": [{"headline": "...", "summary": "...", "article_id": "..."}],
    "industry_moves": [{"headline": "...", "summary": "...", "article_id": "..."}],
    "retail_trends": [...],
    "supply_chain": [...],
    "ai_tech": [...]
  },
  "one_thing": {"headline": "...", "body": "..."},
  "closing": "..."
}""")
    return "\n".join(parts)


def write(cfg: Settings, date_str: str, weekday: str, picks: dict, articles: dict[str, dict],
          backups: list[dict], notes: str, usage: Usage, mock: dict | None = None) -> dict:
    m = cfg.settings["models"]
    system = WRITE_SYSTEM_TEMPLATE.format(style_guide=cfg.style_guide)
    return call_model(cfg, m["writer"], system,
                      write_prompt(cfg, date_str, weekday, picks, articles, backups, notes),
                      int(m["writer_max_tokens"]), usage, mock)

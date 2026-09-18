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


def _unstringify(obj):
    """Tool inputs sometimes arrive with a nested object encoded as a JSON string. Decode those."""
    if isinstance(obj, dict):
        return {k: _unstringify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unstringify(v) for v in obj]
    if isinstance(obj, str):
        t = obj.strip()
        if (t.startswith("{") and t.endswith("}")) or (t.startswith("[") and t.endswith("]")):
            try:
                return _unstringify(json.loads(t))
            except json.JSONDecodeError:
                try:
                    return _unstringify(json.loads(_repair_json(t)))
                except json.JSONDecodeError:
                    return obj
    return obj


def describe_shape(obj, depth: int = 0) -> str:
    """Compact type map for logs, e.g. {title:str, sections:{top_stories:list[5], ...}}."""
    if isinstance(obj, dict):
        if depth > 2:
            return "{...}"
        return "{" + ", ".join(f"{k}:{describe_shape(v, depth + 1)}" for k, v in list(obj.items())[:12]) + "}"
    if isinstance(obj, list):
        return f"list[{len(obj)}]" + (f" of {describe_shape(obj[0], depth + 1)}" if obj and depth < 2 else "")
    if isinstance(obj, str):
        return f"str({len(obj)}:{obj[:40]!r})" if len(obj) > 60 and (obj.lstrip().startswith(("{", "["))) else "str"
    return type(obj).__name__


def count_items(content: dict) -> int:
    secs = content.get("sections") if isinstance(content, dict) else None
    if not isinstance(secs, dict):
        return 0
    return sum(len(v) for v in secs.values() if isinstance(v, list))


def _repair_json(text: str) -> str:
    """Fix the usual model slips: trailing commas, smart quotes around keys, stray fences."""
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return text


def call_model(cfg: Settings, model: str, system: str, user: str, max_tokens: int, usage: Usage,
               mock: dict | None = None, schema: dict | None = None) -> dict:
    """One model call returning a dict. With `schema`, the answer is forced through a tool
    call so the API guarantees well-formed JSON; otherwise free text is parsed (with repair)."""
    if mock is not None:
        usage.add(model, len(system + user) // 4, len(json.dumps(mock)) // 4, cfg.settings["models"]["prices_per_mtok"])
        return mock
    client = _client()
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "system": system,
                    "messages": [{"role": "user", "content": user}]}
    if schema is not None:
        kwargs["tools"] = [{"name": "emit", "description": "Return the finished result.", "input_schema": schema}]
        kwargs["tool_choice"] = {"type": "tool", "name": "emit"}
    # Thinking is on by default for Sonnet 5 / Opus 5 and its tokens count against
    # max_tokens. Off by default here: the prompt already contains the full material.
    # settings.yaml models.thinking: disabled | low | medium | high
    mode = str(cfg.settings["models"].get("thinking", "disabled")).lower()
    if mode == "disabled":
        kwargs["thinking"] = {"type": "disabled"}
    else:
        kwargs["thinking"] = {"type": "adaptive"}
        kwargs["output_config"] = {"effort": mode}
    resp = client.messages.create(**kwargs)
    usage.add(model, resp.usage.input_tokens, resp.usage.output_tokens, cfg.settings["models"]["prices_per_mtok"])
    log.info("%s: %d in / %d out (stop=%s)", model, resp.usage.input_tokens, resp.usage.output_tokens, resp.stop_reason)
    if resp.stop_reason == "max_tokens":
        raise RuntimeError(f"{model} hit max_tokens={max_tokens} before finishing; raise models.*_max_tokens in settings.yaml")
    for b in resp.content:
        if getattr(b, "type", "") == "tool_use" and isinstance(b.input, dict):
            return _unstringify(b.input)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    try:
        return _unstringify(_json_from(text))
    except json.JSONDecodeError as e:
        log.warning("model JSON needed repair: %s", e)
        return _unstringify(_json_from(_repair_json(text)))


# ---------------------------------------------------------------- schemas

def select_schema(cfg: Settings) -> dict:
    props = {s["key"]: {"type": "array", "items": {"type": "string"}} for s in cfg.sections}
    props["backups"] = {"type": "array", "items": {"type": "string"}}
    props["hero"] = {"type": "string"}
    return {"type": "object", "properties": props, "required": list(props)}


def write_schema(cfg: Settings) -> dict:
    item = {"type": "object",
            "properties": {"headline": {"type": "string"}, "summary": {"type": "string"}, "article_id": {"type": "string"}},
            "required": ["headline", "summary", "article_id"]}
    sections = {s["key"]: {"type": "array", "items": item} for s in cfg.sections}
    return {"type": "object",
            "properties": {
                "title": {"type": "string"}, "subtitle": {"type": "string"}, "greeting": {"type": "string"},
                "hero": {"type": "string"},
                "sections": {"type": "object", "properties": sections, "required": list(sections)},
                "one_thing": {"type": "object", "properties": {"headline": {"type": "string"}, "body": {"type": "string"}},
                              "required": ["headline", "body"]},
                "closing": {"type": "string"}},
            "required": ["title", "subtitle", "greeting", "hero", "sections", "one_thing", "closing"]}


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
        if c.get("via"):
            flags.append(f"via {c['via']}")
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
- Two recurring themes of this newsletter deserve a slight edge when candidates are otherwise equal: (a) who carries inventory risk (vendor quick-ship and in-stock programs, drop-ship, direct-to-consumer delivery, warehouses, freight, endless aisle, DTC brands opening showrooms); (b) online share of furniture sales (e-commerce results and penetration, marketplaces, agentic commerce, AI shopping tools, visualizers, retail media, checkout and financing).
- Also choose "backups": 4 spare article ids, best first, in case a pick cannot be extracted.
- Choose "hero": the article id whose lead image should top the edition (a Top Story with a likely photo).
{notes_block}
RECENTLY COVERED HEADLINES (avoid repeats):
{recent_block}

CANDIDATES (id | source | age | title | excerpt | flags):
{chr(10).join(lines)}

Return your selection by calling the emit tool with:
{{"top_stories": ["id", ...], "industry_moves": [...], "retail_trends": [...], "supply_chain": [...], "ai_tech": [...], "backups": [...], "hero": "id"}}"""


def select(cfg: Settings, candidates: list[dict], recent: list[str], notes: str, date_str: str,
           usage: Usage, mock: dict | None = None) -> dict:
    m = cfg.settings["models"]
    raw = call_model(cfg, m["selector"], SELECT_SYSTEM,
                     select_prompt(cfg, candidates, recent, notes, date_str),
                     int(m["selector_max_tokens"]), usage, mock, schema=select_schema(cfg))
    valid = {c["id"] for c in candidates}

    def ids_of(v) -> list[str]:
        """Tolerate a string, a comma/space separated string, or nested lists/dicts from the model."""
        if v is None:
            return []
        if isinstance(v, str):
            return [x for x in re.split(r"[,\s]+", v.strip()) if x]
        if isinstance(v, dict):
            return ids_of(v.get("id") or v.get("article_id") or list(v.values()))
        out_ids: list[str] = []
        for x in v:
            out_ids.extend(ids_of(x))
        return out_ids

    out: dict = {}
    used: set[str] = set()
    for s in cfg.sections:
        ids = []
        for i in ids_of(raw.get(s["key"])):
            if i in valid and i not in used:
                ids.append(i)
                used.add(i)
        out[s["key"]] = ids[: s["count"]]
    out["backups"] = [i for i in ids_of(raw.get("backups")) if i in valid and i not in used][:cfg.settings["extract"]["backups"]]
    hero = next(iter(ids_of(raw.get("hero"))), None)
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
        parts.append(f'- {s["key"]} ({s["title"]}): {len(picks.get(s["key"], []))} items assigned, {lo}-{hi} words each (HARD CAP {hi}; count before you finish)')
    parts.append("\nASSIGNED ARTICLES:")
    for s in cfg.sections:
        for i in picks.get(s["key"], []):
            a = articles.get(i)
            if not a:
                continue
            tag = " [EXCERPT ONLY - paywalled; write only what this supports]" if a.get("excerpt_only") else ""
            img = " [has lead image]" if a.get("image") else ""
            lo, hi = s["words"]
            parts.append(f'\n--- id: {i} | section: {s["key"]} | summary length: {lo}-{hi} words | source: {a["source"]} | published: {a["published"][:16]}{tag}{img}\n'
                         f'TITLE: {a["title"]}\nTEXT:\n{a["text"]}')
    if backups:
        parts.append("\nBACKUP ARTICLES (use one only to replace an assigned article that is too thin; keep its section):")
        for a in backups:
            parts.append(f'\n--- id: {a["id"]} | source: {a["source"]}\nTITLE: {a["title"]}\nEXCERPT: {a["text"]}')
    parts.append("""
Return the edition by calling the emit tool with exactly this shape (article_id values must come from the ids above):
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
                      int(m["writer_max_tokens"]), usage, mock, schema=write_schema(cfg))

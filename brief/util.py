"""Shared helpers: config loading, paths, dates, logging, hashing."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
STATE = ROOT / "state"
DOCS = ROOT / "docs"
OUT = ROOT / "out"
TEMPLATES = ROOT / "templates"
FIXTURES = ROOT / "tests" / "fixtures"

log = logging.getLogger("brief")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.ERROR)
    logging.getLogger("yfinance").setLevel(logging.ERROR)
    logging.getLogger("peewee").setLevel(logging.ERROR)


def load_yaml(name: str) -> dict:
    with open(CONFIG / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Settings:
    settings: dict
    feeds: dict
    tickers: dict
    style_guide: str

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            settings=load_yaml("settings.yaml"),
            feeds=load_yaml("feeds.yaml"),
            tickers=load_yaml("tickers.yaml"),
            style_guide=(CONFIG / "style_guide.md").read_text(encoding="utf-8"),
        )

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.settings["newsletter"]["timezone"])

    @property
    def sections(self) -> list[dict]:
        return self.settings["sections"]


def today_local(cfg: Settings) -> date:
    return datetime.now(cfg.tz).date()


def edition_date(cfg: Settings, override: str | None) -> date:
    if override:
        return date.fromisoformat(override)
    return today_local(cfg)


def window_hours(cfg: Settings, d: date) -> int:
    w = cfg.settings["window"]
    return int(w["monday_hours"]) if d.weekday() == 0 else int(w["hours"])


def long_date(d: date) -> str:
    return d.strftime("%A, %B %-d, %Y")


def short_date(d: date) -> str:
    return d.strftime("%a %b %-d")


def stable_id(*parts: str, n: int = 8) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return h[:n]


def normalize_url(url: str) -> str:
    """Strip tracking params and fragments so the same article dedupes."""
    url = (url or "").strip()
    url = re.sub(r"#.*$", "", url)
    url = re.sub(r"[?&](utm_[a-z]+|fbclid|gclid|ref|source|mc_cid|mc_eid)=[^&]*", "", url)
    url = re.sub(r"\?&", "?", url).rstrip("?&")
    url = re.sub(r"^http://", "https://", url)
    url = re.sub(r"^https://www\.", "https://", url)
    return url.rstrip("/").lower()


def normalize_title(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "")).strip().lower()
    t = re.sub(r"[^a-z0-9 ]", "", t)
    return t


def word_count(s: str) -> int:
    return len(re.findall(r"\b\w[\w'’-]*\b", s or ""))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default

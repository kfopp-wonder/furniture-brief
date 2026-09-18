"""Market Pulse data: yfinance for equities/crude, FRED for rates and fuel, Drewry WCI scrape.

Every quote is sanity-checked; problems become flags for the review email, never
silent blanks or garbage values on the published card.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import requests
import yaml

from .util import STATE, Settings, env, log

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
WCI_FILE = STATE / "wci.json"
WCI_MANUAL = STATE / "wci_manual.yaml"


def _fmt(fmt: str, v: float | None) -> str:
    return fmt.format(v) if v is not None else "—"


def _pct(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / prev * 100


def _row(label: str, value: float | None, prev: float | None, fmt: str, change: str = "pct",
         sub: str = "", flag: str | None = None) -> dict:
    if change == "bp" and value is not None and prev is not None:
        delta = (value - prev) * 100
        change_text = f"{delta:+.0f} bp" if abs(delta) >= 0.5 else "—"
        direction = "up" if delta >= 0.5 else "down" if delta <= -0.5 else "flat"
    else:
        p = _pct(value, prev)
        change_text = f"{p:+.2f}%" if p is not None and abs(p) >= 0.005 else "—"
        direction = "up" if p is not None and p >= 0.005 else "down" if p is not None and p <= -0.005 else "flat"
    return {"label": label, "sub": sub, "value": value, "value_text": _fmt(fmt, value),
            "change_text": change_text, "direction": direction, "flag": flag}


# ---------------------------------------------------------------- yfinance

def yf_history(symbols: list[str], days: int) -> dict[str, list[tuple[str, float]]]:
    """{symbol: [(date, close), ...]} ascending. Uses daily closes."""
    import yfinance as yf
    out: dict[str, list[tuple[str, float]]] = {}
    if not symbols:
        return out
    data = yf.download(symbols, period=f"{days}d", interval="1d", auto_adjust=False,
                       progress=False, group_by="ticker", threads=True)
    for sym in symbols:
        try:
            df = data[sym] if len(symbols) > 1 else data
            closes = df["Close"].dropna()
            out[sym] = [(idx.strftime("%Y-%m-%d"), float(v)) for idx, v in closes.items()]
        except Exception as e:  # noqa: BLE001
            log.warning("yfinance %s: %s", sym, e)
            out[sym] = []
    return out


def _last_two(series: list[tuple[str, float]]) -> tuple[float | None, float | None, str | None]:
    if not series:
        return None, None, None
    cur = series[-1]
    prev = series[-2] if len(series) > 1 else (None, None)
    return cur[1], prev[1], cur[0]


# ---------------------------------------------------------------- FRED

def fred_series(series_id: str, api_key: str | None, days: int = 30) -> list[tuple[str, float]]:
    if not api_key:
        return []
    start = (date.today() - timedelta(days=days)).isoformat()
    try:
        r = requests.get(FRED_URL, params={"series_id": series_id, "api_key": api_key,
                                           "file_type": "json", "observation_start": start,
                                           "sort_order": "asc"}, timeout=20)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        return [(o["date"], float(o["value"])) for o in obs if o.get("value") not in (".", None, "")]
    except Exception as e:  # noqa: BLE001
        log.warning("FRED %s: %s", series_id, e)
        return []


# ---------------------------------------------------------------- Drewry WCI

def scrape_wci(url: str, timeout: int = 20) -> dict | None:
    """Best-effort: find Shanghai-LA, Shanghai-NY and composite $/FEU figures on Drewry's page."""
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        text = re.sub(r"<[^>]+>", " ", r.text)
        text = re.sub(r"\s+", " ", text)
    except Exception as e:  # noqa: BLE001
        log.warning("WCI scrape failed: %s", e)
        return None

    def find(label_re: str) -> tuple[float | None, float | None]:
        m = re.search(label_re + r".{0,160}?\$\s?([\d,]{4,6})(?:\s*per\s*40ft|/FEU| per FEU)?", text, re.I)
        if not m:
            return None, None
        val = float(m.group(1).replace(",", ""))
        tail = text[m.end(): m.end() + 160]
        pm = re.search(r"([+-]?\d{1,2}(?:\.\d+)?)\s?%", tail)
        pct = float(pm.group(1)) if pm else None
        return val, pct

    comp, comp_pct = find(r"(?:composite index|World Container Index)[^$]{0,120}?(?:decreased|increased|rose|fell|dropped|up|down|remained)")
    la, la_pct = find(r"Shanghai\s*(?:to|-|–)\s*Los Angeles")
    ny, ny_pct = find(r"Shanghai\s*(?:to|-|–)\s*New York")
    if not any([comp, la, ny]):
        return None
    return {"composite": comp, "composite_pct": comp_pct, "shanghai_la": la, "shanghai_la_pct": la_pct,
            "shanghai_ny": ny, "shanghai_ny_pct": ny_pct, "as_of": date.today().isoformat(), "source": "scrape"}


def load_wci(cfg: Settings) -> tuple[dict | None, str | None]:
    """Manual override > fresh scrape > cached value (flagged if older than 10 days)."""
    if WCI_MANUAL.exists():
        with open(WCI_MANUAL, encoding="utf-8") as f:
            m = yaml.safe_load(f) or {}
        m["source"] = "manual"
        return m, None
    url = cfg.tickers["container_rates"]["source_url"]
    fresh = scrape_wci(url)
    if fresh:
        WCI_FILE.parent.mkdir(exist_ok=True)
        WCI_FILE.write_text(json.dumps(fresh, indent=2))
        return fresh, None
    if WCI_FILE.exists():
        cached = json.loads(WCI_FILE.read_text())
        age = (date.today() - date.fromisoformat(cached.get("as_of", "2000-01-01"))).days
        flag = f"Drewry WCI scrape failed; showing cached figures from {cached.get('as_of')} ({age} days old)."
        return cached, flag
    return None, "Drewry WCI unavailable (scrape failed, no cache). Copy state/wci_manual.example.yaml to state/wci_manual.yaml."


# ---------------------------------------------------------------- assemble

def build_market(cfg: Settings, fixture: dict | None = None) -> dict:
    """Returns {"markets": [...], "container": [...], "stocks": [...], "flags": [...], "as_of": str}."""
    t = cfg.tickers
    mcfg = cfg.settings["market"]
    flags: list[str] = []
    min_price = float(mcfg["min_price"])
    max_move = float(mcfg["max_abs_move_pct"])

    if fixture:
        yfd, fred, wci, wci_flag = fixture["yf"], fixture["fred"], fixture.get("wci"), None
    else:
        symbols = [s["symbol"] for s in t["stocks"]] + [m["symbol"] for m in t["markets"] if m["kind"] == "yfinance"]
        yfd = yf_history(symbols, int(mcfg["history_days"]))
        key = env("FRED_API_KEY")
        if not key:
            flags.append("FRED_API_KEY not set: Treasury, gas, diesel and mortgage rows are blank.")
        fred = {m["series"]: fred_series(m["series"], key) for m in t["markets"] if m["kind"] == "fred"}
        wci, wci_flag = load_wci(cfg)
    if wci_flag:
        flags.append(wci_flag)

    markets = []
    as_of = None
    for m in t["markets"]:
        if m["kind"] == "yfinance":
            cur, prev, d = _last_two(yfd.get(m["symbol"], []))
            as_of = as_of or d
        else:
            cur, prev, d = _last_two(fred.get(m["series"], []))
        flag = None
        if cur is None:
            flag = f"{m['label']}: no data."
        elif prev is not None and m.get("change") != "bp":
            p = _pct(cur, prev)
            if p is not None and abs(p) > max_move:
                flag = f"{m['label']}: move of {p:+.1f}% looks wrong."
        if flag:
            flags.append(flag)
        markets.append(_row(m["label"], cur, prev, m["format"], m.get("change", "pct"), flag=flag))

    container = []
    ccfg = t["container_rates"]
    for r in ccfg["rows"]:
        val = (wci or {}).get(r["key"])
        pct = (wci or {}).get(r["key"] + "_pct")
        prev = val / (1 + pct / 100) if (val is not None and pct is not None) else None
        container.append(_row(r["label"], val, prev, "${:,.0f}/FEU"))

    stocks = []
    for s in t["stocks"]:
        cur, prev, d = _last_two(yfd.get(s["symbol"], []))
        flag = None
        if cur is None:
            flag = f"{s['symbol']}: no quote."
        elif cur < min_price:
            flag = f"{s['symbol']}: price ${cur:.2f} is under ${min_price:.2f}; check ticker."
        elif prev is not None:
            p = _pct(cur, prev)
            if p is not None and abs(p) > max_move:
                flag = f"{s['symbol']}: {p:+.1f}% day move; verify before publishing."
        if flag:
            flags.append(flag)
        stocks.append(_row(s["symbol"], cur, prev, "${:,.2f}", sub=s["name"], flag=flag))
    stocks.sort(key=lambda r: -(r["value"] or 0))

    return {"markets": markets, "container": container, "stocks": stocks, "flags": flags,
            "as_of": as_of or date.today().isoformat(),
            "wci_meta": {k: (wci or {}).get(k) for k in ("as_of", "source")},
            "container_title": ccfg["title"], "container_subtitle": ccfg["subtitle"]}

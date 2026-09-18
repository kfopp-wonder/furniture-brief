"""Source candidate stories from newsletters in a Gmail inbox (IMAP, zero model tokens).

Reads recent emails from the senders listed in config/newsletters.yaml, pulls the
article links out of each newsletter's HTML, and turns them into candidates that
join the RSS candidates. Tracking links are resolved to the publisher URL at
extraction time (only for the stories the selector actually picks).

Credentials: NEWSLETTER_IMAP_USER / NEWSLETTER_IMAP_PASS, falling back to
SMTP_USER / SMTP_PASS (a Gmail app password works for IMAP too).

    python -m brief.main --list-newsletters   # scan the inbox, propose senders
"""
from __future__ import annotations

import email
import html as htmllib
import imaplib
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import urlparse

from .util import Settings, env, load_yaml, log, normalize_title, normalize_url

IMAP_HOST = "imap.gmail.com"

SKIP_LINK_RE = re.compile(
    r"unsubscribe|manage.?preferences|update.?profile|view.?in.?browser|view.?online|privacy|terms|"
    r"mailto:|twitter\.com|x\.com/|linkedin\.com|facebook\.com|instagram\.com|youtube\.com/@|threads\.net|"
    r"apple\.com/.*app|play\.google|substack\.com/(app|subscribe|redirect/app)|/subscribe|/signup|/login|"
    r"forward.?to.?a.?friend|share|refer|sponsor|advertis|\.(png|jpg|jpeg|gif|svg|webp)(\?|$)",
    re.I,
)
SKIP_TEXT_RE = re.compile(
    r"^(read more|read on|learn more|click here|here|link|view|open|continue reading|read the full|"
    r"subscribe|sign up|unsubscribe|share|tweet|reply|forward|more|watch|listen|source|via|app)\b[\s.!»→>]*$",
    re.I,
)


def _creds() -> tuple[str | None, str | None]:
    return (env("NEWSLETTER_IMAP_USER") or env("SMTP_USER"), env("NEWSLETTER_IMAP_PASS") or env("SMTP_PASS"))


def _connect() -> imaplib.IMAP4_SSL | None:
    user, pw = _creds()
    if not (user and pw):
        log.warning("newsletters: no IMAP credentials (NEWSLETTER_IMAP_* or SMTP_*)")
        return None
    m = imaplib.IMAP4_SSL(IMAP_HOST, 993)
    m.login(user, pw)
    return m


def _decode(s: str | None) -> str:
    if not s:
        return ""
    try:
        return str(make_header(decode_header(s)))
    except Exception:  # noqa: BLE001
        return s


def _body_html(msg) -> str:
    html_part, text_part = None, None
    for part in msg.walk():
        ct = part.get_content_type()
        if part.get_content_disposition() == "attachment":
            continue
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            continue
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if ct == "text/html" and html_part is None:
            html_part = text
        elif ct == "text/plain" and text_part is None:
            text_part = text
    return html_part or (f"<pre>{htmllib.escape(text_part)}</pre>" if text_part else "")


def _strip(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def extract_links(html: str, max_links: int) -> list[dict]:
    """Return [{title, url, excerpt}] for article-looking links, in document order."""
    out, seen = [], set()
    # split on anchors so we can grab the text that follows each link as an excerpt
    parts = re.split(r'(<a\s[^>]*href="[^"]+"[^>]*>.*?</a>)', html, flags=re.S | re.I)
    for i, chunk in enumerate(parts):
        m = re.match(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', chunk, flags=re.S | re.I)
        if not m:
            continue
        href = htmllib.unescape(m.group(1)).strip()
        text = _strip(m.group(2))
        if not href.startswith("http") or SKIP_LINK_RE.search(href):
            continue
        if len(text.split()) < 4 or len(text) > 200 or SKIP_TEXT_RE.match(text):
            continue
        key = normalize_url(href)
        if key in seen:
            continue
        seen.add(key)
        following = _strip(parts[i + 1]) if i + 1 < len(parts) else ""
        excerpt = following[:400]
        out.append({"title": text, "url": href, "excerpt": excerpt})
        if len(out) >= max_links:
            break
    return out


def _source_from_url(url: str, names: dict) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    for dom, name in names.items():
        if host == dom or host.endswith("." + dom):
            return name
    base = host.split(".")[-2] if host.count(".") >= 1 else host
    return base.replace("-", " ").title() if base else "Web"


def collect_newsletters(cfg: Settings, now: datetime, hours: int) -> tuple[list[dict], dict]:
    """Returns (candidates, report). Never raises."""
    ncfg = load_yaml("newsletters.yaml")
    senders = ncfg.get("senders") or []
    report = {"emails": 0, "links": 0, "senders_matched": Counter(), "error": None}
    if not senders:
        report["error"] = "no senders configured in config/newsletters.yaml"
        return [], report
    max_links = int(ncfg.get("max_links_per_email", 12))
    names = ncfg.get("publisher_names") or {}
    kw = cfg.feeds.get("keywords", {})
    from .collect import score_item  # local import to avoid a cycle

    try:
        m = _connect()
        if m is None:
            report["error"] = "no IMAP credentials"
            return [], report
        m.select('"[Gmail]/All Mail"' if ncfg.get("all_mail", True) else "INBOX", readonly=True)
        since = (now - timedelta(hours=hours + 12)).strftime("%d-%b-%Y")
        typ, data = m.search(None, f'(SINCE {since})')
        ids = data[0].split() if typ == "OK" else []
        cutoff = now - timedelta(hours=hours)
        items: list[dict] = []
        for uid in ids[-400:]:
            typ, msgdata = m.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM DATE SUBJECT)])")
            if typ != "OK" or not msgdata or not msgdata[0]:
                continue
            hdr = email.message_from_bytes(msgdata[0][1])
            _, addr = parseaddr(hdr.get("From", ""))
            addr = addr.lower()
            sender = next((s for s in senders if _match_sender(s, addr)), None)
            if not sender:
                continue
            try:
                dt = parsedate_to_datetime(hdr.get("Date", "")).astimezone(timezone.utc)
            except Exception:  # noqa: BLE001
                continue
            if dt < cutoff:
                continue
            typ, full = m.fetch(uid, "(BODY.PEEK[])")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(full[0][1])
            subject = _decode(msg.get("Subject"))
            links = extract_links(_body_html(msg), max_links)
            report["emails"] += 1
            report["senders_matched"][sender["name"]] += 1
            for link in links:
                score, is_ai = score_item(link["title"], link["excerpt"], {"weight": sender.get("weight", 1.0)}, kw)
                if score < 0:          # negative keywords (crypto, sports...) still apply
                    continue
                base = 2.5 * float(sender.get("weight", 1.0))
                score = max(score, base)
                items.append({
                    "title": link["title"], "url": link["url"], "norm_url": normalize_url(link["url"]),
                    "norm_title": normalize_title(link["title"]), "published": dt.isoformat(),
                    "age_hours": round((now - dt).total_seconds() / 3600, 1),
                    "source": _source_from_url(link["url"], names), "via": sender["name"], "via_subject": subject,
                    "feed_id": "newsletter:" + sender["name"].lower().replace(" ", "_"),
                    "paywalled": False, "google_news": False, "newsletter": True,
                    "excerpt": link["excerpt"], "score": round(score, 2),
                    "is_ai": bool(is_ai or sender.get("ai", True)),
                    "sections_hint": sender.get("sections", ["ai_tech"]),
                })
            report["links"] += len(links)
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
        log.info("newsletters: %d emails from %d senders, %d links", report["emails"], len(report["senders_matched"]), report["links"])
        return items, report
    except (imaplib.IMAP4.error, OSError) as e:
        report["error"] = f"IMAP: {e}"
        log.warning("newsletters: %s", e)
        return [], report


def _match_sender(sender: dict, addr: str) -> bool:
    for pat in sender.get("match", []):
        pat = pat.lower()
        if pat.startswith("@"):
            if addr.endswith(pat):
                return True
        elif addr == pat:
            return True
    return False


def list_senders(days: int = 14, limit: int = 60) -> list[dict]:
    """Scan recent mail and rank senders that look like newsletters (List-Unsubscribe header)."""
    m = _connect()
    if m is None:
        raise RuntimeError("no IMAP credentials")
    m.select('"[Gmail]/All Mail"', readonly=True)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
    typ, data = m.search(None, f'(SINCE {since})')
    ids = data[0].split() if typ == "OK" else []
    stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "name": "", "unsub": 0, "subjects": []})
    for uid in ids[-1500:]:
        typ, msgdata = m.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT LIST-UNSUBSCRIBE)])")
        if typ != "OK" or not msgdata or not msgdata[0]:
            continue
        hdr = email.message_from_bytes(msgdata[0][1])
        name, addr = parseaddr(hdr.get("From", ""))
        addr = addr.lower()
        if not addr:
            continue
        st = stats[addr]
        st["count"] += 1
        st["name"] = st["name"] or _decode(name)
        if hdr.get("List-Unsubscribe"):
            st["unsub"] += 1
        if len(st["subjects"]) < 2:
            st["subjects"].append(_decode(hdr.get("Subject", ""))[:70])
    m.logout()
    rows = [{"address": a, **v} for a, v in stats.items() if v["unsub"] > 0]
    rows.sort(key=lambda r: (-r["count"], r["address"]))
    return rows[:limit]

"""Create the edition as a Substack draft through Substack's internal editor API.

Substack has no official write API. The web editor uses a small set of JSON
endpoints that have been stable for years and are wrapped by libraries such as
python-substack. We call them directly with requests:

    GET  https://substack.com/api/v1/user/profile/self          -> user id (byline)
    POST https://<pub>.substack.com/api/v1/image  {"image": ...}  -> hosted image URL
    POST https://<pub>.substack.com/api/v1/drafts  {draft_*}      -> draft (never published)

Auth is the `substack.sid` session cookie from a logged-in browser, stored as the
SUBSTACK_SID secret. Either the raw cookie value or a full "name=value; ..." cookie
string is accepted. If the cookie expires, the run still succeeds: the review email
just falls back to the paste workflow and says why.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date
from pathlib import Path

import requests

from .util import Settings, env, log, long_date

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


# ------------------------------------------------------------------ ProseMirror helpers

def _t(text: str, *marks: dict) -> dict:
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def _link(href: str) -> dict:
    return {"type": "link", "attrs": {"href": href, "target": "_blank", "rel": "noopener noreferrer nofollow", "class": None}}


STRONG = {"type": "strong"}
EM = {"type": "em"}


def _p(*inline: dict) -> dict:
    return {"type": "paragraph", "content": [n for n in inline if n]}


def _h(level: int, text: str) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [_t(text)]}


def _image(src: str, alt: str = "", href: str | None = None, width: int | None = None, height: int | None = None) -> dict:
    return {"type": "captionedImage", "content": [{
        "type": "image2",
        "attrs": {"src": src, "srcNoWatermark": None, "fullscreen": False, "imageSize": "normal",
                  "height": height, "width": width, "resizeWidth": None, "bytes": None, "alt": alt or None,
                  "title": None, "type": "image/png" if src.lower().endswith(".png") else "image/jpeg",
                  "href": href, "belowTheFold": False, "topImage": False, "internalRedirect": None},
    }]}


def _source_line(name: str, url: str) -> dict:
    return _p(_t("Source: ", EM), _t(name, EM, _link(url)))


def build_doc(cfg: Settings, d: date, content: dict, card_url: str | None) -> dict:
    """Edition -> ProseMirror doc mirroring templates/newsletter.html.j2."""
    doc: list[dict] = []
    doc.append(_p(_t(long_date(d).upper(), EM)))
    doc.append(_p(_t(content["greeting"])))
    hero = content.get("hero_image")
    if hero and hero.get("url"):
        doc.append(_image(hero["url"], alt=hero.get("alt", ""), href=hero.get("source_url")))

    for s in cfg.sections:
        if s["key"] == "retail_trends":
            doc.append(_h(2, "Market Pulse"))
            if card_url:
                doc.append(_image(card_url, alt="Market Pulse", href=card_url))
        items = content["sections"].get(s["key"], [])
        if not items:
            continue
        doc.append(_h(2, s["title"]))
        if s["kind"] == "story":
            for i, it in enumerate(items, 1):
                doc.append(_h(3, f"{i}. {it['headline']}"))
                doc.append(_p(_t(it["summary"])))
                doc.append(_source_line(it["source_name"], it["source_url"]))
        else:
            li = []
            for it in items:
                li.append({"type": "list_item", "content": [
                    _p(_t(it["headline"], STRONG), _t(" - " + it["summary"])),
                    _source_line(it["source_name"], it["source_url"]),
                ]})
            doc.append({"type": "bullet_list", "content": li})

    ot = content.get("one_thing") or {}
    if ot.get("headline"):
        doc.append({"type": "blockquote", "content": [
            _p(_t("The One Thing", STRONG)),
            _p(_t(ot["headline"], STRONG)),
            _p(_t(ot.get("body", ""), EM)),
        ]})
    doc.append({"type": "horizontal_rule"})
    doc.append(_p(_t(content["closing"])))
    doc.append(_p(_t(cfg.settings["newsletter"]["footer"], EM)))
    return {"type": "doc", "content": doc}


# ------------------------------------------------------------------ API client

class SubstackError(RuntimeError):
    pass


class Substack:
    def __init__(self, publication_url: str, sid: str, timeout: int = 30):
        self.pub = publication_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json"})
        cookies = self._parse_cookie(sid)
        for k, v in cookies.items():
            self.s.cookies.set(k, v, domain=".substack.com")
        self.timeout = timeout

    @staticmethod
    def _parse_cookie(sid: str) -> dict:
        sid = sid.strip()
        if "=" not in sid:
            return {"substack.sid": sid}
        out = {}
        for part in sid.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                out[k.strip()] = v.strip()
        if "substack.sid" not in out:
            raise SubstackError("SUBSTACK_SID must contain the substack.sid cookie")
        return out

    def _check(self, r: requests.Response, what: str) -> dict:
        if r.status_code in (401, 403):
            raise SubstackError(f"{what}: Substack rejected the session cookie ({r.status_code}). Refresh SUBSTACK_SID.")
        if r.status_code >= 400:
            raise SubstackError(f"{what}: HTTP {r.status_code} {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise SubstackError(f"{what}: non-JSON response") from e

    def user_id(self) -> int:
        r = self.s.get("https://substack.com/api/v1/user/profile/self", timeout=self.timeout)
        prof = self._check(r, "profile")
        if not prof.get("id"):
            raise SubstackError("profile: no user id (cookie expired?)")
        return int(prof["id"])

    def upload_image(self, path_or_url: str | Path) -> str:
        """Returns a substackcdn URL. Accepts a local file or a remote URL."""
        p = Path(str(path_or_url))
        if p.exists():
            mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            payload = f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
        else:
            payload = str(path_or_url)
        r = self.s.post(f"{self.pub}/api/v1/image", json={"image": payload}, timeout=90)
        data = self._check(r, "image upload")
        url = data.get("url")
        if not url:
            raise SubstackError(f"image upload: no url in response {str(data)[:200]}")
        return url

    def create_draft(self, title: str, subtitle: str, doc: dict, user_id: int,
                     audience: str = "everyone") -> dict:
        body = {
            "draft_title": title,
            "draft_subtitle": subtitle,
            "draft_body": json.dumps(doc),
            "draft_bylines": [{"id": user_id, "is_guest": False}],
            "audience": audience,
            "type": "newsletter",
            "section_chosen": True,
            "draft_section_id": None,
            "write_comment_permissions": "everyone",
            "should_send_email": True,
        }
        r = self.s.post(f"{self.pub}/api/v1/drafts", json=body, timeout=self.timeout)
        return self._check(r, "create draft")


def publish_draft(cfg: Settings, d: date, content: dict, card_png: Path, card_url: str | None) -> tuple[str | None, str | None]:
    """Create the Substack draft. Returns (editor_url, warning). Never raises."""
    sid = env("SUBSTACK_SID")
    if not sid:
        return None, "SUBSTACK_SID not set; draft not created in Substack (paste workflow only)."
    pub = cfg.settings["newsletter"]["substack_url"]
    try:
        api = Substack(pub, sid)
        uid = api.user_id()
        hosted_card = api.upload_image(card_png) if card_png.exists() else card_url
        hero = content.get("hero_image")
        if hero and hero.get("url"):
            try:
                hero = {**hero, "url": api.upload_image(hero["url"])}
            except SubstackError as e:
                log.warning("hero image upload failed, using original URL: %s", e)
        content = {**content, "hero_image": hero}
        doc = build_doc(cfg, d, content, hosted_card)
        draft = api.create_draft(content["title"], content["subtitle"], doc, uid)
        draft_id = draft.get("id")
        if not draft_id:
            raise SubstackError(f"create draft: no id in response {str(draft)[:200]}")
        url = f"{pub}/publish/post/{draft_id}"
        log.info("substack draft created: %s", url)
        return url, None
    except (SubstackError, requests.RequestException) as e:
        log.warning("substack draft failed: %s", e)
        return None, f"Substack draft not created: {e}. Use the paste workflow for this edition."


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]

"""Send the review email over SMTP (Gmail app password) with attachments."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from .util import Settings, env, log


def send_review(cfg: Settings, subject: str, html_body: str, attachments: list[Path]) -> bool:
    user, pw = env("SMTP_USER"), env("SMTP_PASS")
    mail_from, mail_to = env("MAIL_FROM", user), env("MAIL_TO")
    if not all([user, pw, mail_from, mail_to]):
        log.warning("SMTP_USER/SMTP_PASS/MAIL_TO not set; skipping email")
        return False
    e = cfg.settings["email"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = mail_to
    msg.set_content("Your mail client does not render HTML. Open the attached paste.html.")
    msg.add_alternative(html_body, subtype="html")
    for p in attachments:
        if not p.exists():
            continue
        data = p.read_bytes()
        if p.suffix == ".png":
            msg.add_attachment(data, maintype="image", subtype="png", filename=p.name)
        elif p.suffix == ".html":
            msg.add_attachment(data, maintype="text", subtype="html", filename=p.name)
        else:
            msg.add_attachment(data, maintype="text", subtype="plain", filename=p.name)
    with smtplib.SMTP(e["smtp_host"], int(e["smtp_port"]), timeout=30) as s:
        s.ehlo()
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    log.info("review email sent to %s", mail_to)
    return True

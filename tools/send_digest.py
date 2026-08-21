#!/usr/bin/env python3
"""Daily email digest for dirtydogtown.news.

Builds a digest of the last 24 hours of wire items (grouped into the same
sections as the site), reads subscriber emails from Firestore, drops any
address that has filed an unsubscribe, and sends one email per subscriber
through Brevo's free transactional API (300 emails/day).

Environment:
  FIREBASE_PROJECT_ID              Firebase/GCP project id (required to read
                                   subscribers)
  GOOGLE_APPLICATION_CREDENTIALS   path to a service-account JSON with the
                                   "Cloud Datastore Viewer" role
  BREVO_API_KEY                    Brevo API key; when absent the script
                                   dry-runs (prints the digest, sends nothing)
  DIGEST_FROM_EMAIL                verified Brevo sender
                                   (default tips@dirtydogtown.news)

Run by .github/workflows/daily-digest.yml every morning; run locally with
no credentials for a harmless dry-run preview written to digest-preview.html.
"""
from __future__ import annotations

import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    CENTRAL = ZoneInfo("America/Chicago")
except Exception:
    CENTRAL = timezone.utc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIRE = os.path.join(ROOT, "public", "wire.json")
SITE = "https://dirtydogtown.news"
MAX_SENDS = 290  # stay under Brevo's 300/day free ceiling

SECTION_ORDER = ["major", "crime", "sports", "obits"]
SECTION_NAMES = {"major": "Major News", "crime": "Crime & Safety",
                 "sports": "Sports", "obits": "Obituaries"}


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def fresh_items(now: datetime) -> list[dict]:
    try:
        wire = json.load(open(WIRE, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    cutoff = (now - timedelta(hours=24)).timestamp()
    out = []
    for it in wire.get("items", []):
        stamp = max(float(it.get("published") or 0), float(it.get("first_seen") or 0))
        if stamp >= cutoff:
            out.append(it)
    return out


def build_digest(items: list[dict], now: datetime) -> str:
    """Plain, email-client-safe HTML in the site's voice."""
    date_line = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    rows = [
        '<div style="max-width:600px;margin:0 auto;padding:24px 16px;'
        "font-family:Georgia,'Times New Roman',serif;color:#201e1d;background:#f3f2f2\">",
        '<div style="border-top:3px solid #201e1d;border-bottom:1px solid #201e1d;height:5px"></div>',
        f'<h1 style="font-size:34px;letter-spacing:-0.02em;margin:18px 0 4px">Dirty Dogtown</h1>',
        f'<p style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#5f5c5b;margin:0 0 18px">'
        f'North Little Rock, Arkansas · Daily digest · {esc(date_line)}</p>',
        '<div style="border-top:1px solid #201e1d"></div>',
    ]
    for key in SECTION_ORDER:
        sec = [i for i in items if i.get("section", "major") == key]
        if not sec:
            continue
        rows.append(f'<h2 style="font-size:13px;letter-spacing:0.08em;text-transform:uppercase;'
                    f'color:#5f5c5b;margin:24px 0 4px">{esc(SECTION_NAMES[key])}</h2>')
        for it in sec:
            hot = ('<span style="background:#ffdee6;color:#790e3d;font-size:11px;'
                   'padding:2px 8px;border-radius:2px;margin-right:6px">Hot story</span>'
                   if it.get("hot") else "")
            rows.append(
                f'<p style="margin:12px 0 2px;font-size:17px;line-height:1.35">{hot}'
                f'<a href="{esc(it["url"])}" style="color:#201e1d">{esc(it["title"])}</a></p>')
            meta = esc(it.get("source", ""))
            if it.get("discussion_url") and it["discussion_url"] != it["url"]:
                n = it.get("num_comments")
                meta += (f' · <a href="{esc(it["discussion_url"])}" style="color:#006786">'
                         f'Discussion{f" ({n})" if n else ""}</a>')
            rows.append(f'<p style="margin:0;font-size:12px;color:#5f5c5b">{meta}</p>')
    rows.append('<div style="border-top:1px solid #201e1d;margin-top:26px"></div>')
    rows.append(
        f'<p style="font-size:12px;color:#5f5c5b;line-height:1.6;margin:14px 0 0">'
        f'Gathered hourly from public sources; every item links to its source. '
        f'<a href="{SITE}/" style="color:#006786">Read the full wire</a> · '
        f'<a href="{SITE}/#submit" style="color:#006786">Send a tip</a> · '
        f'<a href="{SITE}/unsubscribe" style="color:#006786">Unsubscribe</a></p>')
    rows.append("</div>")
    return "\n".join(rows)


def firestore_emails(project: str, collection: str) -> set[str]:
    """List email fields via the Firestore REST API with SA credentials."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/datastore"])
    session = AuthorizedSession(creds)
    emails: set[str] = set()
    url = (f"https://firestore.googleapis.com/v1/projects/{project}"
           f"/databases/(default)/documents/{collection}?pageSize=300")
    page_token = ""
    while True:
        r = session.get(url + (f"&pageToken={page_token}" if page_token else ""), timeout=30)
        r.raise_for_status()
        data = r.json()
        for doc in data.get("documents", []):
            v = doc.get("fields", {}).get("email", {}).get("stringValue", "")
            if v:
                emails.add(v.strip().lower())
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break
    return emails


def send_brevo(api_key: str, sender: str, to_email: str, subject: str, body: str) -> None:
    payload = json.dumps({
        "sender": {"name": "Dirty Dogtown", "email": sender},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": body,
    }).encode()
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email", data=payload,
        headers={"api-key": api_key, "Content-Type": "application/json",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def main() -> int:
    now = datetime.now(CENTRAL)
    items = fresh_items(now)
    if not items:
        print("[digest] nothing newer than 24h — no digest today")
        return 0
    digest = build_digest(items, now)
    subject = f"Dogtown daily — {len(items)} North Little Rock items, {now.strftime('%b')} {now.day}"

    api_key = os.environ.get("BREVO_API_KEY", "")
    project = os.environ.get("FIREBASE_PROJECT_ID", "")
    sender = os.environ.get("DIGEST_FROM_EMAIL") or "tips@dirtydogtown.news"

    if not api_key or not project:
        preview = os.path.join(ROOT, "digest-preview.html")
        open(preview, "w", encoding="utf-8").write(digest)
        print(f"[digest] DRY RUN ({len(items)} items) — no BREVO_API_KEY/"
              f"FIREBASE_PROJECT_ID set; preview written to {preview}")
        return 0

    try:
        subscribers = firestore_emails(project, "subscribers")
        gone = firestore_emails(project, "unsubscribes")
    except Exception as e:
        print(f"[digest] cannot read subscribers: {e}", file=sys.stderr)
        print("[digest] the service account needs the 'Cloud Datastore Viewer' role",
              file=sys.stderr)
        return 1

    recipients = sorted(subscribers - gone)[:MAX_SENDS]
    if not recipients:
        print("[digest] no subscribers yet — nothing to send")
        return 0

    sent = failed = 0
    for email in recipients:
        try:
            send_brevo(api_key, sender, email, subject, digest)
            sent += 1
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            failed += 1
            print(f"[digest] send failed for one recipient: {e}", file=sys.stderr)
        time.sleep(0.25)
    print(f"[digest] sent {sent}, failed {failed}, items {len(items)}")
    return 0 if sent or not failed else 1


if __name__ == "__main__":
    sys.exit(main())

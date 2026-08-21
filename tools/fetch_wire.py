#!/usr/bin/env python3
"""Hourly North Little Rock news sweep for dirtydogtown.news.

Pulls headlines and public discussion from free, keyless sources:
  - Google News RSS (several North Little Rock queries)
  - Reddit search + r/LittleRock (posts, plus top public comments)

Writes:
  - public/wire.json                  (structured data, newest first)
  - public/index.html                 (renders items between WIRE markers,
                                       refreshes the JSON-LD dateModified)
  - public/sitemap.xml                (bumps <lastmod>)

Stdlib only — runs the same under GitHub Actions and locally:
    python3 tools/fetch_wire.py
Every item keeps its link; quoted comments keep their permalink. Sources
that fail (network hiccup, rate limit) are skipped, never fatal.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

try:
    from zoneinfo import ZoneInfo
    CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # zoneinfo data missing — fall back to UTC labels
    CENTRAL = timezone.utc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "public")
UA = "dirtydogtown-wire/1.0 (+https://dirtydogtown.news)"

MAX_NEWS = 20
MAX_REDDIT_POSTS = 8
COMMENTS_PER_POST = 2
POSTS_WITH_COMMENTS = 5

GOOGLE_NEWS_QUERIES = [
    '"North Little Rock" Arkansas',
    '"North Little Rock" city council OR police OR schools OR parks',
]

REDDIT_ENDPOINTS = [
    "https://www.reddit.com/r/LittleRock/search.json?q=%22North%20Little%20Rock%22&restrict_sr=1&sort=new&t=week&limit=15&raw_json=1",
    "https://www.reddit.com/search.json?q=%22North%20Little%20Rock%22%20Arkansas&sort=new&t=week&limit=15&raw_json=1",
]


def fetch(url: str, timeout: int = 20) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[wire] skip {url.split('?')[0]}: {e}", file=sys.stderr)
        return None


def clean(text: str, limit: int = 240) -> str:
    # strip only tag-shaped runs (must start with a letter or /) so prose
    # like "3 < 5 but > 2" survives untouched
    text = re.sub(r"</?[A-Za-z][^>]*>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


def google_news() -> list[dict]:
    items = []
    for q in GOOGLE_NEWS_QUERIES:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q)
               + "&hl=en-US&gl=US&ceid=US:en")
        raw = fetch(url)
        if not raw:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f"[wire] bad RSS for {q!r}: {e}", file=sys.stderr)
            continue
        for it in root.iter("item"):
            title = clean(it.findtext("title") or "", 200)
            link = (it.findtext("link") or "").strip()
            if not title or not link:
                continue
            src = it.find("source")
            source = clean(src.text if src is not None else "", 60) or "Google News"
            pub = it.findtext("pubDate") or ""
            try:
                ts = parsedate_to_datetime(pub).timestamp()
            except (TypeError, ValueError):
                ts = 0.0
            items.append({
                "type": "article",
                "title": title,
                "url": link,
                "source": source,
                "published": ts,
                "snippet": "",
                "discussion_url": "",
                "comments": [],
            })
    return items


def reddit() -> list[dict]:
    posts: list[dict] = []
    seen: set[str] = set()
    for url in REDDIT_ENDPOINTS:
        raw = fetch(url)
        time.sleep(1)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            pid = d.get("id")
            if not pid or pid in seen or d.get("over_18"):
                continue
            seen.add(pid)
            permalink = "https://www.reddit.com" + d.get("permalink", "")
            is_self = d.get("is_self", True)
            outbound = d.get("url", "") if not is_self else permalink
            if outbound.startswith("/"):  # crossposts return a relative path
                outbound = "https://www.reddit.com" + outbound
            posts.append({
                "type": "post",
                "title": clean(d.get("title", ""), 200),
                "url": outbound or permalink,
                "source": "r/" + d.get("subreddit", "reddit"),
                "published": float(d.get("created_utc") or 0),
                "snippet": clean(d.get("selftext", ""), 240),
                "discussion_url": permalink,
                "num_comments": int(d.get("num_comments") or 0),
                "comments": [],
                "_permalink_api": "https://www.reddit.com" + d.get("permalink", "") + ".json?limit=10&raw_json=1",
            })
    posts.sort(key=lambda p: p["published"], reverse=True)
    posts = posts[:MAX_REDDIT_POSTS]

    # Public opinion: quote the top comments on the freshest discussed posts.
    for p in posts[:POSTS_WITH_COMMENTS]:
        if not p.get("num_comments"):
            continue
        raw = fetch(p["_permalink_api"])
        time.sleep(1)
        if not raw:
            continue
        try:
            listing = json.loads(raw)
            children = listing[1]["data"]["children"]
        except (json.JSONDecodeError, LookupError, TypeError):
            continue
        for c in children:
            if c.get("kind") != "t1":
                continue
            cd = c.get("data", {})
            body = clean(cd.get("body", ""), 220)
            author = cd.get("author", "")
            if not body or author in ("[deleted]", "AutoModerator", ""):
                continue
            p["comments"].append({
                "author": "u/" + author,
                "text": body,
                "url": "https://www.reddit.com" + (cd.get("permalink") or p["discussion_url"].replace("https://www.reddit.com", "")),
            })
            if len(p["comments"]) >= COMMENTS_PER_POST:
                break
    for p in posts:
        p.pop("_permalink_api", None)
    return posts


def dedupe(items: list[dict]) -> list[dict]:
    out, seen = [], set()
    for it in items:
        key = re.sub(r"\W+", "", it["title"].lower())[:80]
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def when_label(ts: float, now: datetime) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=CENTRAL)
    day = f"{dt.strftime('%b')} {dt.day}"
    if (now - dt).days >= 1:
        return day
    hour = dt.hour % 12 or 12
    return f"{day}, {hour}:{dt.strftime('%M')} {dt.strftime('%p')}"


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def render(items: list[dict], now: datetime) -> str:
    if not items:
        return ('<p style="font-size:15.5px;line-height:1.65;color:color-mix(in srgb, '
                'var(--color-text) 78%, transparent);margin:18px 0 0">Quiet hour on the '
                'wire — nothing new found. The next sweep runs within the hour.</p>')
    rows = []
    for it in items:
        meta = esc(it["source"])
        label = when_label(it["published"], now)
        if label:
            meta += " · " + esc(label)
        parts = [f'<p class="wire-meta">{meta}</p>']
        parts.append(
            f'<h3><a class="story-link" href="{esc(it["url"])}" rel="noopener">{esc(it["title"])}</a></h3>')
        if it.get("snippet"):
            parts.append(
                f'<p style="font-size:14.5px;line-height:1.6;color:color-mix(in srgb, '
                f'var(--color-text) 78%, transparent);margin:8px 0 0">{esc(it["snippet"])}</p>')
        links = [f'<a href="{esc(it["url"])}" rel="noopener">Read at the source</a>']
        if it.get("discussion_url") and it["discussion_url"] != it["url"]:
            n = it.get("num_comments")
            label_d = f"Discussion ({n})" if n else "Discussion"
            links.append(f'<a href="{esc(it["discussion_url"])}" rel="noopener ugc">{label_d}</a>')
        parts.append('<p class="wire-links">' + "".join(links) + "</p>")
        for c in it.get("comments", []):
            parts.append(
                f'<blockquote>“{esc(c["text"])}” — <a href="{esc(c["url"])}" '
                f'rel="noopener ugc">{esc(c["author"])}</a></blockquote>')
        rows.append('<div class="wire-item">' + "\n          ".join(parts) + "</div>")
    grid = ('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));'
            'gap:34px clamp(32px,4.5vw,64px);margin-top:22px">' + "\n        ".join(rows) + "</div>")
    return grid


def main() -> int:
    now = datetime.now(CENTRAL)
    news = dedupe(google_news())
    news.sort(key=lambda n: n["published"], reverse=True)
    items = sorted(news[:MAX_NEWS] + reddit(),
                   key=lambda i: i["published"], reverse=True)

    wire_path = os.path.join(PUB, "wire.json")
    payload = {
        "updated": now.isoformat(),
        "place": "North Little Rock, Arkansas",
        "items": items,
    }

    # Don't wipe a good wire with an empty one when every source failed.
    if not items and os.path.exists(wire_path):
        print("[wire] all sources empty — keeping the previous wire")
        return 0

    with open(wire_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    index_path = os.path.join(PUB, "index.html")
    page = open(index_path, encoding="utf-8").read()
    block = "<!-- WIRE:START -->\n        " + render(items, now) + "\n        <!-- WIRE:END -->"
    page, n = re.subn(r"<!-- WIRE:START -->.*?<!-- WIRE:END -->", lambda _: block, page, flags=re.S)
    if n != 1:
        print("[wire] WIRE markers missing from index.html", file=sys.stderr)
        return 1
    stamp = when_label(now.timestamp(), now) + " CT"
    page = re.sub(r'(<span id="wire-updated">)[^<]*(</span>)',
                  lambda m: m.group(1) + "Checked hourly · " + stamp + m.group(2), page)
    # keep the structured data honest: the page really did change
    page = re.sub(r'("dateModified":\s*")\d{4}-\d{2}-\d{2}(")',
                  lambda m: m.group(1) + now.strftime("%Y-%m-%d") + m.group(2), page)
    open(index_path, "w", encoding="utf-8").write(page)

    sitemap_path = os.path.join(PUB, "sitemap.xml")
    if os.path.exists(sitemap_path):
        sm = open(sitemap_path, encoding="utf-8").read()
        sm = re.sub(r"<lastmod>[^<]*</lastmod>",
                    "<lastmod>" + now.strftime("%Y-%m-%d") + "</lastmod>", sm)
        open(sitemap_path, "w", encoding="utf-8").write(sm)

    print(f"[wire] {len(items)} items "
          f"({len(news[:MAX_NEWS])} articles, {len(items) - len(news[:MAX_NEWS])} posts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

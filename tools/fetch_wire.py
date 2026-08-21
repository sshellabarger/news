#!/usr/bin/env python3
"""Hourly North Little Rock news sweep for dirtydogtown.news.

Pulls headlines and public discussion from free, keyless sources:
  - Google News RSS (several North Little Rock queries)
  - Reddit search + r/LittleRock (posts, plus top public comments)

Each item is classified into a section (Major News / Crime & Safety /
Sports / Obituaries), stamped with when it was filed by the source and
when this wire first pulled it, and the most-discussed items are labeled
"Hot story".

Writes:
  - public/wire.json                  (structured data, newest first)
  - public/index.html                 (renders sections between WIRE markers,
                                       refreshes the JSON-LD dateModified)
  - public/feed.xml                   (RSS 2.0 feed of the wire)
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
from email.utils import format_datetime, parsedate_to_datetime

try:
    from zoneinfo import ZoneInfo
    CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # zoneinfo data missing — fall back to UTC labels
    CENTRAL = timezone.utc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "public")
UA = "dirtydogtown-wire/1.0 (+https://dirtydogtown.news)"
SITE = "https://dirtydogtown.news"

MAX_NEWS = 28
MAX_REDDIT_POSTS = 8
COMMENTS_PER_POST = 2
POSTS_WITH_COMMENTS = 5
HOT_MIN_COMMENTS = 5   # a post needs at least this much discussion...
HOT_MAX_LABELS = 3     # ...and only the top few get the label

# Section caps — Major News keeps the majority of the page.
SECTION_CAPS = {"major": 16, "crime": 6, "sports": 6, "obits": 6}
SECTION_TITLES = {
    "major": "Major News",
    "crime": "Crime &amp; Safety",
    "sports": "Sports",
    "obits": "Obituaries",
}
SECTION_FEED_NAMES = {
    "major": "Major News", "crime": "Crime & Safety",
    "sports": "Sports", "obits": "Obituaries",
}

# Checked in order — first hit wins; anything unmatched is Major News.
SECTION_KEYWORDS = [
    ("obits", [
        "obituar", "dignity memorial", "funeral home", "funeral service",
        "memorial service", "celebration of life", "passed away", "legacy.com",
        "visitation will", "interment", "graveside",
    ]),
    ("crime", [
        "police", "arrest", "shooting", "shot ", "homicide", "murder",
        "stabb", "robbery", "burglar", "theft", "stolen", "assault",
        "suspect", "fatal", "crash", "wreck", "kidnap", "fraud", "sentenced",
        "convicted", "charged", "jail", "prison", "manhunt", "gunfire",
        "carjack", "sheriff", "state trooper", "crime", "drug bust",
        "pursuit", "missing person",
    ]),
    ("sports", [
        "travelers", "dickey-stephens", "baseball", "basketball", "football",
        "softball", "volleyball", "soccer", "golf ", "tennis", "track and field",
        "wrestling", "playoff", "tournament", "coach", "athletic", "razorback",
        "mariners", "charging wildcats", "high school hoops", "quarterback",
        "mvp", "all-star",
    ]),
]

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


def item_key(it: dict) -> str:
    return re.sub(r"\W+", "", it["title"].lower())[:80]


def categorize(it: dict) -> str:
    text = " ".join([it.get("title", ""), it.get("snippet", ""), it.get("source", "")]).lower()
    for section, words in SECTION_KEYWORDS:
        if any(w in text for w in words):
            return section
    return "major"


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
        key = item_key(it)
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


def carry_first_seen(items: list[dict], wire_path: str, now: datetime) -> None:
    """Items keep the pull stamp from the run that first found them."""
    prev: dict[str, dict] = {}
    if os.path.exists(wire_path):
        try:
            for it in json.load(open(wire_path, encoding="utf-8")).get("items", []):
                prev[item_key(it)] = it
        except (json.JSONDecodeError, OSError):
            pass
    for it in items:
        old = prev.get(item_key(it))
        it["first_seen"] = (old or {}).get("first_seen") or now.timestamp()


def mark_hot(items: list[dict]) -> None:
    ranked = sorted((i for i in items if i.get("num_comments")),
                    key=lambda i: -i["num_comments"])
    for i in ranked[:HOT_MAX_LABELS]:
        if i["num_comments"] >= HOT_MIN_COMMENTS:
            i["hot"] = True


def render_item(it: dict, now: datetime) -> str:
    meta = esc(it["source"])
    filed = when_label(it.get("published") or 0, now)
    if filed:
        meta += " · Filed " + esc(filed)
    pulled = when_label(it.get("first_seen") or 0, now)
    if pulled:
        meta += " · Pulled " + esc(pulled)
    parts = []
    if it.get("hot"):
        parts.append('<p style="margin:0 0 6px"><span class="tag tag-accent-2">Hot story</span></p>')
    parts.append(f'<p class="wire-meta">{meta}</p>')
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
    return '<div class="wire-item">' + "\n          ".join(parts) + "</div>"


def split_sections(items: list[dict]) -> dict[str, list[dict]]:
    sections: dict[str, list[dict]] = {"major": [], "crime": [], "sports": [], "obits": []}
    for it in items:
        sections[it.get("section", "major")].append(it)
    return {k: v[:SECTION_CAPS[k]] for k, v in sections.items()}


def render(items: list[dict], now: datetime) -> str:
    if not items:
        return ('<p style="font-size:15.5px;line-height:1.65;color:color-mix(in srgb, '
                'var(--color-text) 78%, transparent);margin:18px 0 0">Quiet hour on the '
                'wire — nothing new found. The next sweep runs within the hour.</p>')
    sections = split_sections(items)
    out = []

    head_style = ('font-size:13px;letter-spacing:0.08em;text-transform:uppercase;'
                  'color:color-mix(in srgb, var(--color-text) 70%, transparent);'
                  'border-bottom:1px solid var(--color-divider);padding-bottom:8px')

    # Major News — the majority of the page, full-width grid.
    if sections["major"]:
        out.append(f'<h3 style="{head_style};margin:26px 0 0;font-family:var(--font-body);font-weight:400">'
                   f'{SECTION_TITLES["major"]} · {len(sections["major"])}</h3>')
        out.append('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));'
                   'gap:34px clamp(32px,4.5vw,64px);margin-top:22px">'
                   + "\n        ".join(render_item(i, now) for i in sections["major"]) + "</div>")

    # The compact band: Crime & Safety / Sports / Obituaries.
    cols = []
    for key in ("crime", "sports", "obits"):
        if not sections[key]:
            continue
        col = [f'<h3 style="{head_style};margin:0;font-family:var(--font-body);font-weight:400">'
               f'{SECTION_TITLES[key]} · {len(sections[key])}</h3>']
        col.append('<div style="display:grid;gap:24px;margin-top:18px">'
                   + "\n          ".join(render_item(i, now) for i in sections[key]) + "</div>")
        cols.append('<div>' + "\n        ".join(col) + "</div>")
    if cols:
        out.append('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));'
                   'gap:40px clamp(28px,4vw,56px);margin-top:clamp(40px,6vw,56px)">'
                   + "\n        ".join(cols) + "</div>")
    return "\n        ".join(out)


def write_feed(items: list[dict], now: datetime, path: str) -> None:
    """RSS 2.0 feed of the wire — the site's subscribable news feed."""
    rows = []
    for it in items:
        ts = it.get("published") or it.get("first_seen") or now.timestamp()
        pub = format_datetime(datetime.fromtimestamp(ts, tz=timezone.utc))
        desc_bits = [it.get("snippet") or "", "Source: " + it["source"]]
        if it.get("discussion_url") and it["discussion_url"] != it["url"]:
            desc_bits.append("Discussion: " + it["discussion_url"])
        rows.append(
            "    <item>\n"
            f"      <title>{esc(it['title'])}</title>\n"
            f"      <link>{esc(it['url'])}</link>\n"
            f"      <guid isPermaLink=\"false\">dogtown-{esc(item_key(it))}</guid>\n"
            f"      <pubDate>{pub}</pubDate>\n"
            f"      <category>{esc(SECTION_FEED_NAMES.get(it.get('section', 'major'), 'Major News'))}</category>\n"
            f"      <description>{esc(' — '.join(b for b in desc_bits if b))}</description>\n"
            "    </item>")
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        "    <title>Dirty Dogtown — North Little Rock, AR News</title>\n"
        f"    <link>{SITE}/</link>\n"
        f'    <atom:link href="{SITE}/feed.xml" rel="self" type="application/rss+xml"/>\n'
        "    <description>The Wire: North Little Rock, Arkansas news and public discussion, "
        "gathered hourly by dirtydogtown.news. Every item links to its source.</description>\n"
        "    <language>en-us</language>\n"
        f"    <lastBuildDate>{format_datetime(now)}</lastBuildDate>\n"
        + "\n".join(rows) + "\n"
        "  </channel>\n"
        "</rss>\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(feed)


def main() -> int:
    now = datetime.now(CENTRAL)
    news = dedupe(google_news())
    news.sort(key=lambda n: n["published"], reverse=True)
    items = sorted(news[:MAX_NEWS] + reddit(),
                   key=lambda i: i["published"], reverse=True)

    wire_path = os.path.join(PUB, "wire.json")

    # Don't wipe a good wire with an empty one when every source failed.
    if not items and os.path.exists(wire_path):
        print("[wire] all sources empty — keeping the previous wire")
        return 0

    carry_first_seen(items, wire_path, now)
    for it in items:
        it["section"] = categorize(it)
    mark_hot(items)

    payload = {
        "updated": now.isoformat(),
        "place": "North Little Rock, Arkansas",
        "items": items,
    }
    with open(wire_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    if items:
        write_feed(items, now, os.path.join(PUB, "feed.xml"))

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

    counts = {k: len(v) for k, v in split_sections(items).items()}
    print(f"[wire] {len(items)} items | sections {counts} | "
          f"hot {sum(1 for i in items if i.get('hot'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

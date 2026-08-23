#!/usr/bin/env python3
"""Render the shareable weekly front page: public/this-week.png (1080×1080).

Builds a square social card in the site's Broadsheet style — CMYK plate
masthead, the week's date range, and the top stories of the last 7 days
from archive.json (most-discussed first, then Major News, newest first) —
and screenshots it with headless Chrome. Post it to local Facebook groups,
Nextdoor, etc.; every headline drives readers to dirtydogtown.news.

Run by .github/workflows/weekly-front.yml every Monday morning, or locally:
    python3 tools/weekly_front.py
Set CHROME_BIN to a Chrome/Chromium binary if it isn't on PATH.
"""
from __future__ import annotations

import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    CENTRAL = ZoneInfo("America/Chicago")
except Exception:
    CENTRAL = timezone.utc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "public")
OUT = os.path.join(PUB, "this-week.png")
STORY_COUNT = 5

SECTION_NAMES = {"major": "Major News", "crime": "Crime & Safety",
                 "sports": "Sports", "obits": "Obituaries"}


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def chrome_bin() -> str:
    for cand in (os.environ.get("CHROME_BIN"), "google-chrome", "chromium",
                 "chromium-browser", "/opt/pw-browsers/chromium"):
        if cand and (shutil.which(cand) or os.path.exists(cand)):
            return shutil.which(cand) or cand
    sys.exit("no Chrome/Chromium found — set CHROME_BIN")


def pick_stories(now: datetime) -> list[dict]:
    try:
        items = json.load(open(os.path.join(PUB, "archive.json"),
                               encoding="utf-8")).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []
    cutoff = (now - timedelta(days=7)).timestamp()
    week = [i for i in items
            if float(i.get("published") or i.get("first_seen") or 0) >= cutoff]
    week.sort(key=lambda i: (-(int(i.get("num_comments") or 0)),
                             0 if i.get("section", "major") == "major" else 1,
                             -float(i.get("published") or i.get("first_seen") or 0)))
    picked, seen_sections = [], set()
    # lead with discussion + major, but let each section get a look-in
    for it in week:
        if len(picked) >= STORY_COUNT:
            break
        picked.append(it)
        seen_sections.add(it.get("section", "major"))
    for it in week:  # swap in one story from any unseen section
        if len(picked) < STORY_COUNT:
            break
        sec = it.get("section", "major")
        if sec not in seen_sections:
            picked[-1] = it
            seen_sections.add(sec)
            break
    return picked


def build_html(stories: list[dict], now: datetime) -> str:
    start = now - timedelta(days=6)
    if start.month == now.month:
        span = f"{start.strftime('%B')} {start.day}–{now.day}, {now.year}"
    else:
        span = f"{start.strftime('%b')} {start.day} – {now.strftime('%b')} {now.day}, {now.year}"
    fonts = os.path.join(PUB, "fonts")
    rows = []
    for it in stories:
        kicker = SECTION_NAMES.get(it.get("section", "major"), "Major News")
        if it.get("source"):
            kicker += " · " + it["source"]
        hot = ('<span class="hot">Hot story</span>' if int(it.get("num_comments") or 0) >= 5 else "")
        title = it.get("title", "")
        src = (it.get("source") or "").lower()
        if " - " in title:  # Google News appends " - Outlet"; the kicker has it
            head, tail = title.rsplit(" - ", 1)
            if tail.lower() in src or src in tail.lower():
                title = head
        if len(title) > 88:
            title = title[:87].rsplit(" ", 1)[0] + "…"
        rows.append(f'''<div class="story">
      <p class="kicker">{hot}{esc(kicker)}</p>
      <p class="head">{esc(title)}</p>
    </div>''')
    stories_html = "\n    ".join(rows) or '<p class="head">A quiet week in Dogtown.</p>'
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
@font-face {{ font-family: 'Source Serif 4'; font-style: normal; font-weight: 400;
  src: url("file://{fonts}/source-serif-4-normal-latin.woff2") format('woff2'); }}
@font-face {{ font-family: 'Source Serif 4'; font-style: normal; font-weight: 600;
  src: url("file://{fonts}/source-serif-4-normal-latin.woff2") format('woff2'); }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ width: 1080px; height: 1080px; overflow: hidden; background: #f3f2f2; color: #201e1d;
  font-family: 'Source Serif 4', Georgia, serif; padding: 44px 64px;
  display: flex; flex-direction: column; }}
.rule-heavy {{ border-top: 3px solid #201e1d; border-bottom: 1px solid #201e1d; height: 7px; }}
.rule {{ border-top: 1px solid #201e1d; }}
.folio {{ display: flex; justify-content: space-between; padding: 11px 2px;
  font-size: 16px; letter-spacing: 0.09em; text-transform: uppercase; color: rgba(32,30,29,0.7); }}
h1 {{ font-weight: 600; font-size: 84px; line-height: 1; letter-spacing: -0.02em; margin: 12px 0 10px -4px; }}
.cmyk {{ position: relative; display: inline-block; }}
.cmyk .paper {{ color: #f3f2f2; text-shadow: 0.027em 0.0185em 0 #f3f2f2, -0.0245em -0.0175em 0 #f3f2f2; }}
.cmyk .plate {{ position: absolute; inset: 0; mix-blend-mode: multiply; }}
.cmyk .c {{ color: #0088b0; }}
.cmyk .m {{ color: #d6006c; translate: 0.018em 0.0125em; }}
.cmyk .y {{ color: #edbb00; translate: -0.0155em -0.0115em; }}
.tag {{ font-size: 18px; letter-spacing: 0.1em; text-transform: uppercase;
  color: rgba(32,30,29,0.7); padding: 0 2px 14px; }}
.stories {{ flex: 1 1 0; min-height: 0; overflow: hidden;
  display: flex; flex-direction: column; justify-content: space-evenly; }}
.story {{ padding: 6px 0; border-bottom: 1px solid rgba(32,30,29,0.14); }}
.story:last-child {{ border-bottom: none; }}
.kicker {{ font-size: 14px; letter-spacing: 0.08em; text-transform: uppercase;
  color: rgba(32,30,29,0.62); margin-bottom: 7px; }}
.hot {{ background: #ffdee6; color: #790e3d; font-size: 13px; letter-spacing: 0.05em;
  padding: 3px 10px; border-radius: 2px; margin-right: 10px; text-transform: uppercase; }}
.head {{ font-weight: 600; font-size: 27px; line-height: 1.18; letter-spacing: -0.01em; }}
.foot {{ display: flex; justify-content: space-between; padding: 12px 2px 0;
  font-size: 16px; letter-spacing: 0.08em; text-transform: uppercase; color: rgba(32,30,29,0.7); }}
.foot b {{ color: #006786; font-weight: 600; }}
</style></head>
<body>
  <div class="rule-heavy"></div>
  <div class="folio"><span>The week in Dogtown</span><span>{esc(span)}</span></div>
  <div class="rule"></div>
  <h1><span class="cmyk"><span class="paper">Dirty Dogtown</span><span class="plate c" aria-hidden="true">Dirty Dogtown</span><span class="plate m" aria-hidden="true">Dirty Dogtown</span><span class="plate y" aria-hidden="true">Dirty Dogtown</span></span></h1>
  <div class="tag">North Little Rock, Arkansas · Neighborhood News</div>
  <div class="rule"></div>
  <div class="stories">
    {stories_html}
  </div>
  <div class="rule"></div>
  <div class="foot"><span>Read it all · <b>dirtydogtown.news</b></span><span>Tips welcome · no name needed</span></div>
  <div class="rule-heavy" style="margin-top:12px"></div>
</body></html>"""


def main() -> int:
    now = datetime.now(CENTRAL)
    stories = pick_stories(now)
    html_doc = build_html(stories, now)
    with tempfile.TemporaryDirectory() as td:
        page = os.path.join(td, "front.html")
        open(page, "w", encoding="utf-8").write(html_doc)
        # headless --window-size can shave the bottom of the viewport, so
        # render tall and crop to the exact square
        shot = os.path.join(td, "shot.png")
        subprocess.run(
            [chrome_bin(), "--headless", "--no-sandbox", "--disable-gpu",
             "--hide-scrollbars", "--force-device-scale-factor=1",
             "--window-size=1080,1240", f"--screenshot={shot}", "file://" + page],
            check=True, capture_output=True)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from crop_png import crop
        crop(shot, OUT, 1080, 1080)
    print(f"[weekly] {len(stories)} stories -> {OUT} "
          f"({os.path.getsize(OUT)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

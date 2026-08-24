#!/usr/bin/env python3
"""Civic Calendar sweep for dirtydogtown.news.

Pulls upcoming public-meeting data and posted agendas for North Little
Rock's four covered bodies:

  - City Council            (city site / CivicLive agenda PDFs)
  - Parks & Rec Commission  (city events calendar)
  - School Board (NLRSD)    (BoardDocs public listing — best-effort)
  - Library Board (NLRPLS)  (library events calendar — best-effort)

Writes:
  - public/civic.json                        (machine-readable meeting list)
  - public/civic.html                        (rows between CIVIC markers)
  - public/civic/<body>-<YYYY-MM-DD>.html    (agenda between AGENDA markers,
                                              when a posted agenda is found
                                              and the meeting page exists)

Every source is best-effort: a failed fetch or parse logs to stderr and is
skipped, never fatal, and never wipes previously good data. Stdlib only;
PDF agenda extraction activates when `pypdf` is installed (the workflow
installs it) and degrades to a plain link otherwise.

NOTE: like tools/fetch_wire.py, this is meant to run where outbound
network is open — GitHub Actions (.github/workflows/civic.yml) or a
laptop. Run locally: python3 tools/fetch_civic.py
"""
from __future__ import annotations

import html
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    CENTRAL = ZoneInfo("America/Chicago")
except Exception:
    CENTRAL = timezone.utc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "public")
UA = "dirtydogtown-civic/1.0 (+https://dirtydogtown.news)"
# CivicLive fronts 403 plain-script UAs; a browser UA gets the public pages.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

LOOKAHEAD_DAYS = 60

BODY_PAGES = {
    "council": "/civic/council",
    "parks": "/civic/parks-commission",
    "school": "/civic/school-board",
    "library": "/civic/library-board",
}

# The Events Calendar (WordPress) REST endpoints the city has used.
TRIBE_ENDPOINTS = [
    "https://nlr.ar.gov/wp-json/tribe/events/v1/events",
    "https://development.nlr.ar.gov/wp-json/tribe/events/v1/events",
]

CIVICLIVE_COUNCIL = "https://northlittlerock.hosted.civiclive.com/government/city_council"

# Historical CivicLive file-store pattern for council agenda PDFs
# (e.g. .../Council%20Agendas/7-13-20/City%20Council%20Agenda%207-13-20.pdf).
CIVICLIVE_PDF_BASE = ("https://cdnsm5-hosted.civiclive.com/UserFiles/Servers/"
                      "Server_63092/File/City%20Clerk/Council%20Agendas/")

LIBRARY_EVENTS = "https://lamanlibrary.libnet.info/events?r=thismonth"
BOARDDOCS_PUBLIC = "https://go.boarddocs.com/ar/nlrsd/Board.nsf/public"


def fetch(url: str, timeout: int = 20, binary: bool = False, ua: str = UA):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return data if binary else data.decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"[civic] skip {url.split('?')[0]}: {e}", file=sys.stderr)
        return None


def classify(title: str) -> str | None:
    t = title.lower()
    if "city council" in t or re.search(r"\bcouncil meeting\b", t):
        return "council"
    if "parks" in t and ("commission" in t or "recreation" in t):
        return "parks"
    if "school board" in t or "board of education" in t:
        return "school"
    if "board" in t and ("library" in t or "trustee" in t):
        return "library"
    return None


def city_calendar() -> list[dict]:
    """City Council + Parks Commission from the city's WordPress events API."""
    out = []
    start = date.today().isoformat()
    for base in TRIBE_ENDPOINTS:
        url = f"{base}?per_page=50&start_date={start}"
        raw = fetch(url)
        if not raw:
            continue
        try:
            events = json.loads(raw).get("events", [])
        except (json.JSONDecodeError, AttributeError):
            print(f"[civic] bad events JSON from {base}", file=sys.stderr)
            continue
        for ev in events:
            title = html.unescape(ev.get("title") or "")
            body = classify(title)
            if not body:
                continue
            start_iso = (ev.get("start_date") or "").replace(" ", "T")
            venue = ev.get("venue") or {}
            if isinstance(venue, list):
                venue = venue[0] if venue else {}
            out.append({
                "body": body,
                "title": title,
                "start": start_iso,
                "location": html.unescape((venue.get("venue") or "") if isinstance(venue, dict) else ""),
                "url": ev.get("url") or "",
            })
        if out:
            break  # first endpoint that answers wins
    return out


def library_board() -> list[dict]:
    """Scan the library's Communico events page for board meetings."""
    raw = fetch(LIBRARY_EVENTS)
    if not raw:
        return []
    out = []
    for m in re.finditer(
            r'href="(?:https://lamanlibrary\.libnet\.info)?(/event/\d+)"[^>]*>([^<]{0,120})</a>',
            raw):
        text = html.unescape(m.group(2)).strip()
        if "board" in text.lower():
            out.append({
                "body": "library",
                "title": text or "Library Board of Trustees",
                "start": "",  # date lives on the event page; leave blank rather than guess
                "location": "William F. Laman Public Library",
                "url": "https://lamanlibrary.libnet.info" + m.group(1),
            })
    return out


def school_board() -> list[dict]:
    """BoardDocs is a JS app; a plain fetch rarely yields dates. Best-effort:
    keep the standing first/third-Thursday schedule and surface the portal."""
    out = []
    today = date.today()
    for delta in range(LOOKAHEAD_DAYS):
        d = today + timedelta(days=delta)
        if d.weekday() != 3:  # Thursday
            continue
        nth = (d.day - 1) // 7 + 1
        if nth == 1:
            kind = "Board workshop (first Thursday)"
        elif nth == 3:
            kind = "Regular board meeting (third Thursday)"
        else:
            continue
        out.append({
            "body": "school",
            "title": f"NLRSD Board of Education — {kind}",
            "start": f"{d.isoformat()}T17:30:00",
            "location": "NLRSD Administration Building, 2400 Willow St",
            "url": BOARDDOCS_PUBLIC,
            "computed": True,  # from the published regular schedule, not a live feed
        })
    return out


def council_schedule() -> list[dict]:
    """Standing second/fourth-Monday schedule as a floor under the live feed."""
    out = []
    today = date.today()
    for delta in range(LOOKAHEAD_DAYS):
        d = today + timedelta(days=delta)
        if d.weekday() != 0:
            continue
        nth = (d.day - 1) // 7 + 1
        if nth not in (2, 4):
            continue
        out.append({
            "body": "council",
            "title": "City Council — regular meeting",
            "start": f"{d.isoformat()}T18:00:00",
            "location": "City Hall Council Chambers, 300 Main St",
            "url": CIVICLIVE_COUNCIL,
            "computed": True,
        })
    return out


def parks_schedule() -> list[dict]:
    out = []
    today = date.today()
    for delta in range(LOOKAHEAD_DAYS):
        d = today + timedelta(days=delta)
        if d.weekday() == 0 and (d.day - 1) // 7 + 1 == 3:
            out.append({
                "body": "parks",
                "title": "Parks & Recreation Commission — regular meeting",
                "start": f"{d.isoformat()}T17:00:00",
                "location": "NLR Community Center, 2700 Willow St",
                "url": "https://nlr.ar.gov/departments/boards-and-commissions/parks-and-recreation-commission/",
                "computed": True,
            })
    return out


def merge_meetings(*lists: list[dict]) -> list[dict]:
    """Live-feed entries beat computed ones for the same body+date."""
    by_key: dict[str, dict] = {}
    for lst in lists:
        for m in lst:
            key = m["body"] + "|" + (m.get("start") or m["title"])[:10]
            cur = by_key.get(key)
            if cur is None or (cur.get("computed") and not m.get("computed")):
                by_key[key] = m
    return sorted(by_key.values(), key=lambda m: m.get("start") or "9999")


# ---------------------------------------------------------------- agendas ---

def agenda_links(src: str, base: str, date_tokens: set[str] | None = None) -> list[str]:
    """Hrefs whose URL or link text mentions an agenda, PDFs first.

    With date_tokens, the URL must also carry one of the tokens — used on
    listing pages that link many meetings' agendas at once.
    """
    found: list[str] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.{0,160}?)</a>',
                         src, re.S | re.I):
        href = html.unescape(m.group(1))
        text = re.sub(r"<[^>]+>", " ", m.group(2)).lower()
        h = urllib.parse.unquote(href).lower()
        if "agenda" not in h and "agenda" not in text:
            continue
        if date_tokens and not any(t in h for t in date_tokens):
            continue
        url = urllib.parse.urljoin(base, href)
        if url not in found:
            found.append(url)
    return sorted(found, key=lambda u: 0 if u.lower().endswith(".pdf") else 1)


def find_council_agenda(meet_date: date, event_url: str = "") -> tuple[str, list[str]]:
    """Return (agenda_url, extracted_items) for a council meeting date.

    Order: the meeting's own city event page (nlr.ar.gov answers plain
    fetches), then the CivicLive council page (browser UA — it 403s script
    UAs), then the historical CDN path pattern. A discovered agenda link
    that is itself a page gets one more scan for the PDF inside it; a PDF
    yields extracted items when pypdf is available, anything else is still
    returned as the link to show.
    """
    tokens = {
        f"{meet_date.month}-{meet_date.day}-{meet_date:%y}",
        f"{meet_date.month:02d}-{meet_date.day:02d}-{meet_date:%y}",
        meet_date.isoformat(),
    }
    candidates: list[str] = []

    if event_url:
        page = fetch(event_url)
        if page:
            candidates += agenda_links(page, event_url)

    page = fetch(CIVICLIVE_COUNCIL, ua=BROWSER_UA)
    if page:
        candidates += agenda_links(page, CIVICLIVE_COUNCIL, tokens)

    for t in sorted(tokens):
        candidates.append(f"{CIVICLIVE_PDF_BASE}{t}/City%20Council%20Agenda%20{t}.pdf")

    seen: set[str] = set()
    fallback_page = ""
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        blob = fetch(url, binary=True, ua=BROWSER_UA)
        if not blob:
            continue
        if blob.startswith(b"%PDF"):
            return url, pdf_items(blob)
        # an agenda *page* — remember it, and look inside for the PDF
        fallback_page = fallback_page or url
        for inner in agenda_links(blob.decode("utf-8", "replace"), url)[:5]:
            if inner in seen:
                continue
            seen.add(inner)
            inner_blob = fetch(inner, binary=True, ua=BROWSER_UA)
            if inner_blob and inner_blob.startswith(b"%PDF"):
                return inner, pdf_items(inner_blob)
    return fallback_page, []


def pdf_items(blob: bytes) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        print("[civic] pypdf not installed — linking agenda without extraction",
              file=sys.stderr)
        return []
    try:
        reader = PdfReader(io.BytesIO(blob))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:  # pypdf raises many types; never fatal here
        print(f"[civic] pdf extract failed: {e}", file=sys.stderr)
        return []
    items, seen = [], set()
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 8 or line.upper() == line and len(line) < 24:
            continue  # page furniture / shouty headers
        if re.fullmatch(r"(page )?\d+( of \d+)?", line.lower()):
            continue
        if line not in seen:
            seen.add(line)
            items.append(line)
        if len(items) >= 80:
            break
    return items


# --------------------------------------------------------------- rendering ---

def esc(s: str) -> str:
    return html.escape(s, quote=True)


def when_label(start: str) -> tuple[str, str]:
    """('Sep 14', '6:00 PM') from an ISO-ish local datetime string."""
    try:
        dt = datetime.fromisoformat(start)
    except (TypeError, ValueError):
        return "", ""
    day = f"{dt.strftime('%b')} {dt.day}"
    if dt.hour or dt.minute:
        hour = dt.hour % 12 or 12
        return day, f"{hour}:{dt.strftime('%M')} {dt.strftime('%p')}"
    return day, ""


def meeting_page_href(m: dict) -> str:
    d = (m.get("start") or "")[:10]
    if d and os.path.exists(os.path.join(PUB, "civic", f"{m['body']}-{d}.html")):
        return f"/civic/{m['body']}-{d}"
    return BODY_PAGES[m["body"]]


def render_rows(meetings: list[dict]) -> str:
    if not meetings:
        return ""
    today = date.today().isoformat()
    rows = []
    for m in meetings:
        d = (m.get("start") or "")[:10]
        if d and d < today:
            continue
        day, tm = when_label(m.get("start") or "")
        title = esc(m["title"])
        bits = [b for b in (tm, esc(m.get("location") or "")) if b]
        tag = ' <span class="tag tag-accent-2">Tonight</span>' if d == today else ""
        rows.append(
            f'  <p class="meet-row"><span class="m-date">{esc(day) or "TBA"}</span>\n'
            f'    <a href="{esc(meeting_page_href(m))}">{title}{tag}</a>\n'
            f'    <span class="m-body">{esc(" · ".join(bits)) if bits else ""}</span></p>')
    return "\n".join(rows)


def render_strip(meetings: list[dict]) -> str:
    """Compact next-meetings line for the front page's Civic Calendar band."""
    today = date.today().isoformat()
    links = []
    for m in meetings:
        d = (m.get("start") or "")[:10]
        if not d or d < today:
            continue
        day, tm = when_label(m.get("start") or "")
        when = "tonight" if d == today else day
        label = f"{esc(m['title'])} — {esc(when)}"
        if tm:
            label += f", {esc(tm)}"
        links.append(f'        <a href="{esc(meeting_page_href(m))}">{label}</a>')
        if len(links) >= 3:
            break
    return "\n        <span aria-hidden=\"true\">·</span>\n".join(links)


def replace_between(path: str, start_marker: str, end_marker: str, content: str) -> bool:
    if not os.path.exists(path):
        return False
    src = open(path, encoding="utf-8").read()
    block = f"{start_marker}\n{content}\n  {end_marker}"
    out, n = re.subn(re.escape(start_marker) + r".*?" + re.escape(end_marker),
                     lambda _: block, src, flags=re.S)
    if n != 1:
        print(f"[civic] markers {start_marker} missing in {os.path.basename(path)}",
              file=sys.stderr)
        return False
    open(path, "w", encoding="utf-8").write(out)
    return True


def render_agenda(url: str, items: list[str]) -> str:
    claim = ("The city has posted the official agenda for this meeting"
             if items else
             "The official agenda for this meeting posts on the city&#39;s site")
    out = [f'  <p class="agenda-note">{claim} — '
           f'<a href="{esc(url)}" rel="noopener">read it at the source</a>.</p>']
    if items:
        out.append('  <ol class="agenda-items">')
        out.extend(f"    <li>{esc(i)}</li>" for i in items)
        out.append("  </ol>")
        out.append('  <p style="font-size:13px;color:color-mix(in srgb, var(--color-text) '
                   '70%, transparent);margin:12px 0 0">Auto-extracted from the city&#39;s '
                   'posted PDF — read the original for the authoritative text.</p>')
    return "\n".join(out)


def main() -> int:
    now = datetime.now(CENTRAL)

    live = city_calendar() + library_board()
    computed = council_schedule() + parks_schedule() + school_board()
    meetings = merge_meetings(computed, live)

    civic_json = os.path.join(PUB, "civic.json")
    prev = []
    if os.path.exists(civic_json):
        try:
            prev = json.load(open(civic_json, encoding="utf-8")).get("meetings", [])
        except (json.JSONDecodeError, OSError):
            pass
    if not meetings and prev:
        print("[civic] all sources empty — keeping previous civic.json")
        meetings = prev
    with open(civic_json, "w", encoding="utf-8") as f:
        json.dump({"updated": now.isoformat(), "meetings": meetings}, f,
                  ensure_ascii=False, indent=1)

    rows = render_rows(meetings)
    if rows:
        replace_between(os.path.join(PUB, "civic.html"),
                        "<!-- CIVIC:START -->", "<!-- CIVIC:END -->", rows)
    strip = render_strip(meetings)
    if strip:
        replace_between(os.path.join(PUB, "index.html"),
                        "<!-- CIVIC-STRIP:START -->", "<!-- CIVIC-STRIP:END -->", strip)

    # Posted agendas → today's / upcoming council meeting pages.
    for m in meetings:
        if m["body"] != "council":
            continue
        d = (m.get("start") or "")[:10]
        if not d:
            continue
        try:
            meet_date = date.fromisoformat(d)
        except ValueError:
            continue
        if not (date.today() <= meet_date <= date.today() + timedelta(days=7)):
            continue
        page = os.path.join(PUB, "civic", f"council-{d}.html")
        if not os.path.exists(page):
            continue
        url, items = find_council_agenda(meet_date, m.get("url") or "")
        if url:
            replace_between(page, "<!-- AGENDA:START -->", "<!-- AGENDA:END -->",
                            render_agenda(url, items))
            print(f"[civic] agenda for {d}: {url} ({len(items)} items)")

    print(f"[civic] {len(meetings)} meetings tracked "
          f"({sum(1 for m in meetings if not m.get('computed'))} from live feeds)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

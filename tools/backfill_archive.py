#!/usr/bin/env python3
"""One-off: seed archive.json from every wire.json snapshot in git history.

Every hourly sweep commits public/wire.json, so the repo's history holds
every item the wire has carried since day one — including items from
before archive.json existed. This walks those snapshots oldest-first,
merges them with the same semantics as the live archive (earliest
first_seen wins, best discussion count kept, sections classified for
pre-section snapshots), folds in the current archive.json, and re-renders
The Morgue.

Run from the repo root:  python3 tools/backfill_archive.py
Idempotent — safe to re-run.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_wire as fw  # noqa: E402  (shared key/categorize/render logic)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, "public", "archive.json")
MORGUE = os.path.join(ROOT, "public", "morgue.html")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def normalize(it: dict, commit_ts: float) -> dict | None:
    if not it.get("title") or not it.get("url"):
        return None
    rec = {k: it.get(k) for k in ("type", "title", "url", "source", "published",
                                  "first_seen", "section", "snippet",
                                  "discussion_url", "num_comments")}
    rec["published"] = float(rec.get("published") or 0)
    rec["first_seen"] = float(rec.get("first_seen") or rec["published"] or commit_ts)
    if not rec.get("section"):
        rec["section"] = fw.categorize(it)
    return rec


def main() -> int:
    shas = git("rev-list", "--reverse", "HEAD", "--", "public/wire.json").split()
    print(f"[backfill] {len(shas)} wire.json snapshots in history")

    by_key: dict[str, dict] = {}
    snapshots_used = 0
    for sha in shas:
        try:
            raw = git("show", f"{sha}:public/wire.json")
            items = json.loads(raw).get("items", [])
            commit_ts = float(git("show", "-s", "--format=%ct", sha).strip())
        except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError):
            continue
        snapshots_used += 1
        for it in items:
            rec = normalize(it, commit_ts)
            if not rec:
                continue
            key = fw.item_key(rec)
            old = by_key.get(key)
            if old:
                rec["first_seen"] = min(old["first_seen"], rec["first_seen"])
                if not rec["published"]:
                    rec["published"] = old["published"]
                rec["num_comments"] = max(int(old.get("num_comments") or 0),
                                          int(rec.get("num_comments") or 0)) or None
            by_key[key] = rec

    # fold in the live archive (it may hold items these snapshots don't)
    if os.path.exists(ARCHIVE):
        for it in json.load(open(ARCHIVE, encoding="utf-8")).get("items", []):
            key = fw.item_key(it)
            old = by_key.get(key)
            if old and old.get("first_seen") and it.get("first_seen"):
                it = dict(it, first_seen=min(it["first_seen"], old["first_seen"]))
            by_key[key] = it

    now = datetime.now(fw.CENTRAL)
    merged = sorted(by_key.values(), key=fw.item_stamp, reverse=True)[:fw.ARCHIVE_KEEP]
    with open(ARCHIVE, "w", encoding="utf-8") as f:
        json.dump({"updated": now.isoformat(), "items": merged}, f,
                  ensure_ascii=False, indent=1)

    import re
    mp = open(MORGUE, encoding="utf-8").read()
    mblock = ("<!-- MORGUE:START -->\n      " + fw.render_morgue(merged, now)
              + "\n      <!-- MORGUE:END -->")
    mp, n = re.subn(r"<!-- MORGUE:START -->.*?<!-- MORGUE:END -->",
                    lambda _: mblock, mp, flags=re.S)
    stamp = fw.when_label(now.timestamp(), now) + " CT"
    mp = re.sub(r'(<span id="morgue-updated">)[^<]*(</span>)',
                lambda m: m.group(1) + f"{len(merged)} stories · Updated " + stamp + m.group(2), mp)
    if n == 1:
        open(MORGUE, "w", encoding="utf-8").write(mp)
    print(f"[backfill] {snapshots_used} snapshots -> {len(merged)} archived items; "
          f"morgue {'re-rendered' if n == 1 else 'MARKERS MISSING'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

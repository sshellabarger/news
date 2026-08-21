#!/usr/bin/env python3
"""Unbundle a __bundler-format single-file export into template + resources.

Usage: python3 tools/unbundle_export.py <export.html> [out_dir]

Canvas exports ship as one self-unpacking HTML file whose real page lives in
an escaped <script type="__bundler/template"> string — invisible to search
engines. This extracts the template plus every font/script resource so the
page can be rebuilt as static, crawlable HTML (see README, "New editions").
"""
import base64, gzip, json, os, re, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "export.html"
OUT = sys.argv[2] if len(sys.argv) > 2 else "unbundled"
os.makedirs(OUT, exist_ok=True)

html = open(SRC, encoding="utf-8").read()

def section(name):
    m = re.search(r'<script type="__bundler/%s">\s*(.*?)\s*</script>' % name, html, re.S)
    return m.group(1) if m else None

manifest = json.loads(section("manifest"))
template = json.loads(section("template"))
ext = json.loads(section("ext_resources") or "[]")
page_order = json.loads(section("page_order") or "[]")

print("manifest entries:", len(manifest))
print("ext resources:", ext)
print("page_order:", page_order)

open(os.path.join(OUT, "template.html"), "w", encoding="utf-8").write(template)
print("template chars:", len(template))

meta = {}
for uuid, entry in manifest.items():
    data = base64.b64decode(entry["data"])
    if entry.get("compressed"):
        data = gzip.decompress(data)
    meta[uuid] = {"mime": entry["mime"], "size": len(data)}
    ext_map = {"font/woff2": ".woff2", "text/javascript": ".js", "text/css": ".css",
               "image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg",
               "image/webp": ".webp"}
    suffix = ext_map.get(entry["mime"], ".bin")
    with open(os.path.join(OUT, uuid + suffix), "wb") as f:
        f.write(data)
    # count references in template
    meta[uuid]["refs_in_template"] = template.count(uuid)

json.dump(meta, open(os.path.join(OUT, "manifest_meta.json"), "w"), indent=1)
for uuid, m in sorted(meta.items(), key=lambda kv: -kv[1]["size"]):
    print(f'{uuid}  {m["mime"]:<18} {m["size"]:>9}B  refs={m["refs_in_template"]}')

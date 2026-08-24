# SEO & Reach Strategy — dirtydogtown.news

*Grounded in an audit of this repo (public/, tools/fetch_wire.py, workflows) as of
issue № 005, August 2026. The site is five days old — everything here assumes a
new domain earning trust from zero.*

## Where we stand

The technical on-page work is already done, and done well. Don't redo it:

- Complete `<head>` on `/`: tuned title/description, canonical, robots directives,
  Open Graph + Twitter cards with a branded image, geo meta, and a JSON-LD graph
  (`NewsMediaOrganization`, `WebSite`, `WebPage`, `FAQPage`).
- `/morgue` has its own metadata, `CollectionPage` + breadcrumb markup.
- `robots.txt`, `sitemap.xml` (lastmod bumped hourly), noindex on `/admin`,
  `/thanks`, `/unsubscribe`, 404 page.
- The wire and the morgue are **server-baked HTML** (markers rewritten by
  `tools/fetch_wire.py`) — crawlers see real content, not a JS shell.
- Hourly fresh content, RSS feed, self-hosted preloaded fonts, deferred JS,
  sane cache headers. Page is text-first; performance is not a problem.

**The ceiling is structural, not technical.** Three findings drive everything
below:

1. **The site has exactly two indexable URLs.** Every story is a fragment
   (`#story-travelers-lease`) on one page. Fragments are not URLs to Google — the
   site can rank for "north little rock news," but it has no *documents* to rank
   for "dickey-stephens lease" or "NLR police overtime audit."
2. **The only original content has no permanent home.** The curated `<article>`
   blocks in `index.html` are the site's real content, but they aren't in
   `archive.json` — when they're edited off the front page they vanish from the
   site and the index entirely. The wire, meanwhile, is aggregated headlines that
   will always rank *below* their sources.
3. **Nothing is measured and nothing is distributed.** No Search Console
   verification confirmed, no analytics of any kind, no social presence, and the
   wire's outbound links go to `news.google.com` redirect URLs rather than
   publishers.

The strategy: keep the hourly wire as the freshness engine, but grow a body of
**original, permalinked, hyperlocal documents** around it, and build the
measurement + distribution loop. A five-day-old domain wins on queries nobody
else bothers with — neighborhood names, civic process, "why is it called
Dogtown" — not on breaking-news queries against KATV and the Democrat-Gazette.

---

## Tier 1 — This week

### 1. Verify Search Console + Bing, submit the sitemap *(owner, ~30 min)*
The README already prescribes it; make it real. Google Search Console (domain
property `dirtydogtown.news`) and Bing Webmaster Tools, submit
`https://dirtydogtown.news/sitemap.xml` to both. GSC query data is the only
free view into what locals actually search — every later decision improves
with it.

### 2. Permalink pages for original stories *(code, ~a day)*
The single highest-ROI build. A small generator (pattern of `fetch_wire.py`)
that emits `/story/<slug>` pages from a stories source (front matter or JSON):

- Each page: own `<title>`/description/canonical/OG, **`NewsArticle` JSON-LD**
  (headline, datePublished/Modified, publisher → `#organization`), breadcrumbs,
  the existing comments thread (`data-story` already keys threads by slug), and
  links back to `/` and related coverage.
- The front page keeps the summary/lede, headline links to the permalink
  (replacing today's self-referential `#story-*` links).
- Every story page joins `sitemap.xml`; stories never vanish again — aged
  stories get listed on the morgue.
- This also unlocks per-story sharing (real URLs for Facebook/Reddit) and is a
  prerequisite for Google News inclusion (Tier 2).

### 3. Trust pages: /about + corrections *(content, ~2 hrs)*
Google's news systems (and humans deciding whether to link or subscribe) look
for: who runs this, how it's produced, how to reach it, how errors get fixed.
One `/about` page covering ownership ("Operated by Clean Dog Town"), how the
wire works, the tip line, and a short corrections policy; linked from the
footer, listed in the sitemap, referenced from the JSON-LD org (`sameAs`/
`publishingPrinciples`/`correctionsPolicy`). The site's "unsigned and unbossed"
voice can stay — anonymity of authors is fine when the operation itself is
transparent about process.

### 4. IndexNow pings from the wire *(code, ~1 hr)*
Google's sitemap-ping endpoint is dead, but IndexNow (Bing, Yandex, Seznam,
Naver) is alive and free: host a key file in `public/`, and have
`fetch_wire.py` POST changed URLs each sweep. Instant indexing on half the
search market for the cost of one HTTP call.

### 5. Turn on any analytics at all *(owner + 1 script tag)*
GSC shows queries; nothing shows visits. A privacy-light counter (GoatCounter,
Plausible, or GA4 if free matters most) on `/`, `/morgue`, and story pages.
Reach work without measurement is guessing.

---

## Tier 2 — This month

### 6. Resolve Google News redirect links *(code)*
Wire items store and display `news.google.com/rss/articles/CBMi…` URLs —
permanently, in `archive.json`. Best-effort resolve to the publisher's real URL
at fetch time (decode/expand, fall back to the redirect on failure), and strip
the trailing " - Publisher" from titles (the source is already shown
separately). Cleaner UX, honest outbound links, better-looking morgue and RSS.

### 7. Neighborhood pages *(code + content)*
The org markup already claims Argenta, Park Hill, Levy, Rose City, Baring
Cross, Lakewood, Amboy. Nobody on the internet is competing for "argenta news"
or "levy north little rock." Keyword-tag wire items by neighborhood in
`fetch_wire.py` (same pattern as `SECTION_KEYWORDS`), then emit one page per
neighborhood: a short human-written blurb + the filtered wire + tagged stories.
Seven indexable, self-updating pages targeting queries with zero competition.

### 8. Own the civic-calendar queries *(content cadence, the big one)*
Recurring original coverage from public documents nobody else covers
consistently:

- **Monday: council agenda preview** (agendas are public on nlr.ar.gov) —
  targets "north little rock city council agenda" every single week.
- **Post-meeting recap** (the Travelers-lease story shows the format works).
- School board, planning commission, parks commission as capacity allows.

Two to three short permalinked stories a week beats any technical change on
this list. It compounds: every recap is a document Google can rank, a digest
item, a social post, and a reason for the Democrat-Gazette's paywalled readers
to come here instead.

### 9. Morgue month pages *(code)*
The morgue renders 600 rows on one page and truncates beyond that. Emit
`/morgue/<yyyy-mm>` pages (linked from `/morgue`) as the archive grows — each
month becomes an indexable "North Little Rock news, August 2026" document, and
nothing is crawl-invisible past the render cap.

### 10. Google Publisher Center *(owner, after #2 + #3)*
With permalinks, dates, and an about page in place, submit the site in Google
Publisher Center. Inclusion in the Google News tab / news surfaces is the
single biggest free-reach lever available to a news site, and the RSS feed is
already there to power it.

---

## Tier 3 — Ongoing reach loop

### 11. Work the distribution the repo already built
`weekly_front.py` renders `this-week.png` *specifically* for Facebook groups
and Nextdoor — but posting is manual and hasn't started. Make it a Monday
ritual: the image + two headlines + link into the NLR Facebook groups and
Nextdoor (no APIs exist for either; manual is the only way). Create a Facebook
Page as the site's identity for it. This is where North Little Rock actually
is online; expect it to dwarf search traffic for months.

### 12. Automated social presence *(code, cheap)*
A Bluesky account posted by a GitHub Action on new wire sweeps / daily digest
(free API, stdlib-friendly). Add X later only if the free write tier suffices.
On Reddit (r/LittleRock): participate genuinely, link only when it adds
context — the site already quotes their threads; goodwill there is worth more
than links.

### 13. Local backlinks *(owner, steady drip)*
For a five-day-old domain, a handful of real local links outweighs everything
else on this page. Targets: Laman Library's community links, neighborhood
association newsletters, Argenta arts orgs, PTAs and booster clubs, the
chamber, Arkansas blogs/podcasts. The pitch is genuinely good: "free, no-ads
hourly NLR news wire + daily email digest + anonymous tip line."

### 14. Grow the digest
The email capture lives only in the footer. Add a one-line subscribe CTA in
the nav area and after the lead story, and put the digest URL on every shared
image. The digest is the retention layer that makes all acquisition stick.

---

## Honest expectations & footnotes

- **FAQ rich results:** since 2023 Google only shows them for well-known
  authoritative sites. Keep the `FAQPage` markup (it's good content and may
  surface in AI/answer features), but don't expect rich snippets.
- **The wire can't outrank its sources** and doesn't need to — its jobs are
  freshness signals, return visits, and being genuinely useful. The original
  stories do the ranking.
- **Timeline:** brand/navigational queries ("dogtown news") should be won in
  weeks; non-brand hyperlocal queries in 2–4 months of consistency; competitive
  news queries maybe never, and that's fine.
- `meta keywords` is inert everywhere (harmless to keep); `changefreq`/
  `priority` in the sitemap are ignored by Google (also harmless).
- When adding pages, remember the pattern the repo already enforces: real HTML
  in `public/`, metadata in the `<head>`, listed in `sitemap.xml`, linked from
  the footer or a nav — never JS-only.

## Suggested order of operations

| When | What | Type |
| --- | --- | --- |
| Now | GSC + Bing verification, sitemap submission | Owner |
| Week 1 | Story permalink generator + `NewsArticle` markup | Code |
| Week 1 | `/about` + corrections policy | Content |
| Week 1 | IndexNow pings in the wire; analytics tag | Code |
| Week 2–4 | Redirect-link resolution; neighborhood pages; morgue months | Code |
| Week 2–4 | Council agenda preview cadence begins | Content |
| Week 4+ | Publisher Center submission | Owner |
| Every Monday | `this-week.png` → Facebook groups + Nextdoor | Owner |
| Ongoing | Local link outreach; Bluesky automation; digest CTAs | Mixed |

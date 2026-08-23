# Dirty Dogtown — dirtydogtown.news

Neighborhood news for North Little Rock, Arkansas, on Firebase Hosting.
Static site (`public/`), a free tip form, an hourly automated news wire,
and moderated public comments.

## Deploy

One-time setup:
1. `npm install -g firebase-tools`
2. `firebase login`
3. Create a project at console.firebase.google.com, then put its ID in
   `.firebaserc` (replace `YOUR-FIREBASE-PROJECT-ID`).

Deploy (from this folder):
```
firebase deploy --only hosting          # site only
firebase deploy                         # site + Firestore rules (comments)
```

## What's in the box

| Piece | Where | Status |
| --- | --- | --- |
| Static, SEO-complete front page | `public/index.html` | Works on deploy |
| Send-a-Tip form (FormSubmit, free) | `public/index.html` | Needs one-click activation (below) |
| Hourly news wire | `.github/workflows/news-wire.yml` + `tools/fetch_wire.py` | Works once pushed to GitHub; auto-deploys with secrets (below) |
| Public comments + moderation | `public/comments.js`, `public/admin.html`, `firestore.rules` | Needs Firebase config (below) |

## SEO

The old export was a JavaScript-unpacked bundle — crawlers saw a page titled
"Bundled Page" with no readable content. The page is now plain HTML with all
three views (Feed / Send a Tip / Terms) in the DOM, plus:

- Title/description/canonical tuned for "North Little Rock AR news",
  Open Graph + Twitter cards with a branded `og-image.png`, geo meta tags
  (`US-AR`, coordinates), and `robots` directives.
- JSON-LD structured data: `NewsMediaOrganization` (areaServed: North Little
  Rock / Dogtown), `WebSite`, and `WebPage`.
- `robots.txt`, `sitemap.xml` (lastmod auto-bumped by the wire), a 404 page,
  self-hosted fonts with preload, and cache headers in `firebase.json`.
- The hourly wire adds fresh, crawlable HTML (with outbound links) every hour
  — the strongest ongoing signal for local-news queries.

After the first deploy: add the site in
[Google Search Console](https://search.google.com/search-console) (domain
property `dirtydogtown.news`), submit `https://dirtydogtown.news/sitemap.xml`,
and do the same in Bing Webmaster Tools.

## Send-a-Tip form (FormSubmit — free, no account)

The form posts to [FormSubmit](https://formsubmit.co/) at
`tips@dirtydogtown.news`, with an AJAX submit, honeypot spam trap, and a
non-JavaScript fallback that redirects to `/thanks`.

To activate: submit the form once after deploying. FormSubmit emails
`tips@dirtydogtown.news` a confirmation link — click it and every later tip
lands in that inbox. (If `tips@` isn't a live mailbox yet, swap both
`formsubmit.co/...` URLs in `public/index.html` to an inbox you control.)
Optional: after activation FormSubmit gives you a random alias string you can
use in place of the address to keep scrapers off it.

## Hourly news wire

`tools/fetch_wire.py` (stdlib Python, no keys) sweeps Google News RSS and
Reddit for North Little Rock items — headlines, posts, and top public
comments — and rewrites the "Wire" section of `index.html` plus
`public/wire.json`. Every item links to its source; quoted comments link to
their permalinks.

- GitHub Actions runs it at :17 every hour (`news-wire.yml`) and commits.
- To auto-deploy the wire to Firebase, add two repo secrets
  (Settings → Secrets and variables → Actions):
  - `FIREBASE_SERVICE_ACCOUNT` — JSON key for a service account with the
    "Firebase Hosting Admin" role (console → Project settings → Service
    accounts → Generate new private key).
  - `FIREBASE_PROJECT_ID` — the project ID.
  Without them the workflow still commits the fresh wire to the repo; it just
  skips the deploy.
- Run locally anytime: `python3 tools/fetch_wire.py`.
- Sources are best-effort: Nextdoor/Facebook aren't publicly fetchable;
  add more RSS feeds in `GOOGLE_NEWS_QUERIES` / `REDDIT_ENDPOINTS`.

## Wire sections, stamps, and Hot stories

The fetcher classifies every wire item into **Major News** (the bulk of the
page), **Crime & Safety**, **Sports**, or **Obituaries** using keyword and
source rules — tune them in `SECTION_KEYWORDS` in `tools/fetch_wire.py`.
Each item shows when the source **Filed** it and when the wire first
**Pulled** it (carried across runs via `wire.json`). The most-discussed
items (5+ Reddit comments, top 3) get a **Hot story** tag; curated stories
with 3+ approved on-site comments get a **Popular** tag automatically.

## Daily issue, The Morgue, and search

- The masthead's **issue number advances daily** (№ 001 = launch day,
  Aug 20 2026 — change `ISSUE_EPOCH` in `tools/fetch_wire.py` to renumber)
  and shows the last-updated time next to it; the dateline date stays
  current automatically.
- The front page carries roughly the **last two weeks** (`FRESH_DAYS`).
  Everything the wire has ever seen lives permanently in
  `public/archive.json` and renders month-by-month at **/morgue** ("The
  Morgue" — newsroom slang for the archive room). Nothing is lost when a
  story ages off the front page.
- The **search box** in the nav (front page and Morgue) searches the full
  archive client-side — title, snippet, source, and section — newest
  first, no server or account needed.

## Subscriptions

**RSS**: the fetcher regenerates `public/feed.xml` hourly — linked from the
page head and the Subscribe block in the footer. Works in any feed reader,
no setup.

**Daily email digest** (free via [Brevo](https://www.brevo.com), 300
emails/day): visitors sign up in the footer (stored create-only in the
Firestore `subscribers` collection; `/unsubscribe` writes to
`unsubscribes`, which the sender honors). Every morning at 7am Central,
`daily-digest.yml` runs `tools/send_digest.py` to build a digest of the
last 24h and email each subscriber. Until configured it dry-runs
harmlessly. To turn on sending:

1. Create a free Brevo account, verify a sender address (or the domain),
   and create an API key (SMTP & API → API Keys).
2. Add repo secrets: `BREVO_API_KEY`, and optionally `DIGEST_FROM_EMAIL`
   (defaults to `tips@dirtydogtown.news` — must be a Brevo-verified sender).
3. In Google Cloud IAM, grant the deploy service account the
   **Cloud Datastore Viewer** role so the job can read subscriber emails.
4. Redeploy Firestore rules (the `subscribers`/`unsubscribes` collections):
   `firebase deploy --only firestore:rules --project dirtydogtownnews`.

## Public comments (free Firestore + `/admin`)

Each story (and the wire) has a "Neighborhood comments" thread. Comments are
**pre-moderated**: they write to Firestore as `pending` and only show once
approved. Setup:

1. In the Firebase console enable **Firestore** (production mode) and
   **Authentication → Google** sign-in.
2. Copy the web-app config (Project settings → Your apps → Web) into
   `public/firebase-config.js`.
3. Deploy rules: `firebase deploy --only firestore:rules`.
4. Sign in once at `https://dirtydogtown.news/admin`, copy the UID it shows,
   and create Firestore doc `admins/<that-uid>` (any contents). That account
   can now approve, unapprove, and delete from `/admin`.

Until step 2 happens the threads show a quiet "comments open soon" note —
nothing breaks.

## New editions

`public/index.html` is now the source of truth — edit the articles inside
`<main>` directly (keep the `<!-- WIRE:START/END -->` markers and the
`<head>` block, which carries the SEO). If you export a new edition from the
canvas tool instead, it arrives as a self-unpacking bundle that search
engines can't read: run `python3 tools/unbundle_export.py <export.html>` to
extract its real HTML, then merge the body into `index.html` rather than
replacing the file.

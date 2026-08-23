/* Dirty Dogtown — site search.
 *
 * Searches the full corpus (/archive.json — every story the wire has
 * carried) client-side: title, snippet, source, and section. Works on the
 * front page (hides the views while results show) and on The Morgue
 * (hides the month list). No dependencies, no server.
 */
(function () {
  var input = document.getElementById("site-search");
  var panel = document.getElementById("search-results");
  if (!input || !panel) return;

  var SECTION_NAMES = { major: "Major News", crime: "Crime & Safety",
                        sports: "Sports", obits: "Obituaries" };
  var corpus = null;
  var loading = false;
  var timer = null;

  function load() {
    if (corpus || loading) return;
    loading = true;
    fetch("/archive.json").then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (data) {
      corpus = (data.items || []).map(function (it) {
        return {
          it: it,
          hay: [it.title, it.snippet, it.source,
                SECTION_NAMES[it.section] || ""].join(" ").toLowerCase(),
        };
      });
      run();
    }).catch(function (err) {
      console.warn("[search]", err);
      loading = false;
      panel.hidden = false;
      panel.textContent = "Search isn’t available right now — try again in a minute.";
    });
  }

  function pageSections() {
    return ["view-feed", "view-submit", "view-legal", "morgue-content"]
      .map(function (id) { return document.getElementById(id); })
      .filter(Boolean);
  }

  function show(active) {
    pageSections().forEach(function (el) { el.hidden = active ? true : el.hidden; });
    panel.hidden = !active;
    if (!active) {
      // hand visibility back to the page (the router on the front page,
      // plain display on the morgue)
      if (document.getElementById("view-feed")) {
        window.dispatchEvent(new HashChangeEvent("hashchange"));
      } else {
        pageSections().forEach(function (el) { el.hidden = false; });
      }
    }
  }

  function fmtDate(it) {
    var ts = (it.published || it.first_seen || 0) * 1000;
    if (!ts) return "";
    var d = new Date(ts);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  function run() {
    var q = input.value.trim().toLowerCase();
    if (!q) { show(false); return; }
    if (!corpus) { load(); return; }
    var terms = q.split(/\s+/).filter(Boolean);
    var hits = [];
    for (var i = 0; i < corpus.length && hits.length < 40; i++) {
      var c = corpus[i];
      var ok = true;
      for (var t = 0; t < terms.length; t++) {
        if (c.hay.indexOf(terms[t]) === -1) { ok = false; break; }
      }
      if (ok) hits.push(c.it);
    }
    panel.textContent = "";
    var head = document.createElement("p");
    head.style.cssText = "font-size:13px;letter-spacing:0.08em;text-transform:uppercase;opacity:0.65;margin:0 0 14px";
    head.textContent = hits.length
      ? "Search · " + hits.length + (hits.length === 40 ? "+" : "") + " result" + (hits.length === 1 ? "" : "s")
      : "Search · nothing found for “" + q + "” — try fewer or different words";
    panel.appendChild(head);
    hits.forEach(function (it) {
      var row = document.createElement("p");
      row.style.cssText = "margin:0;padding:9px 0;border-bottom:1px solid color-mix(in srgb, var(--color-text) 8%, transparent);font-size:16px;line-height:1.5";
      var meta = document.createElement("span");
      meta.style.cssText = "display:block;font-size:12px;letter-spacing:0.06em;text-transform:uppercase;opacity:0.6";
      meta.textContent = [fmtDate(it), SECTION_NAMES[it.section] || "Major News", it.source]
        .filter(Boolean).join(" · ");
      var a = document.createElement("a");
      a.href = it.url;
      a.rel = "noopener";
      a.textContent = it.title;
      a.style.cssText = "color:inherit";
      row.appendChild(meta);
      row.appendChild(a);
      panel.appendChild(row);
    });
    show(true);
  }

  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(run, 160);
  });
  input.addEventListener("focus", load);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { input.value = ""; run(); input.blur(); }
  });
})();

/* Dirty Dogtown — public comment threads.
 *
 * Reads window.DD_FIREBASE_CONFIG (set in firebase-config.js). Until that
 * file carries a real Firebase project config, every thread renders a
 * quiet "opening soon" note instead of a form.
 *
 * Data model: Firestore collection "comments"
 *   { story, name, text, status: "pending" | "approved", createdAt }
 * Clients may only create status:"pending" docs and only read
 * status:"approved" ones — see firestore.rules. Moderation happens in
 * /admin.
 */

const config = window.DD_FIREBASE_CONFIG;
const threads = document.querySelectorAll(".dd-comments");
const tipForm = document.getElementById("tip-form");
const configured = config && config.apiKey && config.apiKey.indexOf("REPLACE") === -1;

if (!configured) {
  threads.forEach((t) => {
    const note = t.querySelector(".dd-note");
    const form = t.querySelector(".dd-comment-form");
    if (form) form.hidden = true;
    const p = document.createElement("p");
    p.className = "dd-comment";
    p.textContent =
      "Comments open soon. Meanwhile, send thoughts to tips@dirtydogtown.news.";
    t.querySelector(".dd-thread").appendChild(p);
    if (note) note.textContent = "";
  });
  if (tipForm) {
    tipForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const status = document.getElementById("tip-status");
      if (status) {
        status.textContent =
          "The tip line is warming up — email tips@dirtydogtown.news meanwhile.";
        status.hidden = false;
      }
    });
  }
} else if (threads.length || tipForm) {
  boot().catch((err) => console.warn("[comments]", err));
}

async function boot() {
  const [{ initializeApp }, fs] = await Promise.all([
    import("https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js"),
    import("https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js"),
  ]);
  const {
    getFirestore, collection, query, where, getDocs,
    addDoc, serverTimestamp,
  } = fs;
  const db = getFirestore(initializeApp(config));

  initTips(db, { collection, addDoc, serverTimestamp });

  for (const t of threads) {
    const slug = t.getAttribute("data-story");
    const list = t.querySelector(".dd-thread");
    const form = t.querySelector(".dd-comment-form");
    const note = form.querySelector(".dd-note");
    const count = t.querySelector(".dd-count");

    try {
      const snap = await getDocs(query(
        collection(db, "comments"),
        where("story", "==", slug),
        where("status", "==", "approved")
      ));
      const docs = snap.docs
        .map((d) => d.data())
        .sort((a, b) => (a.createdAt?.seconds || 0) - (b.createdAt?.seconds || 0));
      list.textContent = "";
      for (const c of docs) list.appendChild(render(c));
      if (count && docs.length) count.textContent = " (" + docs.length + ")";
      if (docs.length >= 3 && !t.querySelector(".dd-popular")) {
        const tag = document.createElement("span");
        tag.className = "tag tag-accent-2 dd-popular";
        tag.textContent = "Popular";
        tag.style.marginLeft = "10px";
        t.querySelector("summary").appendChild(tag);
      }
    } catch (err) {
      console.warn("[comments] load failed for", slug, err);
    }

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = form.elements.text.value.trim();
      if (!text) return;
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      note.textContent = "Posting…";
      try {
        await addDoc(collection(db, "comments"), {
          story: slug,
          name: (form.elements.name.value.trim() || "Neighbor").slice(0, 60),
          text: text.slice(0, 2000),
          status: "pending",
          createdAt: serverTimestamp(),
        });
        form.reset();
        note.textContent =
          "Received. Your comment appears once a moderator approves it.";
      } catch (err) {
        console.warn("[comments] post failed", err);
        note.textContent =
          "Couldn’t post just now — try again, or email tips@dirtydogtown.news.";
      }
      button.disabled = false;
    });
  }
}

function initTips(db, fs) {
  const form = document.getElementById("tip-form");
  if (!form) return;
  const status = document.getElementById("tip-status");

  function say(html) {
    if (!status) return;
    status.innerHTML = html;
    status.hidden = false;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (form.elements._honey && form.elements._honey.value) return; // bot trap
    const what = form.elements.what.value.trim();
    if (what.length < 3) return;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = "Filing…";
    try {
      await fs.addDoc(fs.collection(db, "tips"), {
        what: what.slice(0, 5000),
        where: (form.elements.where.value || "").trim().slice(0, 200),
        when: (form.elements.when.value || "").trim().slice(0, 200),
        cat: (form.elements.cat.value || "").slice(0, 60),
        contact: (form.elements.contact.value || "").trim().slice(0, 254),
        createdAt: fs.serverTimestamp(),
      });
      form.reset();
      say('<strong style="font-style:normal;font-weight:600">Tip received.</strong> ' +
          "A moderator will review it. If it runs, it runs unsigned.");
    } catch (err) {
      console.warn("[tips]", err);
      say('<strong style="font-style:normal;font-weight:600">Couldn\u2019t file that just now.</strong> ' +
          'Try again in a minute, or email <a href="mailto:tips@dirtydogtown.news">tips@dirtydogtown.news</a>.');
    }
    button.disabled = false;
    button.textContent = "File it";
  });
}

function render(c) {
  const p = document.createElement("p");
  p.className = "dd-comment";
  p.textContent = c.text;
  const who = document.createElement("span");
  who.className = "who";
  const when = c.createdAt && c.createdAt.seconds
    ? " · " + new Date(c.createdAt.seconds * 1000).toLocaleDateString("en-US", {
        month: "short", day: "numeric",
      })
    : "";
  who.textContent = "— " + (c.name || "Neighbor") + when;
  p.appendChild(who);
  return p;
}

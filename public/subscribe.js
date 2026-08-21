/* Dirty Dogtown — daily-digest email signup (and unsubscribe).
 *
 * Handles #sub-form (writes to Firestore "subscribers") on the front page
 * and #unsub-form (writes to "unsubscribes") on /unsubscribe. Both are
 * create-only collections — see firestore.rules. Until firebase-config.js
 * holds a real config, forms show a quiet note instead.
 */

const config = window.DD_FIREBASE_CONFIG;
const FORMS = [
  {
    id: "sub-form",
    collectionName: "subscribers",
    ok: "You’re on the list — the next daily digest lands in your inbox.",
    already: "Couldn’t sign you up just now — try again in a minute.",
  },
  {
    id: "unsub-form",
    collectionName: "unsubscribes",
    ok: "Done. You’ll get no more digests after today.",
    already: "Couldn’t process that just now — try again in a minute.",
  },
];

const present = FORMS.map((f) => ({ ...f, el: document.getElementById(f.id) }))
  .filter((f) => f.el);

if (present.length) {
  if (!config || !config.apiKey || config.apiKey.indexOf("REPLACE") !== -1) {
    for (const f of present) {
      const note = f.el.querySelector(".sub-note");
      f.el.querySelector("button").disabled = true;
      if (note) note.textContent = "Email sign-up opens soon — grab the RSS feed meanwhile.";
    }
  } else {
    boot().catch((err) => console.warn("[subscribe]", err));
  }
}

async function boot() {
  const [{ initializeApp }, fs] = await Promise.all([
    import("https://www.gstatic.com/firebasejs/10.12.2/firebase-app.js"),
    import("https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore.js"),
  ]);
  const { getFirestore, collection, addDoc, serverTimestamp } = fs;
  const db = getFirestore(initializeApp(config));

  for (const f of present) {
    f.el.addEventListener("submit", async (e) => {
      e.preventDefault();
      const note = f.el.querySelector(".sub-note");
      const button = f.el.querySelector("button");
      const email = f.el.elements.email.value.trim().toLowerCase();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        if (note) note.textContent = "That doesn’t look like an email address.";
        return;
      }
      button.disabled = true;
      if (note) note.textContent = "One moment…";
      try {
        await addDoc(collection(db, f.collectionName), {
          email: email.slice(0, 254),
          createdAt: serverTimestamp(),
        });
        f.el.reset();
        if (note) note.textContent = f.ok;
      } catch (err) {
        console.warn("[subscribe]", err);
        if (note) note.textContent = f.already;
      }
      button.disabled = false;
    });
  }
}

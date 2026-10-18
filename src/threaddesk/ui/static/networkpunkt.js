/* Optional portable disclosure support. Only UI open/closed flags are stored.
   No application data, requests or product permissions live in this module. */
(() => {
  const key = "np-disclosures-v1";
  let state = {};
  try { state = JSON.parse(sessionStorage.getItem(key) || "{}"); } catch (_) { /* Storage can be unavailable. */ }
  if (!state || typeof state !== "object" || Array.isArray(state)) state = {};
  const restore = () => document.querySelectorAll("details[data-disclosure]").forEach(el => {
    if (Object.hasOwn(state, el.dataset.disclosure)) el.open = state[el.dataset.disclosure] === true;
  });
  document.addEventListener("toggle", event => {
    const el = event.target;
    if (!(el instanceof HTMLDetailsElement) || !el.dataset.disclosure || !el.isConnected) return;
    state[el.dataset.disclosure] = el.open;
    try { sessionStorage.setItem(key, JSON.stringify(state)); } catch (_) { /* In-memory fallback. */ }
  }, true);
  window.npReveal = el => {
    if (!el) return;
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      if (parent instanceof HTMLDetailsElement) parent.open = true;
    }
    el.scrollIntoView({block: "nearest"});
  };
  restore();
  document.addEventListener("htmx:afterSwap", restore);
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    const preferences = document.querySelector(".preferences[open]");
    if (preferences) { preferences.open = false; preferences.querySelector("summary").focus(); }
  });
  document.addEventListener("click", event => {
    const preferences = document.querySelector(".preferences[open]");
    if (preferences && !preferences.contains(event.target)) preferences.open = false;
  });
})();

/* Alpine hooks for later phases. Phase 1 is HTMX-only. */
document.addEventListener("htmx:sendError", () => {
  console.warn("ThreadDesk UI: Anfrage fehlgeschlagen");
});

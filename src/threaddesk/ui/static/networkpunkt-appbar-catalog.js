/* Versioned installation catalog. Approved existing pixels; no runtime discovery. */
export const CATALOG_VERSION = "1.0.0";
export const APP_CATALOG = Object.freeze([
  Object.freeze({ id: "threaddesk", name: Object.freeze({ de: "ThreadDesk", en: "ThreadDesk" }),
    icon: "np-appbar-threaddesk-dark-48.png", color: "#b99cff", colorSource: "ThreadDesk:brand/README.md", routes: Object.freeze(["host-adapter"]) }),
  Object.freeze({ id: "4allpass", name: Object.freeze({ de: "4AllPass", en: "4AllPass" }),
    icon: "np-appbar-4allpass-dark-48.png", color: null, colorSource: null, routes: Object.freeze(["host-adapter"]) }),
]);
// No placeholder logo: these entries require actual approved asset assignment.
export const ASSET_BLOCKERS = Object.freeze({ kirabridge: "approved-icon-missing", tollgate: "asset-not-assigned" });
export const COLOR_BLOCKERS = Object.freeze({ "4allpass": "documented-brand-color-unassigned" });

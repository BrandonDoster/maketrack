// maketrack service worker — install-only, network-only.
//
// Its sole job is to make the app installable as a standalone desktop/mobile
// app. It deliberately does NOT cache anything: maketrack is a single-user,
// LAN-only tool whose pages are live, server-rendered HTML (HTMX), so cached
// responses would just serve stale data. Every request goes straight to the
// network exactly as it would without a service worker.
//
// If offline support is ever wanted, this is where a caching strategy would go.

self.addEventListener("install", () => {
  // Activate this version immediately instead of waiting for old tabs to close.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // Take control of open clients so updates apply without a manual reload.
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", () => {
  // No respondWith() → the browser performs its default network fetch.
  // The empty handler exists only so the app meets install criteria.
});

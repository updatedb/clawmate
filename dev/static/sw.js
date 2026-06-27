// ClawMate Service Worker — cache-first for static assets,
// network-first for API, stale-while-revalidate for vendor libs.
const CACHE_VERSION = 'v20260627a';
const STATIC_CACHE = 'clawmate-static-' + CACHE_VERSION;
const VENDOR_CACHE = 'clawmate-vendor-' + CACHE_VERSION;
const API_CACHE = 'clawmate-api-' + CACHE_VERSION;

// ── Assets to pre-cache on install ──────────────────────────────────
const PRECACHE_URLS = [
  '/clawmate/',
  '/clawmate/css/tokens.css',
  '/clawmate/css/style.css',
  '/clawmate/css/preview.css',
  '/clawmate/css/login.css',
  '/clawmate/js/icons.js',
  '/clawmate/js/topbar.js',
  '/clawmate/js/app.js',
  '/clawmate/js/preview.js',
  '/clawmate/js/preview-common.js',
  '/clawmate/js/agent.js',
  '/clawmate/asset/clawmate-logo.png',
  '/clawmate/manifest.json',
];

// ── Install — pre-cache core app shell ──────────────────────────────
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      return Promise.allSettled(PRECACHE_URLS.map((url) =>
        cache.add(url).catch(() => { /* ignore individual failures */ })
      ));
    }).then(() => self.skipWaiting())
  );
});

// ── Activate — clean old caches ─────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k.startsWith('clawmate-') && k !== STATIC_CACHE && k !== VENDOR_CACHE && k !== API_CACHE)
          .map((k) => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

// ── Fetch — strategy per request type ───────────────────────────────
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only handle same-origin GET requests
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  // API calls — network-first, fallback to cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request, API_CACHE));
    return;
  }

  // Vendor libraries (with version hash in path) — stale-while-revalidate
  if (url.pathname.includes('/vendor/') || url.pathname.includes('/pdfjs/')) {
    event.respondWith(staleWhileRevalidate(request, VENDOR_CACHE));
    return;
  }

  // Static app assets (HTML, CSS, JS with ?v= cache busters) — cache-first
  if (url.pathname.startsWith('/clawmate/')) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }
});

// ── Strategies ──────────────────────────────────────────────────────

// Safe clone: clone a response for caching, returning null if the body
// has already been consumed (avoids "Response body is already used").
function safeClone(response) {
  try {
    if (response.bodyUsed) return null;
    return response.clone();
  } catch (_) {
    return null;
  }
}

// Cache-first: serve from cache, fallback to network (caches fresh copy).
async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const clone = safeClone(response);
      if (clone) {
        const cache = await caches.open(cacheName);
        cache.put(request, clone);
      }
    }
    return response;
  } catch (_) {
    return new Response('Offline — resource not available', { status: 503 });
  }
}

// Network-first: try network, fallback to cache.
async function networkFirst(request, cacheName) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const clone = safeClone(response);
      if (clone) {
        const cache = await caches.open(cacheName);
        cache.put(request, clone);
      }
    }
    return response;
  } catch (_) {
    const cached = await caches.match(request);
    return cached || new Response('Offline — API not available', { status: 503 });
  }
}

// Stale-while-revalidate: serve cached, update cache in background.
async function staleWhileRevalidate(request, cacheName) {
  const cached = await caches.match(request);
  const fetchPromise = fetch(request).then((response) => {
    if (response.ok) {
      const clone = safeClone(response);
      if (clone) {
        caches.open(cacheName).then((cache) => cache.put(request, clone));
      }
    }
    return response;
  }).catch(() => null);
  return cached || fetchPromise || new Response('Offline', { status: 503 });
}

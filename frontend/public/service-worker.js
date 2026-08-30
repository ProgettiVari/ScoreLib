const APP_CACHE = "scorelib-app-v3";
const APP_SHELL = ["/", "/manifest.json", "/scorelib-icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(APP_CACHE)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys
          .filter((key) => key !== APP_CACHE)
          .map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

function isSensitiveRequest(request) {
  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) return true;
  if (request.headers.has("authorization")) return true;
  return false;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  const isPdfFile = url.pathname.includes("/api/pdfs/") && url.pathname.endsWith("/file");
  const isSensitive = isSensitiveRequest(request);

  if (isPdfFile || isSensitive) {
    event.respondWith(
      fetch(request)
        .catch(async () => {
          return (await caches.match(request)) || new Response("Offline", { status: 503, statusText: "Service Unavailable" });
        })
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (!response || response.status >= 400) {
            return caches.match("/") || new Response("Offline", { status: 503, statusText: "Service Unavailable" });
          }
          const copy = response.clone();
          caches.open(APP_CACHE).then((cache) => cache.put("/", copy)).catch(() => {});
          return response;
        })
        .catch(async () => {
          return (await caches.match("/")) || new Response("Offline", { status: 503, statusText: "Service Unavailable" });
        })
    );
    return;
  }

  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(request).then((cached) => cached || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(APP_CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
        }
        return response;
      }).catch(async () => {
        return (await caches.match(request)) || (await caches.match("/")) || new Response("Offline", { status: 503, statusText: "Service Unavailable" });
      }))
    );
  }
});

const GITHUB_PASSED_CARS_URL =
  "https://raw.githubusercontent.com/michaquu/ai-lot-hunter/main/passed_cars.json";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data = event.notification.data || {};
  const targetUrl =
    event.action === "bidcars" && data.bidCarsUrl
      ? data.bidCarsUrl
      : data.url || "/";

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      if (event.action !== "bidcars") {
        for (const client of clientList) {
          if ("focus" in client) {
            return client.focus();
          }
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
    })
  );
});

// Background periodic sync when supported by browser/PWA
self.addEventListener("periodicsync", (event) => {
  if (event.tag === "check-new-cars") {
    event.waitUntil(checkNewCarsInBackground());
  }
});

async function checkNewCarsInBackground() {
  try {
    const res = await fetch(`${GITHUB_PASSED_CARS_URL}?t=${Date.now()}`, {
      cache: "no-store",
    });
    if (!res.ok) return;
    const cars = await res.json();
    if (!Array.isArray(cars) || cars.length === 0) return;

    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of clients) {
      client.postMessage({ type: "NEW_CARS_FETCHED", cars });
    }
  } catch {
    // ignore offline errors
  }
}

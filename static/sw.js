// Clear the old app cache; never cache authenticated pages or transactions.
self.addEventListener('install', event => self.skipWaiting());
self.addEventListener('activate', event => {
  event.waitUntil(Promise.all([caches.delete('noor-foods-v1'), self.clients.claim()]));
});

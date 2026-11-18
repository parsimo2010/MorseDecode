const scope = self.registration.scope;
const cachePrefix = `morsedecode:${scope}:`;
const cacheName = `${cachePrefix}__REVISION__`;
const shell = new URL('index.html', scope).href;
const assets = new Set([
  'index.html', 'manifest.webmanifest', 'icons/app-192.png', 'icons/app-512.png', 'icons/apple.png'
].map(path => new URL(path, scope).href));

self.addEventListener('install', event => {
  event.waitUntil(caches.open(cacheName).then(cache => cache.addAll([...assets])));
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith(cachePrefix) && key !== cacheName)
      .map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const {request} = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  url.search = '';
  const home = request.mode === 'navigate' && (url.href === scope || url.href === shell);
  if (home) {
    event.respondWith(fetch(request).catch(() => caches.match(shell, {cacheName})));
  } else if (assets.has(request.url)) {
    event.respondWith(caches.match(request, {cacheName}).then(cached => cached || fetch(request)));
  }
});

/* Guarda a casca do app (tela, script, ícones) para abrir mesmo sem sinal.
   Dados nunca passam por aqui: /api sempre vai na rede (quem cuida do offline é a fila no app.js). */
const VERSAO = 'estoque-v1';
const CASCA = ['/', '/app.js', '/manifest.webmanifest', '/favicon.png', '/icone-192.png', '/icone.png'];

self.addEventListener('install', (ev) => {
  ev.waitUntil(caches.open(VERSAO).then((c) => c.addAll(CASCA)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (ev) => {
  ev.waitUntil(caches.keys()
    .then((nomes) => Promise.all(nomes.filter((n) => n !== VERSAO).map((n) => caches.delete(n))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (ev) => {
  const url = new URL(ev.request.url);
  if (ev.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) return;            // dados: só rede
  ev.respondWith(
    fetch(ev.request)
      .then((resp) => {
        if (resp.ok) caches.open(VERSAO).then((c) => c.put(ev.request, resp.clone()));
        return resp;
      })
      .catch(() => caches.match(ev.request).then((r) => r || caches.match('/')))
  );
});

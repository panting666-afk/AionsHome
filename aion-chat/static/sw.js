// PWA：生命周期 + Web Push 推送处理
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

// ── 系统推送：收到 push → 弹通知 ──
self.addEventListener('push', (event) => {
  let payload = { title: 'Aion Chat', body: '', data: { url: '/chat' } };
  if (event.data) {
    try {
      const parsed = event.data.json();
      if (parsed && typeof parsed === 'object') {
        payload = {
          title: parsed.title || payload.title,
          body: parsed.body || '',
          data: parsed.data || payload.data,
        };
      } else {
        payload.body = String(parsed);
      }
    } catch (e) {
      payload.body = event.data.text();
    }
  }
  const options = {
    body: payload.body,
    icon: '/public/icon-192.png',
    badge: '/public/icon-192.png',
    data: payload.data,
    vibrate: [120, 60, 120],
    requireInteraction: true,
  };
  event.waitUntil(self.registration.showNotification(payload.title, options));
});

// ── 点通知 → 打开/聚焦对应页面 ──
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/chat';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ('focus' in client) {
          client.focus();
          if ('navigate' in client) {
            try { client.navigate(target); } catch (e) {}
          }
          return;
        }
      }
      return clients.openWindow(target);
    })
  );
});

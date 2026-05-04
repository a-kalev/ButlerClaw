self.addEventListener('push', function(event) {
    let data = { title: 'ButlerClaw', body: 'Your butler has news.', url: '/' };
    try { data = event.data.json(); } catch(e) {}

    event.waitUntil(
        self.registration.showNotification(data.title, {
            body: data.body,
            icon: '/icon.png',
            badge: '/icon.png',
            data: { url: data.url }
        })
    );
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    const url = event.notification.data?.url || '/';
    event.waitUntil(clients.openWindow(url));
});

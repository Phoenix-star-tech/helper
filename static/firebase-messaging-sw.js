importScripts("https://www.gstatic.com/firebasejs/10.11.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.11.0/firebase-messaging-compat.js");

firebase.initializeApp({
  apiKey: "AIzaSyDDgDqFYxjIgUCbjQpoL2hkmqg9BTmGT_k",
    authDomain: "helper-8ec94.firebaseapp.com",
    projectId: "helper-8ec94",
    messagingSenderId: "688597413695",
    appId: "1:688597413695:web:43395b6977f3134169ed8a"
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage(function(payload) {
  console.log("Received background message ", payload);
  const notificationTitle = (payload.notification && payload.notification.title) || (payload.data && payload.data.title) || 'Mr. Helper';
  const notificationOptions = {
    body: (payload.notification && payload.notification.body) || (payload.data && payload.data.body) || '',
    icon: '/static/assets/mrhelperlogo.jpg',
    badge: '/static/notification-icon.png',
    vibrate: [100, 50, 100],
    data: { url: '/notifications' },
    actions: [
      { action: 'open', title: 'Open' }
    ]
  };

  self.registration.showNotification(notificationTitle, notificationOptions);
  // Update app badge if supported
  if (navigator.setAppBadge) {
    try { navigator.setAppBadge(1); } catch(_){}
  }
  // Notify clients (open pages) to update their badge counts
  self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
    for (const client of clients) {
      client.postMessage({ type: 'NEW_NOTIFICATION' });
    }
  });
});

// Fallback for some Android/Chrome setups where 'push' is delivered directly
self.addEventListener('push', function(event) {
  try {
    const data = event.data ? event.data.json() : {};
    const title = (data.notification && data.notification.title) || (data.data && data.data.title) || 'Mr. Helper';
    const body  = (data.notification && data.notification.body)  || (data.data && data.data.body)  || '';
    const options = {
      body,
      icon: '/static/assets/mrhelperlogo.jpg',
      badge: '/static/notification-icon.png',
      vibrate: [100, 50, 100],
      data: { url: (data.fcmOptions && data.fcmOptions.link) || (data.data && data.data.url) || '/notifications' },
      actions: [{ action: 'open', title: 'Open' }]
    };
    event.waitUntil(self.registration.showNotification(title, options));
  } catch (e) {
    // ignore
  }
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const targetUrl = (event.notification && event.notification.data && event.notification.data.url) || '/notifications';
  event.waitUntil((async () => {
    const allClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    let client = allClients.find(c => c.url.includes(targetUrl));
    if (client) {
      client.focus();
    } else {
      self.clients.openWindow(targetUrl);
    }
  })());
});

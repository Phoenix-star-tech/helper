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
  const notificationTitle = payload.notification.title;
  const notificationOptions = {
    body: payload.notification.body,
    icon: '/static/notification-icon.png'
  };

  self.registration.showNotification(notificationTitle, notificationOptions);
});

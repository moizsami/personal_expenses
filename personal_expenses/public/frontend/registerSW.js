if('serviceWorker' in navigator) {window.addEventListener('load', () => {navigator.serviceWorker.register('/assets/personal_expenses/frontend/sw.js', { scope: '/assets/personal_expenses/frontend/' })})}
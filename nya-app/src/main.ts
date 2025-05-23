import '@/styles/normalize.css';
import '@/styles/tailwind.css';

import 'element-plus/theme-chalk/src/message-box.scss';
import 'element-plus/theme-chalk/src/message.scss';
import { createPinia } from 'pinia';
import { createApp } from 'vue';

import App from './App.vue';
import router from './router';

const app = createApp(App);

app.use(createPinia());
app.use(router);

app.mount('#app');

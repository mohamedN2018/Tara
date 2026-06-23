import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { i18n } from "./i18n";
import { setUnauthorizedHandler } from "./lib/api";
import { router } from "./router";
import { useAuthStore } from "./stores/auth";
import { useUiStore } from "./stores/ui";
import "./style.css";

const app = createApp(App);
const pinia = createPinia();

app.use(pinia);
app.use(i18n);
app.use(router);

// Apply persisted theme + locale/direction before first paint.
useUiStore().init();

// When a refresh fails, drop to the login screen.
setUnauthorizedHandler(() => {
  useAuthStore().logout();
  router.push({ name: "login" });
});

app.mount("#app");

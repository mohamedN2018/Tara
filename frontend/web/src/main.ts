import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { i18n } from "./i18n";
import { setUnauthorizedHandler } from "./lib/api";
import { setUpPwa } from "./lib/pwa";
import { jwtClaims, onTokensChangedElsewhere, tokenStore } from "./lib/tokens";
import { router } from "./router";
import { useAuthStore } from "./stores/auth";
import { installFlagSync } from "./stores/flags";
import { useUiStore } from "./stores/ui";
import "./style.css";

const app = createApp(App);
const pinia = createPinia();

app.use(pinia);
app.use(i18n);
app.use(router);

// Apply persisted theme + locale/direction before first paint.
useUiStore().init();
// Feature flags follow the signed-in account (menu gating, useFlag).
installFlagSync();

// When the server rejects the refresh token, drop to the login screen. During
// boot there is no account yet and the router guard routes there by itself.
setUnauthorizedHandler(() => {
  const auth = useAuthStore();
  if (auth.account) void auth.logout({ remote: false });
});

// Another tab logged out or switched account: this one must not keep showing
// the old account's data. A plain token rotation needs nothing, since tokens
// are re-read from storage on every use.
onTokensChangedElsewhere(() => {
  const auth = useAuthStore();
  if (!auth.account) return;
  const owner = jwtClaims(tokenStore.access)?.sub;
  if (!tokenStore.refresh) void auth.logout({ remote: false });
  else if (owner && owner !== auth.account.id) window.location.reload();
});

setUpPwa();
app.mount("#app");

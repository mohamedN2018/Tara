import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig, type Plugin } from "vite";

// Chunks only some people need, left out of the install-time precache: the
// HEIC converter (~1.3 MB, loaded only when someone picks an iPhone photo).
// The service worker still caches them at runtime once they are used.
const LAZY_ONLY_CHUNKS = new Set(["heic2any"]);

// Lists every built asset, so the service worker can cache the whole app shell
// (lazy route chunks included) on install, not only what index.html links.
function precacheList(): Plugin {
  return {
    name: "tara-precache-list",
    apply: "build",
    generateBundle(_options, bundle) {
      const files = Object.entries(bundle)
        .filter(([name]) => name.startsWith("assets/"))
        .filter(([, item]) => !(item.type === "chunk" && LAZY_ONLY_CHUNKS.has(item.name)))
        .map(([name]) => `/${name}`);
      this.emitFile({ type: "asset", fileName: "precache.json", source: JSON.stringify(files) });
    },
  };
}

export default defineConfig({
  plugins: [vue(), precacheList()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    // Split vendors so the framework + icons cache independently of app code
    // and load in parallel (smaller, long-cacheable chunks).
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          // Its own lazy chunk (src/lib/heic.ts imports it dynamically).
          if (id.includes("heic2any")) return "heic2any";
          if (id.includes("lucide")) return "icons";
          if (id.includes("/vue") || id.includes("pinia") || id.includes("@intlify") || id.includes("vue-i18n")) {
            return "vue";
          }
          return "vendor";
        },
      },
    },
  },
  server: {
    host: true,
    port: 5173,
    // Dev proxy: the browser stays same-origin (no CORS); Vite forwards the API
    // and WebSocket to the local gateway (nginx on :8080).
    proxy: {
      "/api": { target: "http://localhost:8080", changeOrigin: true },
      "/ws": { target: "http://localhost:8080", ws: true, changeOrigin: true },
      // Object storage (MinIO) is published on :9000 but its presigned URLs are
      // signed for the internal host `minio:9000`, which the browser can't
      // resolve. Forward /__s3/* to localhost:9000 while keeping the signed
      // Host header so the S3v4 signature still validates. Dev-only.
      "/__s3": {
        target: "http://localhost:9000",
        changeOrigin: false,
        rewrite: (p) => p.replace(/^\/__s3/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("host", "minio:9000");
          });
        },
      },
    },
  },
});

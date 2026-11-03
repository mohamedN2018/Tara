import { defineConfig } from "@playwright/test";

// Needs the running stack (`make up`). The tests share a few accounts and the
// backend rate-limits registration, so they run one at a time.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    launchOptions: { executablePath: process.env.E2E_CHROMIUM_PATH || undefined },
  },
  webServer: {
    command: "npx vite --port 5173 --host 127.0.0.1",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
  },
});

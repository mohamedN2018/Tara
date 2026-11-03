import { chromium, expect, test } from "@playwright/test";

import { API, apiAs, dmWith, pageAs, sharedAccounts } from "./helpers";

// Real WebRTC through the local LiveKit container, with Chromium's fake camera
// and microphone (as the voice-message test does).
test("a voice call is answered on the other side and hanging up clears both", async () => {
  const { a, b } = await sharedAccounts();
  const api = await apiAs(a);
  const config = await api.get(`${API}/calls/config/`);
  const enabled = config.ok() && Boolean((await config.json()).data?.enabled);
  test.skip(!enabled, "calls are off on this stack (LIVEKIT_* keys empty)");

  const id = await dmWith(api, b.id);
  // A call left over from an earlier run would be joined instead of rung.
  const leftover = (await (await api.get(`${API}/conversations/${id}/calls/active/`)).json()).data;
  if (leftover) await api.post(`${API}/calls/${leftover.id}/end/`);

  const browser = await chromium.launch({
    executablePath: process.env.E2E_CHROMIUM_PATH || undefined,
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  });
  try {
    const alice = await pageAs(browser, a);
    const bob = await pageAs(browser, b);
    await alice.context().grantPermissions(["microphone", "camera"]);
    await bob.context().grantPermissions(["microphone", "camera"]);
    await alice.goto(`/messages/${id}`);
    await bob.goto(`/messages/${id}`);
    await expect(alice.getByTestId("call-start-audio")).toBeVisible();
    await bob.waitForTimeout(800); // Let both sockets connect.

    await alice.getByTestId("call-start-audio").click();
    await expect(alice.getByTestId("call-overlay")).toHaveAttribute("data-phase", /outgoing|connecting/);

    const incoming = bob.getByTestId("call-incoming");
    await expect(incoming).toBeVisible();
    // The focus trap moved focus into the sheet (its first button).
    await expect(bob.getByTestId("call-decline")).toBeFocused();
    await bob.getByTestId("call-accept").click();

    await expect(bob.getByTestId("call-in-progress")).toBeVisible({ timeout: 30_000 });
    await expect(alice.getByTestId("call-in-progress")).toBeVisible({ timeout: 30_000 });
    // Escape never hangs up.
    await bob.keyboard.press("Escape");
    await expect(bob.getByTestId("call-pill")).toBeVisible();
    await expect(alice.getByTestId("call-in-progress")).toBeVisible();

    await alice.getByTestId("call-hangup").click();
    await expect(bob.getByTestId("call-pill")).toBeHidden({ timeout: 15_000 });
    await expect(bob.getByTestId("call-in-progress")).toBeHidden();
    await expect(alice.getByTestId("call-in-progress")).toBeHidden();
    // The call log lands in the conversation for both.
    await expect(bob.getByTestId("call-log").last()).toBeVisible({ timeout: 15_000 });
  } finally {
    await browser.close();
  }
});

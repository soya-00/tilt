import { afterEach, describe, expect, it } from "vitest";

import { bridge, dismiss, inShell, isCaptureWindow, onCaptured } from "./shell";

function setLocation(search: string) {
  // jsdom allows replacing the URL, which is the only part of `location` these
  // helpers read.
  window.history.replaceState({}, "", `/${search}`);
}

afterEach(() => {
  delete window.__TILT__;
  setLocation("");
});

describe("shell detection", () => {
  it("reports no shell in a plain browser", () => {
    expect(inShell()).toBe(false);
    expect(bridge()).toBeUndefined();
  });

  it("reports a shell once the bridge is injected", () => {
    window.__TILT__ = { shell: "tauri", baseUrl: "http://127.0.0.1:51234", token: "t" };
    expect(inShell()).toBe(true);
    expect(bridge()?.baseUrl).toBe("http://127.0.0.1:51234");
  });

  it("does not mistake a bridge carrying only an error for a working shell", () => {
    // The shell injects this when the core failed to start. It is still a
    // shell — the UI needs the reason, not a browser fallback.
    window.__TILT__ = { shell: "tauri", error: "The Tilt core did not start in time." };
    expect(inShell()).toBe(true);
    expect(bridge()?.baseUrl).toBeUndefined();
  });
});

describe("which window this is", () => {
  it("is the journal by default", () => {
    expect(isCaptureWindow()).toBe(false);
  });

  it("is the capture panel when the query string says so", () => {
    setLocation("?capture=1");
    expect(isCaptureWindow()).toBe(true);
  });
});

describe("outside the shell", () => {
  it("dismissing is a no-op rather than an error", async () => {
    // The same view renders in a browser during development; calling into a
    // Tauri API that is not there would break it outright.
    await expect(dismiss()).resolves.toBeUndefined();
  });

  it("subscribing returns an unsubscribe that is safe to call", () => {
    const stop = onCaptured(() => {
      throw new Error("must never fire without a shell");
    });
    expect(() => stop()).not.toThrow();
  });
});

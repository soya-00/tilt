/** The desktop shell, when there is one.
 *
 * Tilt runs in two places: inside the Tauri shell, and in a plain browser
 * against `npm run dev`. Everything here answers the same question — is there a
 * shell to talk to — and does nothing at all when the answer is no.
 *
 * The Tauri API is imported dynamically rather than at module scope. It reaches
 * for globals the shell injects, so a static import would pull it into the
 * browser bundle and into every test run for the sake of code that can never
 * execute there.
 */

export interface ShellBridge {
  /** Where the Python core is listening. Absent in a browser. */
  baseUrl?: string;
  /** Per-launch bearer token. Never persisted, on either side. */
  token?: string;
  /** Present only under the shell. */
  shell?: string;
  /** Why the core failed to start, if it did. */
  error?: string;
}

/** Broadcast when a thought is captured, so the journal window catches up. */
export const CAPTURED = "tilt://captured";

export function bridge(): ShellBridge | undefined {
  return typeof window === "undefined" ? undefined : window.__TILT__;
}

export function inShell(): boolean {
  return Boolean(bridge()?.shell);
}

/** The small always-on-top panel, distinguished by its query string. */
export function isCaptureWindow(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).has("capture");
}

/**
 * Dismiss — hide, never close. A closed window would have to be rebuilt on the
 * next ⌥Space, and the delay is exactly what quick capture cannot afford.
 */
export async function dismiss(): Promise<void> {
  if (!inShell()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().hide();
}

/**
 * Open a link in the real browser.
 *
 * Under the shell a plain `target="_blank"` does nothing at all: Tauri does not
 * create the window, and the app's CSP has no `navigate-to`. That is a link
 * that works perfectly in `npm run dev` and is silently dead in the shipped
 * app, which is the worst shape a bug can take.
 *
 * The plugin command is invoked by name rather than through
 * `@tauri-apps/plugin-opener`. `@tauri-apps/api` is already a dependency and
 * this needs exactly one call, so the npm package would be a second copy of the
 * same thing.
 */
export async function openExternal(url: string): Promise<void> {
  if (!/^https?:\/\//i.test(url)) return;
  if (!inShell()) {
    window.open(url, "_blank", "noopener,noreferrer");
    return;
  }
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("plugin:opener|open_url", { url });
}

export async function announceCapture(): Promise<void> {
  if (!inShell()) return;
  const { emit } = await import("@tauri-apps/api/event");
  await emit(CAPTURED);
}

/** Returns an unsubscribe function, or a no-op outside the shell. */
export function onCaptured(handler: () => void): () => void {
  if (!inShell()) return () => {};

  let stop: (() => void) | undefined;
  let cancelled = false;

  void import("@tauri-apps/api/event").then(async ({ listen }) => {
    const unlisten = await listen(CAPTURED, handler);
    // The component may well have unmounted while the import was in flight.
    if (cancelled) unlisten();
    else stop = unlisten;
  });

  return () => {
    cancelled = true;
    stop?.();
  };
}

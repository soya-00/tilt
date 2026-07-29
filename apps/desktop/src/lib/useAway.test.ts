import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { describe as describeActivity, useAway } from "./useAway";

const KEY = "tilt:last-seen";

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

afterEach(() => {
  window.localStorage.clear();
});

function activity(filed: number, connected: number) {
  return vi
    .spyOn(api, "activity")
    .mockResolvedValue({ since: "2026-07-01T00:00:00Z", filed, connected });
}

describe("useAway", () => {
  it("says nothing on a first launch", async () => {
    const spy = activity(3, 2);

    const { result } = renderHook(() => useAway());

    // No previous visit means there is no absence to report — asking the
    // service would describe the entire history of the journal as "away".
    expect(spy).not.toHaveBeenCalled();
    expect(result.current.activity).toBeNull();
    expect(window.localStorage.getItem(KEY)).not.toBeNull();
  });

  it("reports what happened since the last visit", async () => {
    window.localStorage.setItem(KEY, "2026-07-01T00:00:00Z");
    activity(3, 2);

    const { result } = renderHook(() => useAway());

    await waitFor(() => expect(result.current.activity).not.toBeNull());
    expect(result.current.activity).toMatchObject({ filed: 3, connected: 2 });
  });

  it("stays quiet when nothing happened", async () => {
    window.localStorage.setItem(KEY, "2026-07-01T00:00:00Z");
    activity(0, 0);

    const { result } = renderHook(() => useAway());

    await waitFor(() => expect(api.activity).toHaveBeenCalled());
    expect(result.current.activity).toBeNull();
  });

  it("stamps the visit before asking, so a reload is not a new absence", async () => {
    window.localStorage.setItem(KEY, "2026-07-01T00:00:00Z");
    const spy = activity(3, 0);

    renderHook(() => useAway());
    const stamped = window.localStorage.getItem(KEY);
    renderHook(() => useAway());

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy.mock.calls[0]?.[0]).toBe("2026-07-01T00:00:00Z");
    expect(spy.mock.calls[1]?.[0]).toBe(stamped);
  });

  it("survives a service that is not answering", async () => {
    window.localStorage.setItem(KEY, "2026-07-01T00:00:00Z");
    vi.spyOn(api, "activity").mockRejectedValue(new Error("down"));

    const { result } = renderHook(() => useAway());

    await waitFor(() => expect(api.activity).toHaveBeenCalled());
    expect(result.current.activity).toBeNull();
  });

  it("survives localStorage being unavailable", () => {
    // Locked-down webviews throw on access rather than returning null, and a
    // missing convenience must never break the journal.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });

    expect(() => renderHook(() => useAway())).not.toThrow();
  });
});

describe("describe", () => {
  it("names both halves", () => {
    expect(describeActivity({ since: "", filed: 3, connected: 2 })).toBe(
      "3 filed, 2 connections while you were away",
    );
  });

  it("does not pluralise a single connection", () => {
    expect(describeActivity({ since: "", filed: 0, connected: 1 })).toBe(
      "1 connection while you were away",
    );
  });
});

import "@testing-library/jest-dom/vitest";

// jsdom implements neither of these, and both are used by the layout code.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

window.requestAnimationFrame = (cb: FrameRequestCallback): number =>
  setTimeout(() => cb(performance.now()), 0) as unknown as number;

// And its other half. Without this, a component that cancels its animation on
// unmount does not actually stop, and the callback fires after the environment
// has been torn down — reported as an unrelated crash in whatever ran next.
window.cancelAnimationFrame = (handle: number): void => clearTimeout(handle);

// jsdom has no 2D canvas and logs a "not implemented" trace on every call,
// which the constellation makes once a frame. Returning null is what a real
// browser does for a context it cannot provide, and the painter already treats
// that as "nothing to draw on" — so the layout still runs, silently.
window.HTMLCanvasElement.prototype.getContext = () => null;

Element.prototype.scrollIntoView = () => {};
window.HTMLElement.prototype.scrollTo = () => {};

// jsdom 25 ships Blob without the text() reader that every real browser has
// had since 2019. The composer uses it to preview a dropped text file.
if (typeof Blob.prototype.text !== "function") {
  Blob.prototype.text = function (this: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(this);
    });
  };
}

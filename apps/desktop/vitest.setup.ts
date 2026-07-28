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

Element.prototype.scrollIntoView = () => {};
window.HTMLElement.prototype.scrollTo = () => {};

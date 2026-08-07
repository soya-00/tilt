import react from "@vitejs/plugin-react";
// vitest's defineConfig is the vite one widened with the `test` key.
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    // Off in what ships. A built bundle is what the container serves to a
    // visitor, and a source map hands them the whole original TypeScript with
    // it. This setting governs `vite build` only — `npm run dev` serves its own
    // maps and is unaffected, so debugging while writing code is unchanged.
    sourcemap: false,
    target: "es2022",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    restoreMocks: true,
  },
});

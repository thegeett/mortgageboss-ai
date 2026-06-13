import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // The React plugin transforms JSX in component test files (.tsx) — LP-46.
  plugins: [react()],
  test: {
    // Default to node (fast) for lib/unit tests; component tests opt into jsdom
    // per-file via a `// @vitest-environment jsdom` docblock (LP-46).
    environment: "node",
    include: ["**/*.test.ts", "**/*.test.tsx"],
    exclude: ["node_modules", ".next"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});

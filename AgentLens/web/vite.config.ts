import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: path.resolve(__dirname, "../src/agentlens/web_assets"),
    emptyOutDir: false,
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5757",
      "/healthz": "http://127.0.0.1:5757",
      "/openapi.json": "http://127.0.0.1:5757",
      "/docs": "http://127.0.0.1:5757",
    },
  },
  test: {
    environment: "jsdom",
    exclude: ["tests/e2e/**", "node_modules/**", "dist/**"],
    setupFiles: ["./src/test-setup.ts"],
    globals: true,
  },
});

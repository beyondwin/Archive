import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.PLAYWRIGHT_PORT ?? 6173);
const baseURL = `http://127.0.0.1:${port}`;
const python = process.env.AGENTLENS_PYTHON ?? ".venv/bin/python";

export default defineConfig({
  testDir: "./tests/e2e",
  outputDir: "./tests/e2e/test-results",
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: true,
  reporter: process.env.CI ? "dot" : "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  webServer: {
    command: `npm run build && cd .. && ${python} -m agentlens.cli serve --demo --host 127.0.0.1 --port ${port}`,
    url: `${baseURL}/healthz`,
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});

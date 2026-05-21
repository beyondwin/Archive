import { readdirSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";

const assetsDir = resolve(process.cwd(), "../src/agentlens/web_assets");

for (const entry of readdirSync(assetsDir)) {
  if (entry === "__init__.py") continue;
  rmSync(join(assetsDir, entry), { recursive: true, force: true });
}

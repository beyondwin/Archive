import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

export interface CacheKey {
  sourcePath: string;
  sourceSha256: string;
  extractorVersion: string;
}

export class ArtifactCache {
  constructor(private readonly root: string) {}

  pathFor(key: CacheKey): string {
    const digest = createHash("sha256")
      .update(`${key.sourcePath}|${key.sourceSha256}|${key.extractorVersion}`)
      .digest("hex");
    return join(this.root, `${digest}.json`);
  }

  async read(key: CacheKey): Promise<unknown | null> {
    const path = this.pathFor(key);
    try {
      const raw = await readFile(path, "utf8");
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  async write(key: CacheKey, value: unknown): Promise<void> {
    const path = this.pathFor(key);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, JSON.stringify(value, null, 2), "utf8");
  }
}

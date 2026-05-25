import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { normalizeProcessOutput } from "../src/processAdapters";

const fixtureDir = join(import.meta.dir, "fixtures");

function readFixture(name: string): string {
  return readFileSync(join(fixtureDir, name), "utf8");
}

describe("envelope-level usage extraction (D-08)", () => {
  test("extracts top-level usage from a claude --output-format json envelope", () => {
    const stdout = readFixture("claude_task_3_narrative_then_json.stdout.txt");
    const result = normalizeProcessOutput("claude", "task_3_fixture_preparation_and_gradle_injection", "candidate_task_3", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.worker.status).toBe("completed");
    expect(result.metadata?.usage).toEqual({
      input_tokens: 142000,
      output_tokens: 8200,
      cached_read_tokens: 96000,
      cached_write_tokens: 0
    });
    expect(result.metadata?.usage_source).toBe("provider_json");
  });

  test("envelope-level usage wins over a divergent evidence.usage block", () => {
    const workerBody = {
      schema: "runway.worker_result.v1",
      task_id: "task_envelope_wins",
      candidate_id: "candidate_task_envelope_wins",
      status: "completed",
      changed_files: ["a.ts"],
      summary: "envelope wins",
      evidence: {
        usage: { input_tokens: 1, output_tokens: 2, cached_read_tokens: 3, cached_write_tokens: 4 }
      }
    };
    const stdout = JSON.stringify({
      type: "result",
      subtype: "success",
      result: `Worker result:\n\n\`\`\`json\n${JSON.stringify(workerBody)}\n\`\`\`\n`,
      usage: {
        input_tokens: 1000,
        output_tokens: 200,
        cache_read_input_tokens: 50,
        cache_creation_input_tokens: 25
      },
      modelUsage: { "claude-opus-4-7": { duration_ms: 100 } }
    });
    const result = normalizeProcessOutput("claude", "task_envelope_wins", "candidate_task_envelope_wins", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.metadata?.usage).toEqual({
      input_tokens: 1000,
      output_tokens: 200,
      cached_read_tokens: 50,
      cached_write_tokens: 25
    });
    expect(result.metadata?.usage_source).toBe("provider_json");
  });

  test("falls back to evidence.usage when envelope omits usage", () => {
    const workerBody = {
      schema: "runway.worker_result.v1",
      task_id: "task_evidence_fallback",
      candidate_id: "candidate_task_evidence_fallback",
      status: "completed",
      changed_files: ["b.ts"],
      summary: "evidence fallback",
      evidence: {
        usage: { input_tokens: 11, output_tokens: 7, cached_read_tokens: 0, cached_write_tokens: 0 },
        usage_source: "provider_json"
      }
    };
    const stdout = JSON.stringify({
      type: "result",
      result: `\`\`\`json\n${JSON.stringify(workerBody)}\n\`\`\``
    });
    const result = normalizeProcessOutput("claude", "task_evidence_fallback", "candidate_task_evidence_fallback", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.metadata?.usage).toEqual({
      input_tokens: 11,
      output_tokens: 7,
      cached_read_tokens: 0,
      cached_write_tokens: 0
    });
    expect(result.metadata?.usage_source).toBe("provider_json");
  });

  test("usage missing from both envelope and evidence yields usage=null and usage_source='unknown'", () => {
    const workerBody = {
      schema: "runway.worker_result.v1",
      task_id: "task_no_usage",
      candidate_id: "candidate_task_no_usage",
      status: "completed",
      changed_files: ["c.ts"],
      summary: "no usage anywhere",
      evidence: {}
    };
    const stdout = JSON.stringify({
      type: "result",
      result: `\`\`\`json\n${JSON.stringify(workerBody)}\n\`\`\``
    });
    const result = normalizeProcessOutput("claude", "task_no_usage", "candidate_task_no_usage", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.metadata?.usage).toBeNull();
    expect(result.metadata?.usage_source).toBe("unknown");
  });

  test("extracts actual_model from envelope modelUsage when worker self-report is missing", () => {
    const workerBody = {
      schema: "runway.worker_result.v1",
      task_id: "task_model_envelope",
      candidate_id: "candidate_task_model_envelope",
      status: "completed",
      changed_files: ["d.ts"],
      summary: "model from envelope",
      evidence: {}
    };
    const stdout = JSON.stringify({
      type: "result",
      result: `\`\`\`json\n${JSON.stringify(workerBody)}\n\`\`\``,
      usage: {
        input_tokens: 5,
        output_tokens: 3,
        cache_read_input_tokens: 0,
        cache_creation_input_tokens: 0
      },
      modelUsage: { "claude-opus-4-7": { duration_ms: 100 } }
    });
    const result = normalizeProcessOutput("claude", "task_model_envelope", "candidate_task_model_envelope", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.metadata?.actual_model.model).toBe("claude-opus-4-7");
    expect(result.metadata?.actual_model.source).toBe("provider_json");
  });

  test("worker_result actual_model takes precedence over envelope modelUsage", () => {
    const workerBody = {
      schema: "runway.worker_result.v1",
      task_id: "task_model_worker",
      candidate_id: "candidate_task_model_worker",
      status: "completed",
      changed_files: ["e.ts"],
      summary: "model from worker",
      evidence: {
        actual_model: { model: "worker-self-reported", reasoning: "high", source: "provider_json" }
      }
    };
    const stdout = JSON.stringify({
      type: "result",
      result: `\`\`\`json\n${JSON.stringify(workerBody)}\n\`\`\``,
      modelUsage: { "claude-opus-4-7": { duration_ms: 100 } }
    });
    const result = normalizeProcessOutput("claude", "task_model_worker", "candidate_task_model_worker", {
      exitCode: 0,
      stdout,
      stderr: "",
      timedOut: false
    });
    expect(result.metadata?.actual_model.model).toBe("worker-self-reported");
    expect(result.metadata?.actual_model.reasoning).toBe("high");
  });

  test("system.init.model from a JSONL stream overrides envelope modelUsage", () => {
    const workerBody = {
      schema: "runway.worker_result.v1",
      task_id: "task_system_init",
      candidate_id: "candidate_task_system_init",
      status: "completed",
      changed_files: ["f.ts"],
      summary: "system.init wins",
      evidence: {}
    };
    const lines = [
      JSON.stringify({
        type: "system",
        subtype: "init",
        session_id: "session_42",
        model: "claude-opus-4-7"
      }),
      JSON.stringify({
        type: "result",
        result: `\`\`\`json\n${JSON.stringify(workerBody)}\n\`\`\``,
        usage: { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 0, cache_creation_input_tokens: 0 },
        modelUsage: { "claude-sonnet-stale": { duration_ms: 100 } }
      })
    ].join("\n");
    const result = normalizeProcessOutput("claude", "task_system_init", "candidate_task_system_init", {
      exitCode: 0,
      stdout: lines,
      stderr: "",
      timedOut: false
    });
    expect(result.metadata?.actual_model.model).toBe("claude-opus-4-7");
    expect(result.metadata?.actual_model.source).toBe("provider_json");
    expect(result.metadata?.session_id).toBe("session_42");
  });

  test("direct worker_result without envelope still extracts evidence.usage", () => {
    const result = normalizeProcessOutput("codex", "task_direct", "candidate_task_direct", {
      exitCode: 0,
      stdout: JSON.stringify({
        schema: "runway.worker_result.v1",
        task_id: "task_direct",
        candidate_id: "candidate_task_direct",
        status: "completed",
        changed_files: [],
        summary: "direct",
        evidence: {
          actual_model: { model: "gpt-5.5", reasoning: "high", source: "provider_json" },
          usage: { input_tokens: 10, output_tokens: 3, cached_read_tokens: 2, cached_write_tokens: 0 },
          usage_source: "provider_json"
        }
      }),
      stderr: ""
    });
    expect(result.metadata?.usage?.input_tokens).toBe(10);
    expect(result.metadata?.usage_source).toBe("provider_json");
    expect(result.metadata?.actual_model.model).toBe("gpt-5.5");
  });
});

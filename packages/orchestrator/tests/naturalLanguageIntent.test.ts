import { describe, expect, test } from "bun:test";
import { intentToCommand, parseNaturalLanguageIntent } from "../src";

describe("natural language Waygent intent", () => {
  test("maps Korean and English run intents", () => {
    expect(intentToCommand(parseNaturalLanguageIntent("최근 승인된 플랜 실행해줘"))).toBe("waygent run --latest");
    expect(intentToCommand(parseNaturalLanguageIntent("bun rust platform Codex로 멀티에이전트 실행해줘"))).toContain("--provider codex");
  });

  test("maps explain and apply", () => {
    expect(intentToCommand(parseNaturalLanguageIntent("마지막 실행 왜 막혔는지 설명해줘"))).toBe("waygent explain --last");
    expect(intentToCommand(parseNaturalLanguageIntent("검증 통과한 것만 적용해줘"))).toBe("waygent apply --last");
  });

  test("recognizes sonnet and haiku model names", () => {
    const sonnet = parseNaturalLanguageIntent("sonnet으로 실행해줘");
    expect(sonnet.main_model).toBe("sonnet");
    expect(sonnet.subagent_model).toBe("sonnet");
    const haiku = parseNaturalLanguageIntent("haiku로 빠르게 돌려줘");
    expect(haiku.main_model).toBe("haiku");
    expect(haiku.subagent_model).toBe("haiku");
  });

  test("splits main and subagent models when both mentioned", () => {
    const intent = parseNaturalLanguageIntent("main은 opus, subagent는 sonnet으로 실행해줘");
    expect(intent.main_model).toBe("opus");
    expect(intent.subagent_model).toBe("sonnet");
  });
});

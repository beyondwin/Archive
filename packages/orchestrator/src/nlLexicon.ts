export const NL_LEXICON_VERSION = "waygent.nl_lexicon.v1";

export const nlLexicon = {
  explain: ["왜", "blocked", "explain"],
  resume: ["resume", "재개"],
  apply: ["apply", "적용"],
  status: ["status", "상태"],
  events: ["event", "이벤트"],
  latest: ["latest", "최근", "승인"],
  provider: {
    claude: ["claude", "opus"],
    codex: ["codex"]
  },
  execution_mode: {
    "single-agent": ["single", "단일"],
    "multi-agent": ["multi", "멀티"]
  }
} as const;

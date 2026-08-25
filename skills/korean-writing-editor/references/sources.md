# Evidence Register

Authoritative links, evidence class, and reuse limits for
`korean-writing-editor`. This skill cites these sources; it does not copy
their corpora, datasets, or rule lists. Checked dates are `2026-08-22`.

## Sources

| Source | Evidence class | Used for | Not proof of | Checked | Reuse boundary |
| --- | --- | --- | --- | --- | --- |
| [Korean language norms](https://www.korean.go.kr/kornorms/m/m_regltn.do) | Normative | spelling, spacing, punctuation, standard language, loanword, romanization | a universal prose style | 2026-08-22 | Cite and apply locally; do not copy the regulation text. Permitted alternatives are not errors. |
| [NIKL 2024 correction-corpus study](https://www.korean.go.kr/front/reportData/reportDataView.do?mn_id=45&pageIndex=5&report_seq=1184&searchOrder=) | Empirical | correction categories and accepted-form cautions | current model quality | 2026-08-22 | Government report; cite categories only. Corpus not copied. |
| [NIKL 2025 correction-support study](https://www.korean.go.kr/front/reportData/reportDataView.do?mn_id=207&pageIndex=1&report_seq=1226&searchOrder=years) | Empirical | factuality, evidence fidelity, clarity, fluency categories | open-genre voice preservation | 2026-08-22 | Government report; cite categories only. Corpus not copied. |
| [KAGAS](https://aclanthology.org/2023.acl-long.371/) | Empirical | Korean GEC edit types and precision focus | document-level meaning or voice | 2026-08-22 | ACL paper; cite only. Dataset not copied. |
| [StyleKQC](https://aclanthology.org/2022.lrec-1.771.pdf) | Empirical | separate style and content-preservation axes | all Korean genres | 2026-08-22 | LREC paper; cite only. Dataset not copied. |
| [NIST AI 600-1](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf) | Risk guidance | fabrication, homogenization, non-English variance, automation bias | Korean grammar rules | 2026-08-22 | Cite and link; not a Korean grammar source. |
| [KatFishNet](https://aclanthology.org/2025.acl-long.1030/) | Detector research | why detector signals are diagnostic only | better writing or human authorship | 2026-08-22 | Cite only. Do not reverse detector signals or copy models or data. |
| [Shared report](https://chatgpt.com/share/6a89a698-c790-83ee-8d20-7fe092d2badc) | Design input | source-first and minimal-edit framing | live generalization | 2026-08-22 | Design framing only. Attached package, fixtures, and acceptance counts were not copied. |

## Related Projects

Inspected on 2026-08-22 as design references, not dependencies. No code,
corpus, or rule list was copied. Licenses below are the upstream LICENSE files
at the pinned commits.

| Project | Pinned commit | License | Verified observation | Design use | Checked | Reuse boundary |
| --- | --- | --- | --- | --- | --- | --- |
| [im-not-ai](https://github.com/epoko77-ai/im-not-ai) | [`177e64539cd8b4faf41a2d8c6d187c33d57f79f4`](https://github.com/epoko77-ai/im-not-ai/tree/177e64539cd8b4faf41a2d8c6d187c33d57f79f4) | MIT at pinned [LICENSE](https://github.com/epoko77-ai/im-not-ai/blob/177e64539cd8b4faf41a2d8c6d187c33d57f79f4/LICENSE); not copied | Offline suite: 235 passed, 1 skipped; 35 install-flag subtests passed. Live Claude tests ran only because `claude` existed and produced 18 authentication failures. | Adopt local problem detection, minimal-edit thinking, and explicit opt-in live tests. Reject detector optimization and the full pipeline. | 2026-08-22 | Upstream pointer only. No code, taxonomy, or corpus copied. |
| [Patina](https://github.com/devswha/patina) | [`25f411ee3d06e000d4cdc87e5d4dd398c2bd8f67`](https://github.com/devswha/patina/tree/25f411ee3d06e000d4cdc87e5d4dd398c2bd8f67) | MIT at pinned [LICENSE](https://github.com/devswha/patina/blob/25f411ee3d06e000d4cdc87e5d4dd398c2bd8f67/LICENSE); not copied | 1,685 of 1,686 local tests passed. One macOS temp-path alias duplicated config loading. Study texts are not public. | Adopt candidate rollback and truthful failure reporting. Do not claim its study proves this skill. | 2026-08-22 | Upstream pointer only. No code, pattern catalog, or study texts copied. |
| [personal-humanizer-maker](https://github.com/TaewoooPark/personal-humanizer-maker) | [`86b987d2c609e41854a43214c8868718b5b6acea`](https://github.com/TaewoooPark/personal-humanizer-maker/tree/86b987d2c609e41854a43214c8868718b5b6acea) | MIT at pinned [LICENSE](https://github.com/TaewoooPark/personal-humanizer-maker/blob/86b987d2c609e41854a43214c8868718b5b6acea/LICENSE); not copied | Four local test files passed (profile construction and round trips, not live rewrite generalization). A Korean example added worldview content. | Future voice-profile idea only. No voice learning in v1. | 2026-08-22 | Upstream pointer only. No code, profiles, or examples copied. |

These projects are not runtime dependencies and were not cloned into this
skill.

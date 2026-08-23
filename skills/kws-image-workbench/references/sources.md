# Evidence And Source Register

## Source Classes

This register separates official product documentation, pinned repository
research, provider-boundary evidence, and benchmark categories. It is a set of
locators, not runtime dependencies, release gates, compatibility claims, or
instructions to execute. All entries were checked on `2026-08-23`.

## Primary OpenAI Sources

| Source | Revision | License | Checked | Used for | Rejected boundary | Refresh trigger |
| --- | --- | --- | --- | --- | --- | --- |
| [Image generation guide](https://developers.openai.com/api/docs/guides/image-generation) | live official page | not applicable | 2026-08-23 | bundled capability boundary | do not add a provider client or copy model parameters | bundled capability or guide changes |
| [GPT Image prompting guide](https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide) | live official page | not applicable | 2026-08-23 | prompt structure context | copied prompt corpus | material guidance change |
| [Content provenance](https://developers.openai.com/api/docs/guides/content-provenance) | live official page | not applicable | 2026-08-23 | provenance limitation | provenance as truth or rights proof | provenance guidance change |
| [Build skills](https://learn.chatgpt.com/docs/build-skills) | live official page | not applicable | 2026-08-23 | skill packaging context | cross-runtime claim | packaging guidance change |

## Related Projects

`awesome-gpt-image-2` is the supplied upstream research anchor. The other seven
rows are related projects. Each license value was read from the linked license
file at its immutable revision, read-only, before this register was written.

| Source | Revision | License | Checked | Used for | Rejected boundary | Refresh trigger |
| --- | --- | --- | --- | --- | --- | --- |
| [awesome-gpt-image-2](https://github.com/freestylefly/awesome-gpt-image-2/tree/3a9c63baa03e6bbe2f28c89a2654cf9845466646) | `3a9c63baa03e6bbe2f28c89a2654cf9845466646` | [MIT](https://github.com/freestylefly/awesome-gpt-image-2/blob/3a9c63baa03e6bbe2f28c89a2654cf9845466646/LICENSE) | 2026-08-23 | analyzed snapshot; compact artifact fields | copied gallery, prompts, examples, Agent instructions | approved evidence refresh |
| [GPT-Image2-Skill](https://github.com/wuyoscar/GPT-Image2-Skill/tree/068dd9e24aadc8731e46f38548ca4dcd94515d35) | `068dd9e24aadc8731e46f38548ca4dcd94515d35` | [MIT](https://github.com/wuyoscar/GPT-Image2-Skill/blob/068dd9e24aadc8731e46f38548ca4dcd94515d35/LICENSE) | 2026-08-23 | bounded intent-to-execution pattern | model, CLI, API-key coupling and gallery | approved evidence refresh |
| [ComfyUI](https://github.com/Comfy-Org/ComfyUI/tree/82f839f5e737d8bfce480872ba05e5a430f2526f) | `82f839f5e737d8bfce480872ba05e5a430f2526f` | [GPL-3.0-only](https://github.com/Comfy-Org/ComfyUI/blob/82f839f5e737d8bfce480872ba05e5a430f2526f/LICENSE) | 2026-08-23 | workflow/history concepts | node runtime, model management, UI dependency | approved evidence refresh |
| [InvokeAI](https://github.com/invoke-ai/InvokeAI/tree/e431d249e09290b241c45ad340addebc1bfc7737) | `e431d249e09290b241c45ad340addebc1bfc7737` | [Apache-2.0](https://github.com/invoke-ai/InvokeAI/blob/e431d249e09290b241c45ad340addebc1bfc7737/LICENSE) | 2026-08-23 | recallable settings/edit history concept | production graph engine dependency | approved evidence refresh |
| [Diffusers](https://github.com/huggingface/diffusers/tree/58eb52c0803ea9af3abec60841c2a093bdf1f951) | `58eb52c0803ea9af3abec60841c2a093bdf1f951` | [Apache-2.0](https://github.com/huggingface/diffusers/blob/58eb52c0803ea9af3abec60841c2a093bdf1f951/LICENSE) | 2026-08-23 | explicit model revision concept | GPU/model download and per-model license scope | approved evidence refresh |
| [image-prompt-library](https://github.com/EddieTYP/image-prompt-library/tree/c9e8d3547a9556bcba4dbbfab17e24680f0747db) | `c9e8d3547a9556bcba4dbbfab17e24680f0747db` | [AGPL-3.0-only](https://github.com/EddieTYP/image-prompt-library/blob/c9e8d3547a9556bcba4dbbfab17e24680f0747db/LICENSE) | 2026-08-23 | source/variant/model/note separation | code, database, UI, prompt reuse | approved evidence refresh |
| [promptfoo](https://github.com/promptfoo/promptfoo/tree/679e7ecb64a2e09042b009b549b81dc0d0b983bb) | `679e7ecb64a2e09042b009b549b81dc0d0b983bb` | [MIT](https://github.com/promptfoo/promptfoo/blob/679e7ecb64a2e09042b009b549b81dc0d0b983bb/LICENSE) | 2026-08-23 | explicit test matrix/report pattern | complete visual-quality judge claim | approved evidence refresh |
| [c2pa-rs](https://github.com/contentauth/c2pa-rs/tree/24d17555beafb70c15e1e1e4054ac3c06fbba1c0) | `24d17555beafb70c15e1e1e4054ac3c06fbba1c0` | [Apache-2.0 OR MIT](https://github.com/contentauth/c2pa-rs/blob/24d17555beafb70c15e1e1e4054ac3c06fbba1c0/LICENSE-APACHE) | 2026-08-23 | optional media-history concept | provenance as rights or QA replacement | approved evidence refresh |

## Provider Boundaries

| Source | Revision | License | Checked | Used for | Rejected boundary | Refresh trigger |
| --- | --- | --- | --- | --- | --- | --- |
| [Google Gemini image generation](https://ai.google.dev/gemini-api/docs/generate-content/image-generation) | live official page | not applicable | 2026-08-23 | provider admission evidence category | runtime dependency or quality ranking | separately approved provider review |
| [Adobe Firefly image generation](https://developer.adobe.com/firefly-services/docs/firefly-api/guides/how-tos/cm-generate-image/feature-guide) | live official page | not applicable | 2026-08-23 | provider admission evidence category | runtime dependency or quality ranking | separately approved provider review |
| [Ideogram prompt-based editing](https://developer.ideogram.ai/api-reference/api-reference/edit-with-prompt) | live official page | not applicable | 2026-08-23 | provider admission evidence category | runtime dependency or quality ranking | separately approved provider review |
| [Midjourney community and automation guidelines](https://docs.midjourney.com/hc/en-us/articles/32013696484109-Community-Guidelines) | live official page | not applicable | 2026-08-23 | automation-boundary evidence category | v1 automation or API assumption | separately approved provider review |

## Evaluation References

| Source | Revision | License | Checked | Used for | Rejected boundary | Refresh trigger |
| --- | --- | --- | --- | --- | --- | --- |
| [GenEval](https://arxiv.org/abs/2310.11513) | arXiv:2310.11513 | not applicable | 2026-08-23 | object/count/color/position fixture category | release gate or Korean typography proof | evaluation-program approval |
| [T2I-CompBench](https://arxiv.org/abs/2307.06350) | arXiv:2307.06350 | not applicable | 2026-08-23 | attribute/composition fixture category | release gate or project-fit proof | evaluation-program approval |
| [DPG-Bench](https://arxiv.org/abs/2403.05135) | arXiv:2403.05135 | not applicable | 2026-08-23 | dense prompt-following category | release gate or rights proof | evaluation-program approval |
| [ImgEdit-Bench](https://arxiv.org/abs/2505.20275) | arXiv:2505.20275 | not applicable | 2026-08-23 | edit/preservation category | release gate or live quality proof | evaluation-program approval |

## Refresh Triggers

Refresh an entry only for an approved source or behavior review, a material
official-documentation change, or a provider-admission decision. Re-read an
external repository's license at the new immutable revision; use `unknown` if
that revision has no identifiable license rather than infer one from a branch
or a different revision.

## Reuse And Rights Boundary

No code, prompt corpus, gallery content, example image, or remote Agent
instruction was copied from these sources. Repository licenses govern their
covered code, not automatically third-party media, people, marks, styles,
prompts, privacy consent, ownership, truth, or commercial-use permission.
Hashes and provenance are useful file/history signals but do not establish
those separate rights or quality facts.

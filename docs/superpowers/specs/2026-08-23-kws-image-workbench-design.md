# KWS Image Workbench Design

**Date:** 2026-08-23

**Status:** Approved design

**Repository:** `/Users/kws/source/private/Archive`

**Primary surface:** `skills/kws-image-workbench/`

## 1. Summary

Create `kws-image-workbench`, a Codex-focused Agent Skill for project-bound
raster image work. It adds project inspection, a compact image brief,
reference-role handling, deterministic routing, output review, targeted
iteration, and non-destructive asset handoff around Codex's existing built-in
image-generation capability.

The skill is not another image model, API proxy, prompt marketplace, or fork
of a large community gallery. It does not duplicate the bundled imagegen
skill's provider and CLI mechanics. Its value is the production contract that
the generic generation path cannot infer reliably from a short request:

- what the asset is for and where it will be consumed;
- whether raster generation is appropriate at all;
- which input is an edit target, a style reference, or a compositing source;
- which visual, textual, identity, layout, and brand properties must remain
  invariant;
- how an output is inspected, corrected, saved, and reported;
- when exact text, data, logos, icons, or UI should use a deterministic hybrid
  workflow instead of a fully generated image.

The normal experience remains simple. A clear request to create or edit a
project image proceeds without a configuration form. The skill asks one short
question only when a missing choice would materially change the deliverable,
rights boundary, or edit target. It generates one useful first candidate by
default, inspects the result, performs a narrowly justified correction when
the failure is unambiguous, and returns the final asset path and prompt.

## 2. Goals

1. Produce or edit raster assets that fit the current project's dimensions,
   crop behavior, theme, surrounding assets, and consuming surface.
2. Keep generation, editing, planning, and audit-only requests distinct so a
   review request never causes an unintended live generation.
3. Convert image requests into a compact `ImageSpec` that makes purpose,
   references, invariants, exact copy, and acceptance criteria explicit.
4. Reuse the current Codex built-in image-generation path rather than adding
   a second API client, relay, credential flow, or provider router.
5. Inspect generated outputs visually and mechanically before claiming that a
   project asset is ready.
6. Preserve user control through non-destructive filenames, bounded
   assumptions, and targeted single-change iterations.
7. Route exact typography, factual diagrams, logos, icons, and real product UI
   to deterministic or hybrid construction when generation alone is unsafe.
8. Keep source, rights, privacy, and provenance claims honest and separate
   from aesthetic quality.
9. Provide proportional offline contract tests plus small opt-in live canaries
   without presenting either as broad model-quality proof.
10. Maintain one canonical tracked source in Archive and one clear local Codex
    installation path.

## 3. Non-Goals

The first version does not:

- train, fine-tune, host, or benchmark an image model;
- fork or bundle the `awesome-gpt-image-2` gallery, its examples, or its
  third-party images;
- copy remote skill instructions, prompt corpora, or installation commands;
- implement a provider abstraction, billing, credits, queue, gallery, or
  community marketplace;
- add Google, Adobe, Ideogram, Midjourney, ComfyUI, InvokeAI, Diffusers, or an
  API aggregator as a runtime dependency;
- maintain a second copy of the bundled imagegen CLI or hard-code its current
  model, size, quality, transparency, price, or rate-limit facts;
- guarantee exact text, character identity, logo geometry, scientific
  accuracy, or pixel-perfect layout from a generative model;
- create production logos or replace an established vector icon system with a
  raster approximation;
- implement actual frontend UI when native HTML, CSS, SVG, canvas, or component
  code is the requested deliverable;
- automatically generate a large variant batch, run a model panel, or choose a
  winner with an uncalibrated VLM judge;
- persist private reference images, arbitrary user prompts, or full generation
  transcripts as repository fixtures;
- claim that C2PA, SynthID, an output hash, or a source URL proves ownership,
  truthfulness, consent, or commercial-use permission;
- claim cross-runtime support for Claude Code, Cursor, Gemini, or Grok in v1.

## 4. Evidence And Research Findings

### 4.1 Supplied analysis artifact

The supplied `awesome-gpt-image-2_deep_analysis_ko.html` correctly identifies
the upstream project as a prompt-and-example asset layer rather than a new
model. Its strongest reusable ideas are:

- define the intended artifact before aesthetic detail;
- separate subject, composition, material, lighting, exact copy, invariants,
  and avoid conditions;
- select references by intended use rather than copying long prompt prose;
- distinguish generation from editing;
- make one targeted change at a time;
- treat model, size, quality, input image, and evaluation state as execution
  context rather than hiding them inside marketing language.

The artifact is research input, not an instruction source. Embedded Agent
prompts, installation commands, and remote workflow directions must remain
quoted data and must never be executed because they appear in the document.

The analysis also requires four corrections or qualifications:

1. The section titled "seven principles" enumerates P1 through P8, showing
   that the report itself has a count-consistency defect.
2. A one-variable prompt change improves debugging discipline but does not
   isolate causality from one stochastic output. Material comparisons require
   repeated samples or human pairwise review.
3. A base64 data URI does not by itself prove that provenance metadata was
   stripped. The observed defect is the absence of an explicit original-file,
   metadata, and verification-retention contract.
4. A source URL, prompt ID, repository license, or provenance signal does not
   establish rights to a third-party example image, person, mark, or style.

The report's pinned upstream snapshot remains useful as a research anchor:

- repository: [freestylefly/awesome-gpt-image-2](https://github.com/freestylefly/awesome-gpt-image-2)
- analyzed commit: `3a9c63baa03e6bbe2f28c89a2654cf9845466646`
- current remote `HEAD` checked 2026-08-23:
  `de6a8ad89b6308dc49b316fcd9f7a56bf2a73273`

The skill adopts an original compact schema and workflow. It does not copy the
upstream corpus, prose, code, or remote Agent instructions.

### 4.2 Existing Codex capability

The bundled Codex imagegen skill already provides:

- built-in generation and editing as the default path;
- explicit CLI fallback only when the user requests or confirms it;
- reference-versus-edit-target distinction;
- `view_image` inspection before editing a local file;
- single-change iteration and invariant repetition;
- non-destructive save behavior and project-bound handoff;
- prompt scaffolding for common raster use cases.

`kws-image-workbench` must not restate that manual or create a competing API
client. It owns the project-specific layer: repository inspection, `ImageSpec`,
hybrid routing, rights and privacy holds, mechanical output inspection,
acceptance status, and integration reporting.

Fast-moving provider facts must stay outside the stable KWS contract. On
2026-08-23, the local bundled CLI reference said that GPT Image 2 did not
support the Image API transparency parameter, while current OpenAI
documentation described transparent PNG/WebP output as a preview feature.
That drift is direct evidence that the KWS skill should route through the
active bundled capability and official documentation instead of copying model
parameter tables.

Primary OpenAI references checked 2026-08-23:

- [Image generation guide](https://developers.openai.com/api/docs/guides/image-generation)
- [GPT Image prompting guide](https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide)
- [Content provenance](https://developers.openai.com/api/docs/guides/content-provenance)
- [Build skills](https://learn.chatgpt.com/docs/build-skills)

### 4.3 Related open-source patterns

The following projects were inspected read-only on 2026-08-23. Their current
remote `HEAD` values are evidence locators, not compatibility guarantees.

| Project | Checked `HEAD` | Useful pattern | Rejected boundary |
| --- | --- | --- | --- |
| [GPT-Image2-Skill](https://github.com/wuyoscar/GPT-Image2-Skill) | `068dd9e24aadc8731e46f38548ca4dcd94515d35` | intent -> limited reference -> prompt -> execute runbook | model/CLI/API-key coupling and bundled gallery |
| [ComfyUI](https://github.com/Comfy-Org/ComfyUI) | `82f839f5e737d8bfce480872ba05e5a430f2526f` | versioned workflow and execution-history concepts | node runtime, model management, and UI workflow dependency |
| [InvokeAI](https://github.com/invoke-ai/InvokeAI) | `e431d249e09290b241c45ad340addebc1bfc7737` | image plus recallable settings and edit history | production graph engine as a personal skill dependency |
| [Diffusers](https://github.com/huggingface/diffusers) | `58eb52c0803ea9af3abec60841c2a093bdf1f951` | explicit model revision and pipeline configuration | GPU/model downloads and per-model licenses in v1 |
| [image-prompt-library](https://github.com/EddieTYP/image-prompt-library) | `c9e8d3547a9556bcba4dbbfab17e24680f0747db` | separate source prompt, variants, source, model, and notes | AGPL code, database, and UI reuse |
| [promptfoo](https://github.com/promptfoo/promptfoo) | `679e7ecb64a2e09042b009b549b81dc0d0b983bb` | explicit test matrix, cache, and exportable reports | treating its checks as a complete visual-quality judge |
| [c2pa-rs](https://github.com/contentauth/c2pa-rs) | `24d17555beafb70c15e1e1e4054ac3c06fbba1c0` | optional signed media-history adapter | using provenance as a replacement for rights or QA |

No third-party implementation is copied. `references/sources.md` will record
the pinned source, license, checked date, adopted idea, and rejected boundary.

### 4.4 Provider and evaluation findings

The built-in Codex path is the only v1 execution route because it is already
available in the target host and avoids another secret, relay, and failure
surface. Other official services may have useful capabilities, but no
cross-provider quality or latency ranking was established in the research.

Future provider admission must use rights-safe fixtures and the same request,
receipt, and evaluation contract. Vendor claims about text rendering,
reference fidelity, commercial safety, speed, or production suitability are
not acceptance evidence by themselves. Midjourney is not a v1 automation
candidate because its public guidance does not provide a general supported API
for this workflow.

Official provider surfaces checked for this decision on 2026-08-23:

- [Google Gemini image generation](https://ai.google.dev/gemini-api/docs/generate-content/image-generation)
- [Adobe Firefly image generation](https://developer.adobe.com/firefly-services/docs/firefly-api/guides/how-tos/cm-generate-image/feature-guide)
- [Ideogram prompt-based editing](https://developer.ideogram.ai/api-reference/api-reference/edit-with-prompt)
- [Midjourney community and automation guidelines](https://docs.midjourney.com/hc/en-us/articles/32013696484109-Community-Guidelines)

Public benchmarks inform fixture categories but do not become release gates:

- [GenEval](https://arxiv.org/abs/2310.11513) covers object, count, color, and
  position composition;
- [T2I-CompBench](https://arxiv.org/abs/2307.06350) covers attribute binding and
  compositional relations;
- [DPG-Bench](https://arxiv.org/abs/2403.05135) covers dense prompt following;
- [ImgEdit-Bench](https://arxiv.org/abs/2505.20275) covers edit instruction,
  quality, preservation, and multi-turn behavior.

These benchmarks do not prove Korean typography, brand fit, project crop
safety, rights, or actual publishability. Small project-realistic live canaries
plus calibrated human review remain the meaningful evidence.

## 5. Considered Approaches

### A. Fork the prompt gallery

Copy the upstream cases, templates, and routing skill into Archive. This offers
fast breadth, but creates rights ambiguity, source drift, noisy retrieval, and
a maintenance obligation unrelated to the user's actual project assets.

### B. Build a multi-provider image engine

Create adapters for OpenAI, Google, Adobe, Ideogram, local diffusion, queues,
receipts, and cross-provider evaluation. This may become useful later, but it
duplicates existing Codex capability and turns a personal skill into a product
runtime before its project workflow is validated.

### C. Project-aware workbench over built-in imagegen — selected

Create a thin skill that inspects the project, compiles a clear `ImageSpec`,
routes deterministic versus generative work, calls the built-in image tool for
authorized raster work, checks the result, and hands it off safely. External
case libraries remain evidence sources rather than runtime dependencies.

## 6. Invocation Contract

### 6.1 Canonical trigger description

The intended `SKILL.md` description is:

> Use when the user asks to plan, generate, edit, compare, or production-check
> a raster image asset that must fit a local project, preserve input
> constraints, or be saved and integrated. Inspect project context, compile a
> compact ImageSpec, use Codex image generation only for a clear generation or
> edit request, validate the result, and save non-destructively. Do not use for
> casual one-off image requests, SVG or code-native assets, actual frontend
> implementation, or copying external prompt galleries.

Automatic invocation remains enabled. Explicit invocation is preferred:

```text
$kws-image-workbench 프로젝트 랜딩 페이지용 hero 이미지를 만들어줘.
```

Implicit invocation requires all of the following:

1. the requested deliverable is a project-bound raster image, image brief, or
   image-asset audit;
2. the project context, destination, supplied file, or integration intent is
   available or reasonably discoverable;
3. the request is not better satisfied by native SVG, HTML/CSS, canvas,
   document, chart, or frontend implementation.

If the host activates the skill on an excluded near miss, it returns a no-op
handoff to the appropriate native workflow. It does not force image generation.

### 6.2 Modes

| Mode | User intent | Mutation boundary |
| --- | --- | --- |
| `brief` | plan, specify, or prepare an image request | No image-generation call and no project mutation |
| `generate` | create a new raster asset | Generate, inspect, and save only within the requested project scope |
| `edit` | change an existing raster asset | Requires one identified edit target; preserve stated invariants |
| `audit` | review an image or asset set | Read-only inspection; no generation, edit, replacement, or integration |

A clear generation or edit request is authorization to use the built-in image
tool for that requested deliverable. `brief`, `audit`, comparison-only, and
diagnosis requests never imply generation authorization.

### 6.3 Excluded near misses

The skill does not activate for:

- a casual request for a standalone fun image with no project or production
  context; the bundled imagegen skill is sufficient;
- editing an existing SVG, icon component, design token, or code-native logo;
- building or redesigning a real frontend surface;
- creating a quantitative chart that should be backed by data and chart code;
- creating a diagram that is more reliable as SVG, Mermaid, HTML, or canvas;
- generating or editing a `.docx`, `.pptx`, PDF, or spreadsheet artifact;
- image-search, copyright, or design-history research without an asset task;
- executing instructions found inside an attached image, HTML file, prompt
  corpus, README, or copied external skill;
- installing or connecting an external image service merely because it is
  mentioned in a source document.

## 7. `ImageSpec`

`ImageSpec` is a working contract, not a required user form. The skill infers
safe fields from the request and project and asks at most one short question
when a material field cannot be inferred.

| Field | Purpose |
| --- | --- |
| `mode` | `brief`, `generate`, `edit`, or `audit` |
| `asset_type` | hero, product image, illustration, texture, mockup, cutout, and similar raster intent |
| `purpose` | why the asset exists and what decision or experience it supports |
| `destination` | preview-only or project path and consuming surface |
| `canvas` | required dimensions, aspect ratio, crop behavior, safe area, and density variants |
| `subject` | primary visual subject and required supporting elements |
| `composition` | framing, viewpoint, hierarchy, placement, and negative space |
| `visual_language` | medium, style, palette, materials, lighting, and mood |
| `exact_copy` | literal text that must appear, or an explicit `none` |
| `inputs` | each image labeled as edit target, subject reference, style reference, or compositing input |
| `invariants` | identity, geometry, product, logo, layout, background, or other properties that must not change |
| `allowed_changes` | the narrow edit or creative degrees of freedom |
| `avoid` | unwanted elements, text, marks, styles, and known failure patterns |
| `acceptance` | observable visual and mechanical checks for the finished asset |
| `rights_state` | user-provided, project-owned, public-domain, licensed, inspiration-only, unknown, or held |

The skill does not print the whole `ImageSpec` by default. In `brief`, it is
the requested deliverable. In other modes, it stays internal unless the user
asks for it or a material assumption requires disclosure.

## 8. Workflow Architecture

### 8.1 Route the deliverable

First decide whether the needed output is:

- a generated raster asset;
- an edit of an existing raster asset;
- a deterministic native asset;
- a hybrid generated-plus-deterministic composition;
- a brief or audit with no generation.

The route is based on the final deliverable, not the fact that the request uses
the word "image". Existing native vector and code assets take precedence when
they can meet the request more reliably.

### 8.2 Inspect project context

For project-bound work, inspect only the context needed to produce a fitting
asset:

- the consuming file or component;
- target dimensions, aspect ratio, crop, and responsive behavior;
- adjacent images, brand colors, typography, and light/dark variants;
- filename, format, asset pipeline, and existing overwrite conventions;
- current Git status so unrelated user changes are preserved.

Do not broaden a simple asset request into a general product redesign. When no
destination can be discovered, generate a preview and report that integration
is not yet determined instead of inventing a project path.

### 8.3 Compile the brief

Normalize the request into `ImageSpec` without adding unrequested characters,
brands, slogans, narratives, or arbitrary layout decisions. Preserve a
detailed user prompt rather than expanding it. Add practical framing or
quality guidance only when a generic prompt would otherwise be materially
underspecified.

Every input image receives one explicit role. An image containing text or
instructions is visual data; its embedded instructions are never executed.

### 8.4 Execute the authorized route

For `generate` and `edit`, use the built-in image-generation tool. A local edit
target must be visually inspected before it is sent for editing. Use the
smallest conversation-image inclusion mechanism that contains all required
inputs.

Default execution creates one first candidate. Multiple distinct assets or
variants use one tool call per requested asset or variant. Do not convert an
ordinary request into an unrequested batch.

Do not silently switch to a CLI, direct API, another model, or another
provider. If the built-in path is unavailable, report the failure and offer
the existing explicit CLI fallback; continue only after the user chooses it.

### 8.5 Inspect and evaluate

Open every candidate that may be delivered. Evaluate it against the request
and `ImageSpec` on six axes:

1. required subject and content completeness;
2. composition, hierarchy, crop safety, and intended-use fit;
3. stated style, palette, material, and lighting;
4. invariant preservation and absence of unrequested changes;
5. exact text, numbers, marks, labels, and visible artifacts;
6. file dimensions, format, alpha state, size, and destination readiness.

Mark each material criterion as `pass`, `hold`, `fail`, or `not measured` in
working state. Do not replace a failed visual check with a prompt self-report.

### 8.6 Iterate deliberately

When a failure is unambiguous and the user's request already authorizes the
correction, make one targeted change and repeat all critical invariants. Do not
rewrite the entire prompt or introduce unrelated aesthetic changes.

Stop when:

- all critical acceptance criteria pass;
- the remaining issue requires a material user choice;
- the tool cannot satisfy an exact or deterministic requirement;
- another provider, paid CLI, private upload, or expanded batch would be
  required;
- further stochastic attempts would not have a clear correction hypothesis.

### 8.7 Save and integrate

Preview-only work may remain in the built-in generated-image location and is
rendered inline. A project-bound final asset must be copied or moved into the
workspace before completion.

Never overwrite an existing asset unless replacement is explicit. Otherwise,
use a descriptive sibling filename. Update consuming code only when integration
was requested or the target is unambiguous and already in scope.

The final response reports:

- final asset path or preview status;
- the final prompt or concise prompt set;
- generation versus edit and built-in versus explicitly chosen fallback;
- any critical `hold` or `not measured` item;
- whether consuming code or metadata was updated.

## 9. Deterministic And Hybrid Boundary

Generation is not the final renderer when correctness depends on exact
structure. Prefer native or hybrid construction for:

- Korean or multilingual copy that must be exact;
- prices, dates, measurements, citations, legal copy, and scientific labels;
- data-backed charts, tables, axes, legends, and process diagrams;
- established logos, app icons, adaptive icons, vector marks, and icon sets;
- actual product UI and responsive layout;
- accessible text that must remain selectable or screen-reader available.

The preferred hybrid pattern is:

1. generate the illustration, background, texture, or photographic layer with
   no exact text;
2. add text, data, marks, and layout deterministically in the project's native
   tool or code;
3. render or export a raster derivative only when the consuming surface needs
   one;
4. verify the deterministic layer against its source data and preserve the
   editable source.

If the user explicitly wants model-rendered text or layout, the skill may try,
but it must inspect the literal result and hold rather than claim exactness
when the output is wrong.

## 10. Tool And Provider Boundary

### 10.1 V1 route

- Use Codex built-in image generation for ordinary generation and editing.
- Use local image viewing for source and result inspection.
- Use repository-native tools for deterministic overlays and integration.
- Use a small standard-library asset inspector for file-level facts.
- Use web or image search only when the user requests research or a missing
  reference is genuinely necessary; preserve source and rights state.

### 10.2 Explicit fallback

The KWS skill does not implement its own CLI. When the user explicitly asks for
CLI, API, model, mask, output-format, or provider controls, follow the active
bundled imagegen fallback contract. Never ask the user to paste an API key into
chat and never route through an unreviewed third-party relay.

### 10.3 Future provider admission

A provider may be added only through a separately approved design and after it
passes all of the following:

- official supported API and automation terms;
- documented data-use, retention, region, and credential behavior;
- generation and editing capabilities needed by the selected use cases;
- the same rights-safe fixture set and evaluation rubric;
- request and output receipts with provider, model or snapshot, parameters,
  input hashes, output hashes, timing, failures, and cost where available;
- no unsupported claim of superiority from vendor examples alone.

## 11. Package Design

The v1 package contains only files with a concrete contract role:

```text
skills/kws-image-workbench/
├── SKILL.md
├── README.md
├── CHANGE_PROTOCOL.md
├── references/
│   ├── image-spec.md
│   ├── quality-rubric.md
│   └── sources.md
├── scripts/
│   └── inspect_asset.py
└── evals/
    ├── cases.json
    └── run.py
```

### `SKILL.md`

Owns the discriminating trigger, four modes, routing sequence, execution
authorization boundary, deterministic/hybrid decision, iteration stop rules,
failure behavior, and final handoff contract. It stays concise and routes to a
reference only when the current request needs that detail.

The frontmatter uses `name`, `description`, `compatibility`, and version
metadata. It does not hard-code provider models, prices, dimensions, hidden
permissions, or an explicit-only invocation policy.

### `README.md`

Provides a one-minute Korean quick start, explicit invocation, example
generation/edit/brief/audit requests, near misses, privacy and rights notes,
installation and update guidance, and offline versus live verification status.
It explains that the bundled imagegen path remains the executor.

### `CHANGE_PROTOCOL.md`

Keeps trigger, modes, `ImageSpec`, rubric, source registry, fixture
expectations, inspection output, README claims, and verification-map commands
synchronized. Model-specific source refreshes do not automatically change the
stable skill behavior; behavior changes require a SemVer bump.

### `references/image-spec.md`

Defines `ImageSpec`, reference roles, safe inference, project-inspection
guidance, deterministic/hybrid routing examples, and the optional sanitized
project receipt. The main skill reads it for complex briefs, multi-input edits,
or project integration, not for every simple asset.

### `references/quality-rubric.md`

Defines visual and mechanical criteria, critical versus advisory failures,
exact-copy checks, edit-preservation checks, crop and safe-area checks,
targeted-iteration rules, and status semantics. It contains no claim that an
automatic aesthetic score is authoritative.

### `references/sources.md`

Records authoritative documentation and external project evidence with direct
URL, immutable revision where available, license, checked date, adopted idea,
rejected boundary, and refresh trigger. It links rather than copying external
prompt libraries or provider manuals.

### `scripts/inspect_asset.py`

Uses the Python standard library to emit JSON for supported final formats:

- detected PNG, JPEG, or WebP format;
- width and height;
- alpha presence when the format exposes it;
- byte size;
- SHA-256;
- explicit parse error for malformed or unsupported data.

It does not score aesthetics, OCR text, identity, rights, or provenance. It
includes `--self-test` fixtures generated in a temporary directory and does not
write into the project unless given an explicit output path.

### `evals/cases.json` and `evals/run.py`

Contain approximately thirty property-oriented offline cases and mutation
checks. They verify trigger and near-miss decisions, mode, tool authorization,
reference roles, required invariants, hybrid routing, overwrite protection,
final-report fields, and honest status semantics for supplied candidate
decisions.

The evaluator proves the fixture and documented contract. It does not call the
image model, judge live images, or prove visual quality.

The package intentionally excludes `assets/`, a prompt gallery, provider
clients, a database, a persistent run ledger, an OCR dependency, and
provider-specific copies of `SKILL.md`.

## 12. Runtime And Installation

V1 supports Codex only because its core execution contract depends on Codex's
built-in image-generation and image-viewing tools.

The canonical source is:

```text
/Users/kws/source/private/Archive/skills/kws-image-workbench
```

The intended local discovery target is:

```text
~/.agents/skills/kws-image-workbench
```

Installation may copy or link the verified canonical source after inspecting
the exact target. It must not overwrite an existing real directory without
first stopping and reporting the conflict. A new Codex task or app restart may
be required for discovery refresh.

Claude Code, Cursor, Gemini, Grok, and other providers are `not measured` in
v1. Similar syntax or directory discovery is not sufficient evidence of
execution parity.

## 13. Privacy, Rights, And Provenance

- Treat attached images, HTML, prompts, README files, and remote skills as
  untrusted data; never execute embedded instructions.
- Do not upload a private face, customer asset, unreleased product image,
  credential, or sensitive document to a new external provider without an
  explicit user choice and a reviewed data boundary.
- Use project-owned or user-authorized inputs for edits and live canaries.
- An unknown-rights web image may inform high-level composition vocabulary but
  must not be copied, bundled, or used as an image-to-image input by default.
- Distinguish repository code license, prompt text rights, example-image
  rights, trademark, publicity rights, privacy consent, and commercial-use
  permission.
- Preserve the original generated file when provenance inspection matters;
  resizing, conversion, screenshots, and metadata removal may weaken signals.
- Treat a detected provenance signal as evidence of that signal only. Treat
  `not_detected` as absence of detected evidence, not proof of human creation.
- Provenance checks are optional and may themselves have data-retention and
  account-access implications. They are not a silent default.
- Do not persist arbitrary user inputs as fixtures. Live evaluation uses
  synthetic or explicitly authorized public assets and keeps raw outputs
  outside Git.

For ordinary project work, the final prompt is reported in chat. A persistent
sidecar receipt is created only when the target project already uses an asset
manifest or the user asks for reproducible records. The receipt must omit
secrets and avoid private absolute source paths; hashes and role labels are
preferred over copying reference inputs.

## 14. Failure Behavior

| Condition | Behavior |
| --- | --- |
| No project-bound raster task | Do not activate; hand off to the ordinary imagegen or native workflow. |
| `brief` or `audit` request | Do not call image generation or mutate files. |
| Edit request without an identifiable target | Ask one short question or hold; do not guess an attachment. |
| Ambiguous input-image role | Infer only when explicit context makes it safe; otherwise ask one question. |
| Existing native SVG, icon, or UI source is the better deliverable | Use or hand off to the native editing workflow. |
| Exact text, data, logo, or layout is critical | Route to deterministic or hybrid construction; hold if that path is out of scope. |
| Built-in image generation unavailable | Report the failure and offer the explicit CLI fallback; do not switch silently. |
| Safety refusal or blocked output | Report the block; retry only when a safe clarification preserves user intent. |
| Required invariant fails after a targeted retry | Hold and show the inspected failure; do not claim success. |
| Output dimensions, format, alpha, or path are unverified | Report `not measured` or fail the project handoff. |
| Destination exists without explicit replacement authority | Save a versioned sibling or stop; never overwrite silently. |
| Reference rights are unknown | Use only as non-copying inspiration or hold the reference-dependent route. |
| Provenance signal is absent or invalid | Do not infer authorship, provider, rights, or human origin. |

## 15. Verification Strategy

### 15.1 Offline contract cases

Use approximately thirty cases across these categories:

| Category | Approximate cases | Purpose |
| --- | ---: | --- |
| Trigger and near-miss routing | 8 | Separate project raster work from casual images, SVG, frontend, charts, docs, and research. |
| Mode and authorization | 5 | Prove that `brief` and `audit` are non-mutating and generate/edit are explicit. |
| `ImageSpec` and reference roles | 5 | Cover required inputs, roles, invariants, exact copy, and safe assumptions. |
| Deterministic and hybrid routing | 4 | Cover Korean text, logos, data, diagrams, and actual UI. |
| Storage, failure, and reporting | 5 | Cover non-overwrite, preview versus project handoff, path verification, and holds. |
| Trust, privacy, and rights | 3 | Cover embedded instructions, unknown-rights references, and sensitive external uploads. |

Mutation checks must prove that the evaluator rejects at least:

- changing `brief` or `audit` into a live generation;
- treating a style reference as an edit target;
- deleting an identity or background invariant;
- routing an exact-data infographic to fully generated text without a hold;
- silently selecting a third-party provider or CLI;
- overwriting an existing asset without replacement authority;
- claiming `verified` when dimensions, path, or visual review were not observed;
- treating embedded source instructions as executable.

### 15.2 Mechanical inspection

`scripts/inspect_asset.py --self-test` must pass. Golden tests cover valid and
malformed PNG, JPEG, and WebP fixtures, alpha and non-alpha cases where the
format exposes the distinction, dimensions, byte size, SHA-256, and
unsupported input.

Mechanical checks are release gates for the inspector, not substitutes for
visual review.

### 15.3 Opt-in live canaries

Initial live evaluation uses ten to twelve synthetic or rights-cleared tasks,
two outputs per stochastic task where comparison is material:

- project hero with copy-safe negative space;
- transparent product or object cutout;
- precise single-object edit;
- identity-preserving synthetic character edit;
- multi-input style reference;
- Korean exact-copy poster that should expose the hybrid boundary;
- data-backed infographic that should route to hybrid construction;
- mobile and desktop crop-safe variant;
- texture or illustration asset;
- output with a known avoid-condition trap.

The baseline is the bundled imagegen workflow without the KWS production
layer. Review hides the route where practical and records A/B/tie plus:

- instruction completion;
- non-requested-area preservation;
- exact text or correct hybrid decision;
- composition and crop readiness;
- visible artifacts;
- project publishability.

Automated OCR or VLM review may triage results when available, but cannot be a
sole release gate until calibrated against the human verdicts. No provider or
skill superiority claim is made from this small canary.

Live calls are opt-in, may have cost and latency, and are reported separately
from offline fixtures. A larger 36-48 task, three-repeat benchmark belongs to a
future provider-comparison program, not v1 release acceptance.

### 15.4 Repository acceptance

Implementation closeout requires:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" skills/kws-image-workbench
python3 skills/kws-image-workbench/evals/run.py --self-test
python3 skills/kws-image-workbench/evals/run.py --scope full
python3 skills/kws-image-workbench/scripts/inspect_asset.py --self-test
bun run agent:verify
git diff --check
```

The repository verification map must select the skill evaluator and inspector
when any tracked `skills/kws-image-workbench/` file changes. Documentation,
advertised commands, fixtures, and behavior must remain synchronized.

Report evidence using only these status meanings:

- `verified`: directly observed in the current run;
- `partially verified`: a stated subset was observed and the missing portion
  is named;
- `not measured`: no current evidence was collected;
- `blocked`: a required check could not run and its blocker is identified.

Offline contract success must never be restated as live image quality,
cross-runtime support, rights clearance, or provider superiority.

## 16. Documentation Requirements

The quick-start guide should lead with natural requests:

```text
$kws-image-workbench 이 프로젝트 랜딩 페이지 hero 이미지를 만들어줘.
$kws-image-workbench 이 상품 사진은 그대로 두고 배경만 바꿔줘.
$kws-image-workbench 생성하지 말고 이미지 브리프만 정리해줘.
$kws-image-workbench 이 자산이 모바일 크롭과 다크 모드에 맞는지 검토해줘.
```

It must also explain:

- a casual standalone image can use the ordinary bundled imagegen path;
- exact Korean text, charts, logos, icons, and actual UI may use a hybrid or
  native workflow;
- each reference image needs a role;
- project assets are saved non-destructively by default;
- model facts and provider comparisons are refreshed from sources rather than
  promised by the stable skill;
- offline evaluation and live generation evidence are different;
- external references need rights and privacy review.

## 17. Residual Risks And Honest Boundaries

- Generative output remains stochastic even when one prompt variable changes.
- Visual inspection is partly subjective and can miss subtle identity,
  cultural, factual, or brand errors.
- Korean text and structured layouts may improve over time but still require
  literal inspection or deterministic composition.
- The built-in tool's model, parameters, output location, safety behavior, and
  feature availability may drift.
- A thin KWS skill cannot guarantee that a provider preserves every edit
  invariant.
- Project integration can reveal crop, density, compression, or theme defects
  that are not visible in an isolated preview.
- Hashes and provenance signals support traceability but do not prove rights or
  truth.
- Approximately thirty offline cases protect the contract, not the open-ended
  distribution of image requests.
- Ten to twelve live canaries are a release smoke set, not a population-level
  quality benchmark.

These risks are handled by narrow routing, hybrid construction, explicit holds,
non-destructive output, visual plus mechanical inspection, and truthful status
reporting rather than by adding a larger engine.

## 18. Implementation Boundary

Implementation may begin only after the written specification is reviewed.
The subsequent plan must preserve this order:

1. add offline trigger, mode, trust, hybrid, storage, and failure fixtures;
2. implement the failing evaluator and mutation checks;
3. scaffold the minimal skill package;
4. implement and self-test `inspect_asset.py`;
5. write `SKILL.md` against the fixtures and progressive-disclosure boundary;
6. add focused references, README, and change protocol;
7. update `skills/README.md` and the repository verification map;
8. run quick skill validation, focused evals, inspector self-test, repository
   verification, and diff checks;
9. run an independent forward test in an isolated temporary workspace;
10. run live image canaries only when separately authorized;
11. report tracked source, local installation, live evidence, and remote Git
    state separately.

Implementation must not add a provider client, prompt corpus, gallery, assets,
database, persistent runtime, OCR package, or cross-runtime installation unless
a later approved design expands the scope.

## 19. Approved Decisions

The user approved the research-backed direction on 2026-08-23:

1. create `kws-image-workbench` as a project-aware production layer over the
   existing Codex image-generation capability;
2. keep v1 Codex-only and use the built-in image tool as the sole default
   execution route;
3. support `brief`, `generate`, `edit`, and `audit` with mutation authority tied
   to the mode;
4. use compact `ImageSpec` guidance rather than a copied prompt gallery;
5. route exact text, data, logos, icons, and actual UI to deterministic or
   hybrid workflows;
6. inspect outputs visually and mechanically and save project assets
   non-destructively;
7. keep external providers and local image engines out of v1;
8. separate offline contract evidence, opt-in live canaries, and unmeasured
   quality claims;
9. keep rights, privacy, provenance, and aesthetic quality as separate
   decision layers;
10. implement a small standard-library asset inspector and an approximately
    thirty-case contract harness without building a new orchestration product.

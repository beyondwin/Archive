# Context Budget

Each worker receives a bounded task packet containing the current goal, file
claims, dependencies, acceptance commands, explicit spec sections, relevant
decisions, and evidence refs. Do not inline unrelated plan/spec sections, raw
conversation history, or prior model transcripts.

If required task evidence cannot fit, stop and narrow the task or create a
reviewed artifact summary. A budget limit never authorizes omission of safety,
scope, acceptance, or completion evidence.

Usage and cached-input counters are attempt evidence. Compare efficiency only
after quality and integrity gates pass.

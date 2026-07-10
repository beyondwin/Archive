# Learning And Diagnostic Evidence

V3 stores bounded diagnostic and learning observations as immutable evidence
referenced by kernel events. Record only facts needed for replay, recovery, or
future execution quality: task/attempt IDs, category, one-line summary, action,
and evidence digest.

Do not store secrets, full conversation transcripts, raw prompts, absolute home
paths, or unbounded command output. Prompt and handoff export create no learning
or run artifacts. Inspection derives recommendations without writing them back
into durable run state.

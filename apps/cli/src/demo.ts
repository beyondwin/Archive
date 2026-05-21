import { defaultRunRoot, runWaygentDemo } from "@waygent/orchestrator";

const result = await runWaygentDemo({ root: defaultRunRoot(), run_id: "run_demo" });

console.log(
  JSON.stringify(
    {
      run_id: result.run_id,
      trust_status: result.trust_report.trust_status,
      total_events: result.events.length,
      safe_wave: result.projection.safe_wave,
      apply_state: result.apply_state
    },
    null,
    2
  )
);

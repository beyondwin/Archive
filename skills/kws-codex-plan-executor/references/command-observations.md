# Command Observations

Record each acceptance or verification command as bounded evidence with the
command, cwd, phase, exit status, duration, failure category, short diagnostic,
and evidence digest. Do not store secrets or unbounded output.

The scheduler and repair policy use a stable root-cause key to bound retries.
Environment and dependency failures return actionable preparation guidance;
product failures return to a Sol/high repair attempt and fresh verification;
policy or integrity failures block. Repeating the same failing command without
new evidence is not a new diagnosis.

The kernel attaches accepted observations to the event history. A model cannot
edit the projected state directly or relabel a failed observation as success.

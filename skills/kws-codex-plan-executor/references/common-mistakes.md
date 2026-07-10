# Common Mistakes

- Editing before task file claims, acceptance commands, and explicit spec refs
  pass preflight.
- Running implementation from the caller's checkout instead of the isolated
  worktree.
- Treating prompt text as model enforcement instead of checking launcher
  arguments and actual-model attestation.
- Letting a read-only scout write files or issue a quality verdict.
- Running two write-capable attempts concurrently.
- Editing a manifest, event, evidence object, or state projection by hand.
- Trusting a stored projection without event replay and digest checks.
- Applying repair without first reviewing a dry-run plan and exact action.
- Treating deterministic checks or a migration dry run as paid live closeout.

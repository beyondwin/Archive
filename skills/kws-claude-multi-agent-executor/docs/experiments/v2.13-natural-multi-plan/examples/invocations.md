# Example invocations (v2.13)

Each example shows the slash-command args and the expected echo line that Phase -1.0 prints to the interactive parent before any work begins. The echo line is the user's one chance to spot mis-interpretation before headless self-spawn.

## 1. Single plan, defaults (no change from v2.12)

Args:
```
/kws-claude-multi-agent-executor plan=plans/feature-a.md spec=specs/feature-a.spec
```

Echo:
```
Parsed: 1 plan [feature-a], implementer_model=sonnet [default], parallel=on [default], mode=headless [default], risk=per-task.
```

State.json shape: v2.12 single-plan (no `plan_chain` field, `active_plan: "plan1"`).

---

## 2. Single plan, model + parallel via explicit args

Args:
```
/kws-claude-multi-agent-executor plan=plans/feature-a.md spec=specs/feature-a.spec implementer_model=opus parallel=off
```

Echo:
```
Parsed: 1 plan [feature-a], implementer_model=opus [explicit], parallel=off [explicit], mode=headless [default], risk=per-task.
```

---

## 3. Single plan, same as #2 but with natural language

Args:
```
/kws-claude-multi-agent-executor plan=plans/feature-a.md spec=specs/feature-a.spec 오푸스로 순차적으로 진행해줘
```

Echo:
```
Parsed: 1 plan [feature-a], implementer_model=opus [NL '오푸스'], parallel=off [NL '순차'], mode=headless [default], risk=per-task.
```

Identical effective behavior to #2. The `오푸스로` and `순차적으로` free-text tokens trigger the lexicon.

---

## 4. Three-plan chain, defaults

Args:
```
/kws-claude-multi-agent-executor plan=plans/a.md spec=specs/a.spec plan2=plans/b.md spec2=specs/b.spec plan3=plans/c.md spec3=specs/c.spec
```

Echo:
```
Parsed: 3 plans [a→b→c], implementer_model=sonnet [default], parallel=on [default], mode=headless [default], risk=per-task.
```

State.json shape: v2.13 multi-plan with `plan_chain` of length 3. `active_plan: 0` initially.

Execution order:
1. Phase 0 → Phase 1 → Phase 2 Step 0 (LOW batch) for plan `a`
2. Phase 2 Step -1 fires: swap to `active_plan: 1`, re-baseline, re-run Phase 0 Steps 3/3.5/4/6 for plan `b`, then Phase 1
3. Step -1 fires again: swap to `active_plan: 2`, same dance for plan `c`
4. After plan `c` Step 0 succeeds, Step -1 finds no next entry → proceed to Step 1 (Final Docs Updater for the whole chain)

---

## 5. Three-plan chain with natural-language model override

Args:
```
/kws-claude-multi-agent-executor plan=plans/a.md spec=specs/a.spec plan2=plans/b.md spec2=specs/b.spec plan3=plans/c.md spec3=specs/c.spec 오푸스로 순차적으로 진행해줘
```

Echo:
```
Parsed: 3 plans [a→b→c], implementer_model=opus [NL '오푸스'], parallel=off [NL '순차'], mode=headless [default], risk=per-task.
```

The model selection propagates to every plan in the chain (run-level, not per-plan).

---

## 6. Conflict — explicit + NL contradicting

Args:
```
/kws-claude-multi-agent-executor plan=plans/a.md spec=specs/a.spec implementer_model=sonnet 오푸스로 진행해줘
```

Halt with:
```
Argument conflict: explicit implementer_model=sonnet contradicts natural-language '오푸스' (→ implementer_model=opus). Remove one or align them.
```

---

## 7. Conflict — two NL tokens for the same key

Args:
```
/kws-claude-multi-agent-executor plan=plans/a.md spec=specs/a.spec 처음엔 opus 좀 보고 다시 sonnet으로 해보자
```

Halt with:
```
Natural-language conflict: 'opus' (→ implementer_model=opus) and 'sonnet' (→ implementer_model=sonnet) both target implementer_model. Disambiguate explicitly.
```

---

## 8. Plan index gap

Args:
```
/kws-claude-multi-agent-executor plan=plans/a.md spec=specs/a.spec plan3=plans/c.md spec3=specs/c.spec
```

Halt with:
```
Plan index gap: expected plan2= but only plan, plan3 provided. Renumber consecutively or fill the gap.
```

---

## 9. Plan without matching spec

Args:
```
/kws-claude-multi-agent-executor plan=plans/a.md spec=specs/a.spec plan2=plans/b.md
```

Halt with:
```
plan2= present but spec2= missing
```

---

## 10. False-positive guard — path containing "opus"

Args:
```
/kws-claude-multi-agent-executor plan=plans/opus-migration.md spec=specs/opus-migration.spec
```

Echo:
```
Parsed: 1 plan [opus-migration], implementer_model=sonnet [default], parallel=on [default], mode=headless [default], risk=per-task.
```

The `plans/opus-migration.md` token contains `/` and `.`, so it's excluded from NL scanning. The model is NOT set to opus.

---

## 11. NL keyword agrees with explicit — no-op (logged)

Args:
```
/kws-claude-multi-agent-executor plan=plans/a.md spec=specs/a.spec implementer_model=opus 오푸스로 가자
```

Echo:
```
Parsed: 1 plan [a], implementer_model=opus [explicit; NL '오푸스' agrees], parallel=on [default], mode=headless [default], risk=per-task.
```

No conflict, no halt. The echo logs the agreement explicitly so the user knows both signals were considered.

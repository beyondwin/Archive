# Source Matching Runtime Trust Fixtures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Add runtime source matching trust fixtures without weakening source-index fixtures.

## File Structure

- Modify `package.json`.
- Modify `scripts/source-matching-fixtures.mjs`.
- Modify `scripts/source-matching-fixtures-test.mjs`.
- Modify `fixtures/source-matching/manifest.json`.
- Create `fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture/RuntimeTrustFixtureModels.kt`.
- Create `fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture/RuntimeTrustFixtureRunner.kt`.
- Modify `docs/guides/source-matching-fixture-lab.md`.

### Task 1: Contract Cleanup

**Files:**
- Modify: `package.json`
- Modify: `fixtures/source-matching/manifest.json`
- Modify: `scripts/source-matching-fixtures.mjs`
- Modify: `scripts/source-matching-fixtures-test.mjs`

- [ ] **Step 1: Write failing package and manifest tests**

```javascript
test("package.json exposes runtime source matching fixture script", () => {
  const pkg = readJson("package.json");
  assert.equal(pkg.scripts["source-matching:fixtures:runtime"], "node scripts/source-matching-fixtures.mjs runtime");
});
```

```json
{
  "id": "reply-compose-fab-runtime",
  "mode": "runtime-trust",
  "runtimeTarget": { "text": "Compose", "role": "Button" },
  "expectedTop3PathContains": "ReplyListContent.kt"
}
```

Run:

```bash
npm run source-matching:fixtures:test
```

Expected: FAIL before the runtime script exists.

- [ ] **Step 2: Commit contract cleanup**

```bash
git add package.json fixtures/source-matching/manifest.json scripts/source-matching-fixtures.mjs scripts/source-matching-fixtures-test.mjs
git commit -m "feat: split source matching fixture contracts"
```

### Task 2: Runtime Runner Mapping

**Files:**
- Create: `fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture/RuntimeTrustFixtureModels.kt`
- Create: `fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture/RuntimeTrustFixtureRunner.kt`

- [ ] **Step 1: Add Kotlin DTO examples**

```kotlin
@Serializable
data class RuntimeTrustFixtureInput(
    val applicationId: String,
    val target: RuntimeTarget,
)
```

```kotlin
fun resultLabel(found: Boolean): String {
    return if (found) "runtime_trust_observed" else "target_not_found"
}
```

Run:

```bash
./gradlew :fixthis-mcp:test --tests "*RuntimeTrustFixtureRunnerTest" --no-daemon
```

Expected: PASS after the runner tests are implemented.

- [ ] **Step 2: Commit runtime mapping**

```bash
git add fixthis-mcp/src/main/kotlin/io/github/beyondwin/fixthis/mcp/fixture
git commit -m "feat: add runtime trust fixture runner"
```

### Task 3: Documentation And Final Verification

**Files:**
- Modify: `docs/guides/source-matching-fixture-lab.md`

- [ ] **Step 1: Document commands**

```markdown
Runtime fixture commands:
- `npm run source-matching:fixtures:runtime`
- `npm run source-matching:fixtures:runtime -- --strict`
```

- [ ] **Step 2: Run final checks**

```bash
npm run source-matching:fixtures:test
./gradlew :fixthis-compose-core:test --tests "*SourceMatcherTest" --tests "*TargetReliabilityCalculatorTest" --no-daemon
./gradlew :fixthis-mcp:test --tests "*TargetEvidenceServiceTest" --tests "*RuntimeTrustFixtureRunnerTest" --no-daemon
./gradlew spotlessCheck --no-daemon
git diff --check
graphify update .
git status --short --branch
command -v adb || true
```

Expected: default checks pass; `adb` absence is a non-blocking optional environment finding.

- [ ] **Step 3: Optional runtime strict check**

```bash
npm run source-matching:fixtures:runtime
npm run source-matching:fixtures:runtime -- --strict
```

Expected: strict mode may fail without a connected Android device.

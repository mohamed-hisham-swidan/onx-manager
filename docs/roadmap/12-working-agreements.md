# MCS Manager — Working Agreements (Contribution Workflow)

**Part IX** of the Engineering Blueprint V4. The collaborative rules that govern *how* code and
documentation get built in this repository — contribution workflow, commit strategy, and
AI-collaboration rules. This file is the human- and agent-readable codification of the same rules
that `.ai/AI_RULES.md`, `AGENTS.md`, and ADR-0010 already state in operational form; the blueprint
places them in one place, labeled as the *agreement* they are.

**Last updated:** 2026-08-06
**Supersedes:** the "Volume 11: Working Agreements" section of the prior V4 roadmap (referenced but
not present in surviving text — this file is written fresh from the rules that *are* present and
active in the repository today).

---

## 1. Contribution workflow

### 1.1 The plan governs

Work is sequenced by **roadmap phase**, not by request convenience (`.ai/AI_RULES.md` — Governing
Plan). A request that does not help close the current phase's exit criteria belongs in a later
phase's backlog, not in current work. Phase gating is enforced: nothing in Phase 2+ starts until
Phase 1's exit criteria are met, and so on (`04`–`07`).

### 1.2 Bootstrap before work

Before any work begins, the entry-point files are read in order (`AGENTS.md`): `.ai/AI_RULES.md`,
`.ai/TOKEN_POLICY.md`, `.ai/CURRENT_STATE.json`, `.ai/PROJECT_STATE.json`. Then task-specific files
only. Reading discipline is context-budget-driven (`.ai/TOKEN_POLICY.md`): read only what the task
requires, use targeted reads, and never load entire files on speculation.

### 1.3 Ask when uncertain

If the task, the files to modify, commit policy, testing requirements, or scope boundaries are
unclear — **stop and ask the user.** Do not guess. This is an explicit agreement, not a preference
(`.ai/AI_RULES.md` — Decision Uncertainty; `AGENTS.md` Step 3).

### 1.4 Evidence before assertion

Nothing is stated as fact without evidence: source code, repository state, git history, docs, test
results, or user-provided information. If evidence is insufficient, say "insufficient evidence" —
never guess (`.ai/AI_RULES.md` — Evidence Rule; Part I §1).

---

## 2. Commit strategy

### 2.1 Default: do not commit

By default **DO NOT COMMIT** (`.ai/AI_RULES.md` — Commit Policy). A commit happens only if the user
explicitly requests it, or the task/repository workflow requires it. Otherwise: prepare the commit
message, show what would be committed, and **wait for confirmation**. Editing files is not permission
to commit.

### 2.2 Commit-per-step discipline

Every commit represents exactly **one logical change** (ADR-0010). Each commit must be immediately
verifiable (tests pass, app boots); no bundling of unrelated changes; the message explains *what, why,
and how verified*. Never `git add .` unless explicitly requested — stage only relevant files.

### 2.3 What that means during phases

- A structural/organizational/bug-fix change is one commit per step (ADR-0010).
- Unrelated files are never included even if trivially fixable (`.ai/AI_RULES.md` — Scope Control).
- An open working-tree diff against a "done" phase is a defect in the close-out, not a norm (see D3,
  `11` §3).

---

## 3. Quality and self-review

### 3.1 Self-review before continuing

Every modification is reviewed before moving on: logic, edge cases, consistency, readability, dead
code, duplicate code, imports, naming. Fix your own mistakes before proceeding
(`.ai/AI_RULES.md` — Self Review).

### 3.2 Test selection

Tests are chosen as the **minimum required verification** for the change class
(`.ai/AI_RULES.md` — Test Selection): docs-only → none; config → affected validation; code → relevant
tests; behavior → regression; architecture → affected suites. Do **not** run unrelated tests.

### 3.3 Regression protection

Every fixed bug receives a regression test. If no code changed, regression tests are not required
(`.ai/AI_RULES.md` — Regression Tests). This is the operational form of the quality gate's
"verification, not declaration" rule (Part III §4.4).

### 3.4 Documentation

Documentation is updated **only if** public behavior, API, architecture, user workflow,
configuration, a known limitation, or project status changed. Otherwise, report "no documentation
update required." Never rewrite unrelated documentation (`.ai/AI_RULES.md` — Documentation).

---

## 4. AI-collaboration rules

### 4.1 AI is a contributor, not a narrator

AI agents work under the same scope, evidence, self-review, and commit rules as any contributor.
The blueprint is not "about" AI; it is the shared contract AI operates under.

### 4.2 Rule inheritance and self-modification

- If `.ai/AI_RULES.md` is modified during a task, the new rules become active **only after the
  current task finishes**; they are never retroactively applied (Rule Inheritance).
- Editing `.ai/AI_RULES.md` (or this file) is normal repo work: not auto-committed, not auto-activated
  mid-task, and subject to the same commit policy as any other change (Self-Modifying Rules).

### 4.3 The "ask, don't assume" discipline is strongest for AI

Because AI is prone to confidently guessing, the Ask-When-Uncertain agreement (§1.3) is absolute for
agents: ambiguous tasks → present options, ask; uncertain commits → ask; uncertain file scope → ask
(`.ai/AI_RULES.md` — Ambiguity Policy, Decision Uncertainty).

### 4.4 AI and this blueprint

- An AI agent must read the blueprint's relevant Part before working in its domain (per §1.2
  bootstrap), and must not treat Part IV (non-committed vision, `09`/`10`) as committed scope.
- The re-verification discipline (Part I §1, Phase 6 `06` §2.4) means an AI agent may not claim a
  number is current without re-checking it live.
- Future AI *product* features (Phase 10) are governed by `07` §4.1's guardrails; nothing in this
  file changes those.

---

## 5. Preservation

- History is append-only (Part I §9): audit rows, event-store rows, ADRs, decision records, and
  roadmap status markers are never deleted or silently changed.
- Roadmap status markers are authoritative for phase state; a marker is not changed without updating
  `docs/STATUS.md`/`current-state.md` accordingly (`.ai/AI_RULES.md` — Governing Plan).
- Historical docs (v1–v3, V4 linear volumes) are preserved and labeled as history, never silently
  deleted.

---

*This completes the Engineering Blueprint V4. Return to [`00-index-and-vision.md`](./00-index-and-vision.md)
for the index and file map, or consult `04` for the current phase.*
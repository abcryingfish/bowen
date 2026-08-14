# Ignore Node Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop tracking every `node_modules` directory while preserving installed dependencies in the local working tree.

**Architecture:** Add one repository-wide ignore rule in the root `.gitignore`, then remove the two known dependency trees from the Git index with `git rm --cached`. Validate ignore matching, index state, local file preservation, repository integrity, and remote synchronization.

**Tech Stack:** Git, `.gitignore`, PowerShell

---

### Task 1: Ignore and untrack Node.js dependencies

**Files:**
- Modify: `.gitignore`
- Reference: `docs/superpowers/specs/2026-07-31-ignore-node-modules-design.md`

- [ ] **Step 1: Verify the current ignore rule does not cover node_modules**

Run:

```powershell
git check-ignore --no-index -- "可视化/vue-app/node_modules/@esbuild/win32-x64/esbuild.exe"
```

Expected: exit code `1` with no matching ignore rule.

- [ ] **Step 2: Add the repository-wide ignore rule**

Append this UTF-8 line to the root `.gitignore`:

```gitignore
node_modules/
```

- [ ] **Step 3: Verify both dependency trees are ignored**

Run:

```powershell
git check-ignore -v --no-index -- "可视化/vue-app/node_modules/@esbuild/win32-x64/esbuild.exe"
git check-ignore -v --no-index -- "outputs/stock_universe_xlsx_build/node_modules/.modules.yaml"
```

Expected: both commands identify the new `.gitignore` rule.

- [ ] **Step 4: Remove tracked dependency files from the Git index only**

Run:

```powershell
git rm -r --cached -- "可视化/vue-app/node_modules" "outputs/stock_universe_xlsx_build/node_modules"
```

Expected: tracked dependency files are staged as deletions; local directories remain present.

- [ ] **Step 5: Verify index cleanup and local preservation**

Run:

```powershell
$tracked = @(git ls-files | Where-Object { $_ -match '(^|/)node_modules/' })
$tracked.Count
Test-Path -LiteralPath "可视化/vue-app/node_modules/@esbuild/win32-x64/esbuild.exe"
Test-Path -LiteralPath "outputs/stock_universe_xlsx_build/node_modules/.modules.yaml"
git diff --cached --check
```

Expected: tracked count is `0`, both `Test-Path` results are `True`, and `git diff --cached --check` exits `0`.

- [ ] **Step 6: Commit the cleanup**

Run:

```powershell
git add -- .gitignore
git commit -m "chore: stop tracking node_modules"
```

Expected: one commit containing the ignore rule and staged dependency deletions.

- [ ] **Step 7: Verify and push**

Run:

```powershell
git status --short --branch
git fsck --no-dangling
git push origin main
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

Expected: the working tree is clean, repository integrity passes, push succeeds, and local/remote commit hashes match.

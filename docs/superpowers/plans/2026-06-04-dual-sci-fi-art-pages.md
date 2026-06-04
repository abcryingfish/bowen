# Dual Sci-Fi Art Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build two independent interactive art webpages inside `筹码分布可视化`: a 3D explorable temple and a 2D living control altar.

**Architecture:** Keep the new work isolated from the existing chip-distribution files by creating new HTML entry points plus a dedicated `assets` tree. Use ES modules with a small shared runtime, a pure-state layer that can be unit-tested with Node, `Three.js` for the 3D world, and layered `Canvas` rendering for the 2D control surface.

**Tech Stack:** Static HTML, CSS, ES modules, `Three.js` from pinned CDN imports, HTML Canvas 2D, Node 24 built-in test runner, Python `http.server`, Codex in-app browser for visual verification.

---

## File Map

**Create**

- `筹码分布可视化/package.json`
- `筹码分布可视化/void-temple.html`
- `筹码分布可视化/signal-altar.html`
- `筹码分布可视化/assets/css/shared.css`
- `筹码分布可视化/assets/css/void-temple.css`
- `筹码分布可视化/assets/css/signal-altar.css`
- `筹码分布可视化/assets/js/shared/animation-clock.js`
- `筹码分布可视化/assets/js/shared/phase-system.js`
- `筹码分布可视化/assets/js/shared/input-controller.js`
- `筹码分布可视化/assets/js/shared/viewport-adapter.js`
- `筹码分布可视化/assets/js/shared/audio-toggle.js`
- `筹码分布可视化/assets/js/void-temple/app.js`
- `筹码分布可视化/assets/js/void-temple/scene-builder.js`
- `筹码分布可视化/assets/js/void-temple/temple-state-machine.js`
- `筹码分布可视化/assets/js/void-temple/temple-interactions.js`
- `筹码分布可视化/assets/js/void-temple/temple-effects.js`
- `筹码分布可视化/assets/js/signal-altar/app.js`
- `筹码分布可视化/assets/js/signal-altar/altar-state-machine.js`
- `筹码分布可视化/assets/js/signal-altar/altar-renderer.js`
- `筹码分布可视化/assets/js/signal-altar/altar-interactions.js`
- `筹码分布可视化/assets/js/signal-altar/altar-effects.js`
- `筹码分布可视化/tests/shared-runtime.test.mjs`
- `筹码分布可视化/tests/temple-state-machine.test.mjs`
- `筹码分布可视化/tests/altar-state-machine.test.mjs`

**Modify**

- None of the existing chip-distribution HTML files.

## Task 1: Bootstrap The New Art Workspace

**Files:**

- Create: `筹码分布可视化/package.json`
- Create: `筹码分布可视化/void-temple.html`
- Create: `筹码分布可视化/signal-altar.html`
- Create: `筹码分布可视化/assets/css/shared.css`
- Create: `筹码分布可视化/assets/css/void-temple.css`
- Create: `筹码分布可视化/assets/css/signal-altar.css`

- [ ] **Step 1: Create the folder structure**

Run:

```powershell
New-Item -ItemType Directory -Force `
  'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化/assets/css' `
  'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化/assets/js/shared' `
  'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化/assets/js/void-temple' `
  'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化/assets/js/signal-altar' `
  'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化/tests'
```

Expected: PowerShell creates the directories with no errors.

- [ ] **Step 2: Add an ESM package marker for browser-testable modules**

Write:

```json
{
  "name": "dual-sci-fi-art-pages",
  "private": true,
  "type": "module"
}
```

to `筹码分布可视化/package.json`.

- [ ] **Step 3: Add minimal HTML shells that load local modules**

Write `void-temple.html` with:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Void Temple</title>
    <link rel="stylesheet" href="./assets/css/shared.css" />
    <link rel="stylesheet" href="./assets/css/void-temple.css" />
  </head>
  <body class="experience-body">
    <div class="hud minimal-hud" aria-hidden="true">
      <button class="icon-button sound-toggle" data-sound-toggle></button>
      <button class="icon-button reset-trigger" data-reset-scene></button>
      <button class="icon-button fullscreen-trigger" data-fullscreen></button>
    </div>
    <canvas id="temple-canvas"></canvas>
    <script type="module" src="./assets/js/void-temple/app.js"></script>
  </body>
</html>
```

Write `signal-altar.html` with:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Signal Altar</title>
    <link rel="stylesheet" href="./assets/css/shared.css" />
    <link rel="stylesheet" href="./assets/css/signal-altar.css" />
  </head>
  <body class="experience-body">
    <div class="hud minimal-hud" aria-hidden="true">
      <button class="icon-button sound-toggle" data-sound-toggle></button>
      <button class="icon-button reset-trigger" data-reset-scene></button>
      <button class="icon-button fullscreen-trigger" data-fullscreen></button>
    </div>
    <canvas id="altar-canvas"></canvas>
    <script type="module" src="./assets/js/signal-altar/app.js"></script>
  </body>
</html>
```

- [ ] **Step 4: Add shared and page CSS shells**

Write `shared.css` with:

```css
:root {
  color-scheme: dark;
  --bg: #04050a;
  --panel: rgba(9, 13, 24, 0.48);
  --line: rgba(191, 244, 255, 0.32);
  --glow-cyan: #3df6ff;
  --glow-magenta: #ff4fd8;
  --glow-gold: #ffcf59;
  --glow-lime: #b4ff5e;
}

* { box-sizing: border-box; }
html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; background: var(--bg); }
.experience-body { position: relative; font-family: Inter, "Segoe UI", sans-serif; }
canvas { width: 100%; height: 100%; display: block; }
.minimal-hud {
  position: fixed;
  top: 18px;
  right: 18px;
  display: flex;
  gap: 10px;
  z-index: 20;
}
.icon-button {
  width: 42px;
  height: 42px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  backdrop-filter: blur(10px);
}
```

Write `void-temple.css` with a deep-space background and subtle vignette pseudo-element.  
Write `signal-altar.css` with a denser layered background grid and radial mask.

- [ ] **Step 5: Open the raw HTML files once to catch broken imports early**

Run:

```powershell
Get-Content 'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化/void-temple.html' | Select-Object -First 5
Get-Content 'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化/signal-altar.html' | Select-Object -First 5
```

Expected: Both files exist and reference the expected CSS and JS paths.

## Task 2: Build Shared Runtime Utilities With Tests

**Files:**

- Create: `筹码分布可视化/assets/js/shared/animation-clock.js`
- Create: `筹码分布可视化/assets/js/shared/phase-system.js`
- Create: `筹码分布可视化/assets/js/shared/input-controller.js`
- Create: `筹码分布可视化/assets/js/shared/viewport-adapter.js`
- Create: `筹码分布可视化/assets/js/shared/audio-toggle.js`
- Create: `筹码分布可视化/tests/shared-runtime.test.mjs`

- [ ] **Step 1: Write the failing shared-runtime tests**

Write:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { createPhaseSystem } from '../assets/js/shared/phase-system.js';
import { getViewportProfile } from '../assets/js/shared/viewport-adapter.js';

test('phase system promotes at configured thresholds', () => {
  const phases = createPhaseSystem([
    { name: 'Dormant', threshold: 0 },
    { name: 'Awakening', threshold: 2 },
    { name: 'Reconfiguration', threshold: 5 },
  ]);

  phases.recordProgress(2);
  assert.equal(phases.current.name, 'Awakening');
  phases.recordProgress(3);
  assert.equal(phases.current.name, 'Reconfiguration');
});

test('viewport profile lowers density on touch devices', () => {
  const profile = getViewportProfile({ width: 390, height: 844, touch: true, devicePixelRatio: 3 });
  assert.equal(profile.mode, 'mobile');
  assert.equal(profile.densityScale < 1, true);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
Set-Location 'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化'
node --test ./tests/shared-runtime.test.mjs
```

Expected: FAIL because the shared modules do not exist yet.

- [ ] **Step 3: Implement the minimal shared modules**

Write `phase-system.js` with:

```js
export function createPhaseSystem(phases) {
  let progress = 0;
  let current = phases[0];
  return {
    get current() { return current; },
    get progress() { return progress; },
    recordProgress(amount = 1) {
      progress += amount;
      current = phases.filter((phase) => progress >= phase.threshold).at(-1) ?? phases[0];
      return current;
    },
    reset() {
      progress = 0;
      current = phases[0];
    },
  };
}
```

Write `viewport-adapter.js` with:

```js
export function getViewportProfile({ width, height, touch, devicePixelRatio }) {
  const mobile = touch || width < 900;
  const cappedDpr = Math.min(devicePixelRatio || 1, mobile ? 1.75 : 2);
  return {
    mode: mobile ? 'mobile' : 'desktop',
    pixelRatio: cappedDpr,
    densityScale: mobile ? 0.58 : 1,
    bloomScale: mobile ? 0.72 : 1,
    shortSide: Math.min(width, height),
  };
}
```

Write `animation-clock.js`, `input-controller.js`, and `audio-toggle.js` as small single-purpose helpers that expose:

- `createAnimationClock(update)`
- `createPointerTracker(target)`
- `createKeyboardTracker(target)`
- `createAudioToggle(button)`

- [ ] **Step 4: Re-run the tests**

Run:

```powershell
Set-Location 'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化'
node --test ./tests/shared-runtime.test.mjs
```

Expected: PASS with 2 passing tests.

- [ ] **Step 5: Commit the shared runtime**

Run:

```powershell
git -C 'C:/Users/Administrator/Desktop/python_venv' add -- `
  '筹码分布可视化/package.json' `
  '筹码分布可视化/assets/css/shared.css' `
  '筹码分布可视化/assets/js/shared' `
  '筹码分布可视化/tests/shared-runtime.test.mjs' `
  '筹码分布可视化/void-temple.html' `
  '筹码分布可视化/signal-altar.html'
git -C 'C:/Users/Administrator/Desktop/python_venv' -c user.name='Codex' -c user.email='codex@local' commit -m "Build shared sci-fi art runtime"
```

## Task 3: Implement The 3D Temple State Layer And Scene

**Files:**

- Create: `筹码分布可视化/assets/js/void-temple/temple-state-machine.js`
- Create: `筹码分布可视化/assets/js/void-temple/scene-builder.js`
- Create: `筹码分布可视化/assets/js/void-temple/temple-effects.js`
- Create: `筹码分布可视化/assets/js/void-temple/temple-interactions.js`
- Create: `筹码分布可视化/assets/js/void-temple/app.js`
- Create: `筹码分布可视化/tests/temple-state-machine.test.mjs`
- Modify: `筹码分布可视化/assets/css/void-temple.css`

- [ ] **Step 1: Write the failing temple state test**

Write:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { createTempleStateMachine } from '../assets/js/void-temple/temple-state-machine.js';

test('temple reaches ascended after four node activations', () => {
  const temple = createTempleStateMachine();
  temple.activateNode('north');
  temple.activateNode('south');
  temple.activateNode('east');
  const result = temple.activateNode('west');
  assert.equal(result.phase.name, 'Ascended');
  assert.equal(temple.state.activatedCount, 4);
});
```

- [ ] **Step 2: Run the temple test and confirm failure**

Run:

```powershell
Set-Location 'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化'
node --test ./tests/temple-state-machine.test.mjs
```

Expected: FAIL because `createTempleStateMachine` does not exist yet.

- [ ] **Step 3: Implement the state machine**

Write `temple-state-machine.js` with:

```js
import { createPhaseSystem } from '../shared/phase-system.js';

const NODE_ORDER = ['north', 'south', 'east', 'west'];

export function createTempleStateMachine() {
  const phases = createPhaseSystem([
    { name: 'Dormant', threshold: 0 },
    { name: 'Awakening', threshold: 1 },
    { name: 'Reconfiguration', threshold: 3 },
    { name: 'Ascended', threshold: 4 },
  ]);

  const state = {
    activatedNodes: new Set(),
    activatedCount: 0,
    gateOpen: false,
    worldPulse: 0,
  };

  return {
    state,
    activateNode(nodeId) {
      if (!NODE_ORDER.includes(nodeId) || state.activatedNodes.has(nodeId)) {
        return { phase: phases.current, state };
      }
      state.activatedNodes.add(nodeId);
      state.activatedCount = state.activatedNodes.size;
      const phase = phases.recordProgress(1);
      state.gateOpen = state.activatedCount >= 3;
      state.worldPulse = state.activatedCount / NODE_ORDER.length;
      return { phase, state };
    },
    reset() {
      state.activatedNodes.clear();
      state.activatedCount = 0;
      state.gateOpen = false;
      state.worldPulse = 0;
      phases.reset();
    },
    get phase() {
      return phases.current;
    },
  };
}
```

- [ ] **Step 4: Re-run the state test**

Run:

```powershell
Set-Location 'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化'
node --test ./tests/temple-state-machine.test.mjs
```

Expected: PASS with 1 passing test.

- [ ] **Step 5: Build the real 3D scene**

Implement:

- `scene-builder.js` to create renderer, scene, camera, fog, reflective floor, starfield, four monolith nodes, ring arrays, bridge arcs, and a nested core group.
- `temple-effects.js` to animate core deformation, orbit speed, particle waterfalls, and phase color changes.
- `temple-interactions.js` to map pointer/keyboard movement, proximity checks, node activation, reset, and mobile drag navigation.
- `app.js` to compose the scene, state machine, viewport profile, shared clock, sound toggle, full-screen button, and resize handling.

Pinned import style:

```js
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';
```

Verification behavior:

- The page opens into a true 3D scene.
- Four nodes can be activated.
- The world visibly reconfigures at the third and fourth activation thresholds.

- [ ] **Step 6: Smoke-run the temple page**

Run:

```powershell
Set-Location 'C:/Users/Administrator/Desktop/python_venv'
.venv/Scripts/python.exe -m http.server 8766 --directory 'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化'
```

Then open `http://127.0.0.1:8766/void-temple.html` in the in-app browser and confirm the canvas is nonblank and interactive.

- [ ] **Step 7: Commit the 3D page**

Run:

```powershell
git -C 'C:/Users/Administrator/Desktop/python_venv' add -- '筹码分布可视化/assets/js/void-temple' '筹码分布可视化/assets/css/void-temple.css' '筹码分布可视化/tests/temple-state-machine.test.mjs'
git -C 'C:/Users/Administrator/Desktop/python_venv' -c user.name='Codex' -c user.email='codex@local' commit -m "Add void temple 3D page"
```

## Task 4: Implement The 2D Altar State Layer And Renderer

**Files:**

- Create: `筹码分布可视化/assets/js/signal-altar/altar-state-machine.js`
- Create: `筹码分布可视化/assets/js/signal-altar/altar-renderer.js`
- Create: `筹码分布可视化/assets/js/signal-altar/altar-effects.js`
- Create: `筹码分布可视化/assets/js/signal-altar/altar-interactions.js`
- Create: `筹码分布可视化/assets/js/signal-altar/app.js`
- Create: `筹码分布可视化/tests/altar-state-machine.test.mjs`
- Modify: `筹码分布可视化/assets/css/signal-altar.css`

- [ ] **Step 1: Write the failing altar state test**

Write:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { createAltarStateMachine } from '../assets/js/signal-altar/altar-state-machine.js';

test('altar enters ascended after overload plus enough links', () => {
  const altar = createAltarStateMachine();
  altar.activateNode('a1');
  altar.activateNode('a2');
  altar.linkNodes('a1', 'a2');
  altar.activateNode('a3');
  altar.linkNodes('a2', 'a3');
  const result = altar.triggerOverload();
  assert.equal(result.phase.name, 'Ascended');
});
```

- [ ] **Step 2: Run the altar test and confirm failure**

Run:

```powershell
Set-Location 'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化'
node --test ./tests/altar-state-machine.test.mjs
```

Expected: FAIL because the module does not exist yet.

- [ ] **Step 3: Implement the altar state machine**

Write `altar-state-machine.js` with:

```js
import { createPhaseSystem } from '../shared/phase-system.js';

export function createAltarStateMachine() {
  const phases = createPhaseSystem([
    { name: 'Dormant', threshold: 0 },
    { name: 'Awakening', threshold: 2 },
    { name: 'Reconfiguration', threshold: 5 },
    { name: 'Ascended', threshold: 7 },
  ]);

  const state = {
    activeNodes: new Set(),
    links: [],
    overloadCount: 0,
  };

  return {
    state,
    activateNode(nodeId) {
      if (!state.activeNodes.has(nodeId)) {
        state.activeNodes.add(nodeId);
        phases.recordProgress(1);
      }
      return { phase: phases.current, state };
    },
    linkNodes(from, to) {
      state.links.push([from, to]);
      phases.recordProgress(1);
      return { phase: phases.current, state };
    },
    triggerOverload() {
      state.overloadCount += 1;
      phases.recordProgress(2);
      return { phase: phases.current, state };
    },
    reset() {
      state.activeNodes.clear();
      state.links = [];
      state.overloadCount = 0;
      phases.reset();
    },
    get phase() {
      return phases.current;
    },
  };
}
```

- [ ] **Step 4: Re-run the altar test**

Run:

```powershell
Set-Location 'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化'
node --test ./tests/altar-state-machine.test.mjs
```

Expected: PASS with 1 passing test.

- [ ] **Step 5: Build the 2D renderer and interactions**

Implement:

- `altar-renderer.js` for multilayer canvas drawing: central phase disk, ring stacks, node lattice, wave pools, scan lines, moire interference, transient energy links, and a final star-map bloom layer.
- `altar-effects.js` for eased oscillations, palette morphing, ring ripples, and overload shockwaves.
- `altar-interactions.js` for drag-to-rotate, node hit-testing, drag-link creation, long-press overload, and reset behavior.
- `app.js` for canvas sizing, DPR scaling, animation loop, state progression, control hooks, and mobile density reduction.

Verification behavior:

- The interface reacts immediately to drag and click.
- Activated nodes and links persist visually.
- Overload triggers an unmistakable full-screen reconfiguration.

- [ ] **Step 6: Smoke-run the altar page**

Open `http://127.0.0.1:8766/signal-altar.html` in the in-app browser and confirm the canvas is nonblank, layered, and interactive.

- [ ] **Step 7: Commit the 2D page**

Run:

```powershell
git -C 'C:/Users/Administrator/Desktop/python_venv' add -- '筹码分布可视化/assets/js/signal-altar' '筹码分布可视化/assets/css/signal-altar.css' '筹码分布可视化/tests/altar-state-machine.test.mjs'
git -C 'C:/Users/Administrator/Desktop/python_venv' -c user.name='Codex' -c user.email='codex@local' commit -m "Add signal altar 2D page"
```

## Task 5: Verify, Tune, And Deliver

**Files:**

- Modify as needed: all new files under `筹码分布可视化/`

- [ ] **Step 1: Run the full automated test set**

Run:

```powershell
Set-Location 'C:/Users/Administrator/Desktop/python_venv/筹码分布可视化'
node --test ./tests/*.test.mjs
```

Expected: PASS with all shared, temple, and altar tests green.

- [ ] **Step 2: Verify both pages in the in-app browser**

Check:

- `http://127.0.0.1:8766/void-temple.html`
- `http://127.0.0.1:8766/signal-altar.html`

Desktop verification:

- The first frame is visually strong.
- Both pages are nearly text-free.
- The 3D page supports exploration and phase changes.
- The 2D page supports rotation, node activation, link drawing, and overload.

Mobile verification:

- The layout still fills the screen.
- Inputs still work on a touch-sized viewport.
- Density is reduced but the experience still feels rich.

- [ ] **Step 3: Fix any visual or interaction regressions found during verification**

Edit the exact files that fail the checks above, then re-run both the automated tests and browser verification.

- [ ] **Step 4: Commit the finished art pages**

Run:

```powershell
git -C 'C:/Users/Administrator/Desktop/python_venv' add -- '筹码分布可视化'
git -C 'C:/Users/Administrator/Desktop/python_venv' -c user.name='Codex' -c user.email='codex@local' commit -m "Finish dual sci-fi art pages"
```

- [ ] **Step 5: Report the local URLs**

Report:

- `http://127.0.0.1:8766/void-temple.html`
- `http://127.0.0.1:8766/signal-altar.html`

## Self-Review

- Spec coverage: Task 1 establishes the independent dual-page structure; Task 2 builds the shared runtime and performance profile hooks; Task 3 implements the 3D page; Task 4 implements the 2D page; Task 5 verifies visual strength, interaction depth, low-text presentation, and responsive behavior.
- Placeholder scan: No `TBD`, `TODO`, or deferred “implement later” markers remain in the plan.
- Type consistency: Both page state machines expose `phase`, `reset()`, and action methods that the page apps can compose consistently.

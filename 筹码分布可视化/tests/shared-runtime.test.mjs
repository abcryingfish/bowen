import test from "node:test";
import assert from "node:assert/strict";
import { createPhaseSystem } from "../assets/js/shared/phase-system.js";
import { getViewportProfile } from "../assets/js/shared/viewport-adapter.js";

test("phase system promotes at configured thresholds", () => {
  const phases = createPhaseSystem([
    { name: "Dormant", threshold: 0 },
    { name: "Awakening", threshold: 2 },
    { name: "Reconfiguration", threshold: 5 },
  ]);

  phases.recordProgress(2);
  assert.equal(phases.current.name, "Awakening");
  phases.recordProgress(3);
  assert.equal(phases.current.name, "Reconfiguration");
});

test("viewport profile lowers density on touch devices", () => {
  const profile = getViewportProfile({ width: 390, height: 844, touch: true, devicePixelRatio: 3 });
  assert.equal(profile.mode, "mobile");
  assert.equal(profile.densityScale < 1, true);
});

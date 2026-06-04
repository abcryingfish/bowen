import { createPhaseSystem } from "../shared/phase-system.js";

const NODE_ORDER = ["north", "south", "east", "west"];

export function createTempleStateMachine() {
  const phases = createPhaseSystem([
    { name: "Dormant", threshold: 0 },
    { name: "Awakening", threshold: 1 },
    { name: "Reconfiguration", threshold: 3 },
    { name: "Ascended", threshold: 4 },
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

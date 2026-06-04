import { createPhaseSystem } from "../shared/phase-system.js";

export function createAltarStateMachine() {
  const phases = createPhaseSystem([
    { name: "Dormant", threshold: 0 },
    { name: "Awakening", threshold: 2 },
    { name: "Reconfiguration", threshold: 5 },
    { name: "Ascended", threshold: 7 },
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
      const duplicate = state.links.some(([a, b]) => (a === from && b === to) || (a === to && b === from));
      if (!duplicate) {
        state.links.push([from, to]);
        phases.recordProgress(1);
      }
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

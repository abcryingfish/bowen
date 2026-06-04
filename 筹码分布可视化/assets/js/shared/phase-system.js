export function createPhaseSystem(phases) {
  let progress = 0;
  let current = phases[0];

  return {
    get current() {
      return current;
    },
    get progress() {
      return progress;
    },
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

export function createAnimationClock(update) {
  let frameId = null;
  let lastTime = performance.now();
  let running = false;

  function tick(now) {
    if (!running) {
      return;
    }
    const deltaMs = now - lastTime;
    lastTime = now;
    update({
      now,
      deltaMs,
      deltaSeconds: deltaMs / 1000,
    });
    frameId = requestAnimationFrame(tick);
  }

  return {
    start() {
      if (running) {
        return;
      }
      running = true;
      lastTime = performance.now();
      frameId = requestAnimationFrame(tick);
    },
    stop() {
      running = false;
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
        frameId = null;
      }
    },
  };
}

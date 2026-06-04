function findNode(nodes, x, y) {
  return nodes.find((node) => {
    const dx = x - node.x;
    const dy = y - node.y;
    return Math.hypot(dx, dy) <= node.radius * 1.5;
  }) ?? null;
}

export function createAltarInteractions({ canvas, altar, getMetrics, audioToggle }) {
  const view = {
    rotation: 0,
    energy: 0.12,
    shockwaves: [],
  };

  const state = {
    draggingCore: false,
    sourceNodeId: null,
    overloadTimer: null,
    pointerOrigin: null,
  };

  function reset() {
    view.rotation = 0;
    view.energy = 0.12;
    view.shockwaves = [];
    state.draggingCore = false;
    state.sourceNodeId = null;
    clearTimeout(state.overloadTimer);
    state.overloadTimer = null;
  }

  function pushShockwave() {
    const metrics = getMetrics();
    view.shockwaves.push({
      baseRadius: metrics.coreRadius * 1.2,
      range: metrics.shortSide * 0.42,
      progress: 0,
    });
  }

  canvas.addEventListener("pointerdown", (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const metrics = getMetrics(view.rotation);
    const dx = x - metrics.center.x;
    const dy = y - metrics.center.y;
    const node = findNode(metrics.nodes, x, y);
    state.pointerOrigin = { x, y };

    if (node) {
      state.sourceNodeId = node.id;
      altar.activateNode(node.id);
      view.energy = Math.min(1, view.energy + 0.12);
      audioToggle?.pulse(view.energy);
      return;
    }

    if (Math.hypot(dx, dy) <= metrics.coreRadius * 1.25) {
      state.draggingCore = true;
      return;
    }

    state.overloadTimer = window.setTimeout(() => {
      altar.triggerOverload();
      view.energy = 1;
      pushShockwave();
      audioToggle?.pulse(1);
    }, 520);
  });

  canvas.addEventListener("pointermove", (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    if (state.draggingCore && state.pointerOrigin) {
      view.rotation += (x - state.pointerOrigin.x) * 0.006;
      view.energy = Math.min(1, view.energy + Math.abs(x - state.pointerOrigin.x) * 0.0008);
      state.pointerOrigin = { x, y };
    }
  });

  function release(event) {
    clearTimeout(state.overloadTimer);
    state.overloadTimer = null;

    if (state.sourceNodeId) {
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const targetNode = findNode(getMetrics(view.rotation).nodes, x, y);
      if (targetNode && targetNode.id !== state.sourceNodeId) {
        altar.activateNode(targetNode.id);
        altar.linkNodes(state.sourceNodeId, targetNode.id);
        view.energy = Math.min(1, view.energy + 0.18);
        audioToggle?.pulse(view.energy);
      }
    }

    state.draggingCore = false;
    state.sourceNodeId = null;
    state.pointerOrigin = null;
  }

  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("pointerleave", release);

  return {
    view,
    reset,
    update({ deltaSeconds, altar: altarState }) {
      view.energy += ((altarState.phase.name === "Ascended" ? 0.95 : 0.28) - view.energy) * deltaSeconds * 1.4;
      view.shockwaves = view.shockwaves
        .map((wave) => ({ ...wave, progress: wave.progress + deltaSeconds * 0.92 }))
        .filter((wave) => wave.progress < 1);
    },
  };
}

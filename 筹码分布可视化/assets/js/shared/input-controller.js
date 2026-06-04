export function createPointerTracker(target) {
  const state = {
    active: false,
    x: target.clientWidth * 0.5,
    y: target.clientHeight * 0.5,
    deltaX: 0,
    deltaY: 0,
  };

  function updatePosition(event) {
    const rect = target.getBoundingClientRect();
    const nextX = event.clientX - rect.left;
    const nextY = event.clientY - rect.top;
    state.deltaX = nextX - state.x;
    state.deltaY = nextY - state.y;
    state.x = nextX;
    state.y = nextY;
    document.body.style.setProperty("--pointer-x", `${event.clientX}px`);
    document.body.style.setProperty("--pointer-y", `${event.clientY}px`);
  }

  target.addEventListener("pointerdown", (event) => {
    state.active = true;
    updatePosition(event);
  });

  target.addEventListener("pointermove", (event) => {
    updatePosition(event);
  });

  const release = () => {
    state.active = false;
    state.deltaX = 0;
    state.deltaY = 0;
  };

  target.addEventListener("pointerup", release);
  target.addEventListener("pointerleave", release);
  target.addEventListener("pointercancel", release);

  return state;
}

export function createKeyboardTracker(target = window) {
  const pressed = new Set();
  target.addEventListener("keydown", (event) => pressed.add(event.code));
  target.addEventListener("keyup", (event) => pressed.delete(event.code));
  target.addEventListener("blur", () => pressed.clear());

  return {
    pressed,
    isDown(code) {
      return pressed.has(code);
    },
  };
}

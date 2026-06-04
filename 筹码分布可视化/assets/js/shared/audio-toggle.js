export function createAudioToggle(button) {
  const state = {
    enabled: false,
    context: null,
    oscillator: null,
    gain: null,
  };

  async function ensureContext() {
    if (state.context) {
      return state.context;
    }
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) {
      return null;
    }
    state.context = new AudioContextCtor();
    state.gain = state.context.createGain();
    state.gain.gain.value = 0.0001;
    state.gain.connect(state.context.destination);
    state.oscillator = state.context.createOscillator();
    state.oscillator.type = "sine";
    state.oscillator.frequency.value = 144;
    state.oscillator.connect(state.gain);
    state.oscillator.start();
    return state.context;
  }

  function syncVisual() {
    button?.toggleAttribute("data-enabled", state.enabled);
    button?.style.setProperty("border-color", state.enabled ? "rgba(180, 255, 94, 0.65)" : "");
  }

  button?.addEventListener("click", async () => {
    if (!state.enabled) {
      const context = await ensureContext();
      if (!context) {
        return;
      }
      await context.resume();
      state.gain.gain.linearRampToValueAtTime(0.018, context.currentTime + 0.3);
      state.enabled = true;
    } else if (state.context) {
      state.gain.gain.linearRampToValueAtTime(0.0001, state.context.currentTime + 0.3);
      state.enabled = false;
    }
    syncVisual();
  });

  syncVisual();

  return {
    state,
    pulse(level) {
      if (!state.enabled || !state.context) {
        return;
      }
      const now = state.context.currentTime;
      state.gain.gain.cancelScheduledValues(now);
      state.gain.gain.setValueAtTime(0.012 + level * 0.02, now);
      state.gain.gain.exponentialRampToValueAtTime(0.006, now + 0.18);
      state.oscillator.frequency.linearRampToValueAtTime(128 + level * 220, now + 0.08);
    },
  };
}

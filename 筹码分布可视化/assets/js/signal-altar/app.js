import { createAnimationClock } from "../shared/animation-clock.js";
import { createAudioToggle } from "../shared/audio-toggle.js";
import { readViewportProfile } from "../shared/viewport-adapter.js";
import { createAltarInteractions } from "./altar-interactions.js";
import { createAltarRenderer } from "./altar-renderer.js";
import { createAltarStateMachine } from "./altar-state-machine.js";

const canvas = document.querySelector("#altar-canvas");
const soundButton = document.querySelector("[data-sound-toggle]");
const resetButton = document.querySelector("[data-reset-scene]");
const fullscreenButton = document.querySelector("[data-fullscreen]");

let profile = readViewportProfile(window);
const renderer = createAltarRenderer(canvas);
renderer.resize(profile);

const altar = createAltarStateMachine();
const audioToggle = createAudioToggle(soundButton);
const interactions = createAltarInteractions({
  canvas,
  altar,
  getMetrics: (rotation) => renderer.getMetrics(rotation),
  audioToggle,
});

function handleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen?.();
  } else {
    document.exitFullscreen?.();
  }
}

resetButton?.addEventListener("click", () => {
  altar.reset();
  interactions.reset();
});

fullscreenButton?.addEventListener("click", handleFullscreen);

window.addEventListener("resize", () => {
  profile = readViewportProfile(window);
  renderer.resize(profile);
});

const clock = createAnimationClock(({ now, deltaSeconds }) => {
  interactions.update({ deltaSeconds, altar });
  renderer.draw({ altar, view: interactions.view, now });
});

clock.start();

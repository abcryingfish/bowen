import { createAnimationClock } from "../shared/animation-clock.js";
import { createAudioToggle } from "../shared/audio-toggle.js";
import { readViewportProfile } from "../shared/viewport-adapter.js";
import { createTempleEffects } from "./temple-effects.js";
import { createTempleInteractions } from "./temple-interactions.js";
import { createTempleScene } from "./scene-builder.js";
import { createTempleStateMachine } from "./temple-state-machine.js";

const canvas = document.querySelector("#temple-canvas");
const soundButton = document.querySelector("[data-sound-toggle]");
const resetButton = document.querySelector("[data-reset-scene]");
const fullscreenButton = document.querySelector("[data-fullscreen]");

let profile = readViewportProfile(window);
const sceneBits = createTempleScene({ canvas, profile });
const temple = createTempleStateMachine();
const audioToggle = createAudioToggle(soundButton);
const interactions = createTempleInteractions({
  canvas,
  camera: sceneBits.camera,
  temple,
  sceneBits,
});
const effects = createTempleEffects(sceneBits, temple, audioToggle);

function handleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen?.();
  } else {
    document.exitFullscreen?.();
  }
}

resetButton?.addEventListener("click", () => {
  temple.reset();
  interactions.reset();
  sceneBits.reset();
});

fullscreenButton?.addEventListener("click", handleFullscreen);

window.addEventListener("resize", () => {
  profile = readViewportProfile(window);
  sceneBits.resize(profile);
});

const clock = createAnimationClock(({ now, deltaSeconds }) => {
  interactions.update({ now, deltaSeconds });
  effects.update({ now, deltaSeconds });
  sceneBits.renderer.render(sceneBits.scene, sceneBits.camera);
});

interactions.reset();
clock.start();

import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { createKeyboardTracker, createPointerTracker } from "../shared/input-controller.js";

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export function createTempleInteractions({ canvas, camera, temple, sceneBits }) {
  const pointer = createPointerTracker(canvas);
  const keyboard = createKeyboardTracker(window);

  const state = {
    position: new THREE.Vector3(8, 3.2, 18),
    yaw: 3.56,
    pitch: -0.12,
    moveSpeed: 6.5,
  };

  let lastTapAt = 0;

  canvas.addEventListener("pointerdown", () => {
    lastTapAt = performance.now();
  });

  function reset() {
    state.position.set(8, 3.2, 18);
    state.yaw = 3.56;
    state.pitch = -0.18;
    camera.position.copy(state.position);
  }

  function updateMovement(deltaSeconds) {
    if (pointer.active) {
      state.yaw -= pointer.deltaX * 0.0038;
      state.pitch = clamp(state.pitch - pointer.deltaY * 0.0028, -0.8, 0.45);
    }

    const forward = new THREE.Vector3(Math.sin(state.yaw), 0, Math.cos(state.yaw));
    const right = new THREE.Vector3(forward.z, 0, -forward.x);
    const velocity = new THREE.Vector3();

    if (keyboard.isDown("KeyW")) {
      velocity.add(forward);
    }
    if (keyboard.isDown("KeyS")) {
      velocity.sub(forward);
    }
    if (keyboard.isDown("KeyA")) {
      velocity.sub(right);
    }
    if (keyboard.isDown("KeyD")) {
      velocity.add(right);
    }

    if (pointer.active && (navigator.maxTouchPoints > 0 || window.innerWidth < 900)) {
      velocity.addScaledVector(forward, 0.55);
    }

    if (velocity.lengthSq() > 0) {
      velocity.normalize().multiplyScalar(state.moveSpeed * deltaSeconds);
      state.position.add(velocity);
      state.position.x = clamp(state.position.x, -15, 15);
      state.position.z = clamp(state.position.z, -15, 15);
    }

    camera.position.lerp(state.position, 0.18);
    const lookTarget = new THREE.Vector3(
      camera.position.x + Math.sin(state.yaw) * 10,
      camera.position.y + Math.sin(state.pitch) * 7,
      camera.position.z + Math.cos(state.yaw) * 10,
    );
    camera.lookAt(lookTarget);
  }

  function maybeActivateNodes() {
    sceneBits.nodes.forEach((node) => {
      if (temple.state.activatedNodes.has(node.id)) {
        return;
      }
      const distance = state.position.distanceTo(node.group.position);
      if (distance <= node.activationRadius) {
        temple.activateNode(node.id);
      }
    });
  }

  return {
    update({ deltaSeconds }) {
      updateMovement(deltaSeconds);
      maybeActivateNodes();
      if (performance.now() - lastTapAt < 160) {
        maybeActivateNodes();
      }
    },
    reset,
  };
}

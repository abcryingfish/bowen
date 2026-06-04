export function createTempleEffects(sceneBits, temple, audioToggle) {
  const paletteByPhase = {
    Dormant: { fog: 0x060711, background: 0x05060d, shell: 0x12304a, emissive: 0x145f82 },
    Awakening: { fog: 0x08111f, background: 0x050912, shell: 0x164868, emissive: 0x18b6d1 },
    Reconfiguration: { fog: 0x180d1d, background: 0x0a0813, shell: 0x40205b, emissive: 0xff4fd8 },
    Ascended: { fog: 0x061520, background: 0x03060d, shell: 0x4a2a6a, emissive: 0xffcf59 },
  };

  function syncPalette() {
    const phaseName = temple.phase.name;
    const palette = paletteByPhase[phaseName];
    sceneBits.scene.fog.color.setHex(palette.fog);
    sceneBits.scene.background.setHex(palette.background);
    sceneBits.outerShell.material.color.setHex(palette.shell);
    sceneBits.outerShell.material.emissive.setHex(palette.emissive);
  }

  return {
    syncPalette,
    update({ now, deltaSeconds }) {
      const seconds = now / 1000;
      const pulse = temple.state.worldPulse;

      sceneBits.coreGroup.rotation.y += deltaSeconds * (0.18 + pulse * 0.9);
      sceneBits.coreGroup.rotation.x = Math.sin(seconds * 0.45) * 0.12;
      sceneBits.coreGroup.position.y = 3 + Math.sin(seconds * 1.25) * (0.22 + pulse * 0.5);

      const scale = 1 + pulse * 0.28 + Math.sin(seconds * 1.8) * 0.03;
      sceneBits.coreSphere.scale.setScalar(scale);
      sceneBits.coreSpindle.rotation.x += deltaSeconds * (0.65 + pulse * 1.6);
      sceneBits.coreSpindle.rotation.z -= deltaSeconds * (0.4 + pulse * 0.9);
      sceneBits.outerShell.rotation.x -= deltaSeconds * 0.22;
      sceneBits.outerShell.rotation.y += deltaSeconds * (0.16 + pulse * 0.5);

      sceneBits.orbitRings.children.forEach((ring, index) => {
        ring.rotation.z += deltaSeconds * (0.12 + pulse * 0.2 + index * 0.03);
        ring.rotation.y += deltaSeconds * (0.08 + index * 0.04);
        ring.scale.setScalar(1 + pulse * 0.06 * (index + 1));
      });

      const gateOpenAmount = temple.state.gateOpen ? 1 : 0;
      sceneBits.gateGroup.children.forEach((arc, index) => {
        const baseScale = 1 + gateOpenAmount * (0.18 + index * 0.06);
        arc.scale.set(baseScale, baseScale, baseScale);
        arc.rotation.z = Math.sin(seconds * 0.3 + index) * 0.12;
        arc.material.opacity = 0.2 + pulse * 0.28;
      });

      sceneBits.skyShell.material.opacity = temple.phase.name === "Ascended" ? 0.48 : 0.18 + pulse * 0.16;
      sceneBits.starfield.rotation.y += deltaSeconds * (0.01 + pulse * 0.03);
      sceneBits.starfield.rotation.x = Math.sin(seconds * 0.04) * 0.12;

      sceneBits.waterfalls.children.forEach((stream, streamIndex) => {
        const positions = stream.geometry.attributes.position;
        const speeds = stream.geometry.attributes.speed;
        for (let index = 0; index < positions.count; index += 1) {
          const speed = speeds.getX(index) * (0.8 + pulse * 0.9 + streamIndex * 0.18);
          let y = positions.getY(index) - deltaSeconds * 6 * speed;
          if (y < -0.5) {
            y = 9.5 + Math.random() * 2;
          }
          positions.setY(index, y);
        }
        positions.needsUpdate = true;
      });

      sceneBits.nodes.forEach((node, index) => {
        const activated = temple.state.activatedNodes.has(node.id);
        node.activated = activated;
        node.halo.rotation.z += deltaSeconds * (0.32 + index * 0.12);
        node.halo.material.opacity = activated ? 0.74 : 0.28;
        node.body.material.emissiveIntensity = activated ? 0.65 : 0.08;
        node.crown.material.emissiveIntensity = activated ? 2 : 0.85;
        node.crown.scale.setScalar(activated ? 1.32 + Math.sin(seconds * 2.2) * 0.08 : 1 + Math.sin(seconds * 1.4 + index) * 0.02);
        node.group.position.y = 2.2 + (activated ? 0.5 : 0) + Math.sin(seconds * 1.1 + index) * 0.08;
      });

      sceneBits.floorRings.children.forEach((ring, index) => {
        ring.rotation.y += deltaSeconds * (0.04 + index * 0.01);
        ring.material.opacity = 0.22 + pulse * 0.16;
      });

      syncPalette();
      audioToggle?.pulse(temple.state.worldPulse);
    },
  };
}

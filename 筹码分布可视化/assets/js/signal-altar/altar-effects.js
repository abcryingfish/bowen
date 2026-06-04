const NODE_IDS = ["a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8"];

const PALETTES = {
  Dormant: {
    background: "#04050a",
    grid: "rgba(61, 246, 255, 0.14)",
    primary: "#3df6ff",
    secondary: "#7b8cff",
    accent: "#ffcf59",
    overload: "#ff4fd8",
  },
  Awakening: {
    background: "#05070d",
    grid: "rgba(61, 246, 255, 0.18)",
    primary: "#3df6ff",
    secondary: "#b4ff5e",
    accent: "#ffcf59",
    overload: "#ff4fd8",
  },
  Reconfiguration: {
    background: "#07050d",
    grid: "rgba(255, 79, 216, 0.14)",
    primary: "#ff4fd8",
    secondary: "#3df6ff",
    accent: "#ffcf59",
    overload: "#ffffff",
  },
  Ascended: {
    background: "#03050b",
    grid: "rgba(180, 255, 94, 0.18)",
    primary: "#ffcf59",
    secondary: "#3df6ff",
    accent: "#b4ff5e",
    overload: "#ff4fd8",
  },
};

export function getPhasePalette(phaseName) {
  return PALETTES[phaseName] ?? PALETTES.Dormant;
}

export function easeOutCubic(value) {
  return 1 - (1 - value) ** 3;
}

export function getNodeLayout({ center, shortSide, rotation = 0 }) {
  const orbitRadius = shortSide * 0.31;
  const nodeRadius = shortSide * 0.024;

  return NODE_IDS.map((id, index) => {
    const angle = rotation + (index / NODE_IDS.length) * Math.PI * 2 - Math.PI / 2;
    return {
      id,
      x: center.x + Math.cos(angle) * orbitRadius,
      y: center.y + Math.sin(angle) * orbitRadius,
      radius: nodeRadius,
    };
  });
}

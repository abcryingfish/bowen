import { easeOutCubic, getNodeLayout, getPhasePalette } from "./altar-effects.js";

function drawGrid(ctx, width, height, palette, time) {
  ctx.save();
  ctx.strokeStyle = palette.grid;
  ctx.lineWidth = 1;
  const spacing = 28;
  const offset = (time * 20) % spacing;
  for (let x = -spacing; x < width + spacing; x += spacing) {
    ctx.beginPath();
    ctx.moveTo(x + offset, 0);
    ctx.lineTo(x + offset, height);
    ctx.stroke();
  }
  for (let y = -spacing; y < height + spacing; y += spacing) {
    ctx.beginPath();
    ctx.moveTo(0, y + offset * 0.6);
    ctx.lineTo(width, y + offset * 0.6);
    ctx.stroke();
  }
  ctx.restore();
}

function drawCircuitField(ctx, width, height, center, shortSide, palette, time, energy) {
  ctx.save();
  ctx.strokeStyle = palette.grid;
  ctx.lineWidth = 1;
  ctx.globalAlpha = 0.55 + energy * 0.25;
  const arms = 32;
  for (let index = 0; index < arms; index += 1) {
    const angle = (index / arms) * Math.PI * 2 + time * 0.015;
    const inner = shortSide * (0.19 + (index % 4) * 0.035);
    const outer = shortSide * (0.38 + (index % 5) * 0.018);
    const elbow = inner + (outer - inner) * 0.45;
    const x1 = center.x + Math.cos(angle) * inner;
    const y1 = center.y + Math.sin(angle) * inner;
    const x2 = center.x + Math.cos(angle) * elbow;
    const y2 = center.y + Math.sin(angle) * elbow;
    const x3 = x2 + Math.cos(angle + Math.PI / 2) * shortSide * 0.035 * ((index % 2) ? 1 : -1);
    const y3 = y2 + Math.sin(angle + Math.PI / 2) * shortSide * 0.035 * ((index % 2) ? 1 : -1);
    const x4 = center.x + Math.cos(angle) * outer;
    const y4 = center.y + Math.sin(angle) * outer;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.lineTo(x3, y3);
    ctx.lineTo(x4, y4);
    ctx.stroke();
  }

  for (let index = 0; index < 18; index += 1) {
    const ring = shortSide * (0.18 + index * 0.018);
    const start = time * 0.05 + index * 0.7;
    ctx.strokeStyle = index % 3 === 0 ? `${palette.accent}44` : palette.grid;
    ctx.beginPath();
    ctx.arc(center.x, center.y, ring, start, start + Math.PI * (0.08 + (index % 5) * 0.035));
    ctx.stroke();
  }
  ctx.restore();
}

function drawWavePools(ctx, center, shortSide, palette, time, energy) {
  ctx.save();
  for (let index = 0; index < 5; index += 1) {
    const radius = shortSide * (0.14 + index * 0.07) + Math.sin(time * 2 + index) * 6;
    const gradient = ctx.createRadialGradient(center.x, center.y, radius * 0.7, center.x, center.y, radius);
    gradient.addColorStop(0, "rgba(0, 0, 0, 0)");
    gradient.addColorStop(0.8, index % 2 === 0 ? `${palette.primary}22` : `${palette.secondary}22`);
    gradient.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 2 + energy * 2;
    ctx.beginPath();
    ctx.ellipse(center.x, center.y, radius, radius * 0.78, time * 0.2 + index * 0.2, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

function drawLinks(ctx, links, nodeMap, palette, time) {
  ctx.save();
  ctx.lineCap = "round";
  links.forEach(([from, to], index) => {
    const a = nodeMap.get(from);
    const b = nodeMap.get(to);
    if (!a || !b) {
      return;
    }
    const midX = (a.x + b.x) * 0.5 + Math.sin(time * 2 + index) * 12;
    const midY = (a.y + b.y) * 0.5 + Math.cos(time * 2.4 + index) * 12;
    const gradient = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
    gradient.addColorStop(0, palette.primary);
    gradient.addColorStop(0.5, palette.accent);
    gradient.addColorStop(1, palette.secondary);
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.quadraticCurveTo(midX, midY, b.x, b.y);
    ctx.stroke();
  });
  ctx.restore();
}

function drawNodes(ctx, nodes, activeNodes, palette, time) {
  nodes.forEach((node, index) => {
    const active = activeNodes.has(node.id);
    ctx.save();
    ctx.translate(node.x, node.y);
    ctx.rotate(time * 0.3 + index * 0.1);
    ctx.strokeStyle = active ? palette.accent : palette.primary;
    ctx.fillStyle = active ? `${palette.primary}55` : "rgba(7, 10, 20, 0.65)";
    ctx.lineWidth = active ? 2.6 : 1.4;
    ctx.beginPath();
    ctx.arc(0, 0, node.radius * (active ? 1.15 : 1), 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(-node.radius * 0.5, 0);
    ctx.lineTo(node.radius * 0.5, 0);
    ctx.moveTo(0, -node.radius * 0.5);
    ctx.lineTo(0, node.radius * 0.5);
    ctx.stroke();
    ctx.restore();
  });
}

function drawCore(ctx, center, shortSide, palette, rotation, time, phaseName) {
  const coreRadius = shortSide * 0.145;
  ctx.save();
  ctx.translate(center.x, center.y);
  ctx.rotate(rotation);

  const glow = ctx.createRadialGradient(0, 0, coreRadius * 0.2, 0, 0, coreRadius * 1.7);
  glow.addColorStop(0, `${palette.primary}cc`);
  glow.addColorStop(0.4, `${palette.secondary}33`);
  glow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(0, 0, coreRadius * 1.7, 0, Math.PI * 2);
  ctx.fill();

  for (let index = 0; index < 5; index += 1) {
    ctx.strokeStyle = index % 2 === 0 ? palette.primary : palette.secondary;
    ctx.lineWidth = 2 - index * 0.18;
    ctx.beginPath();
    ctx.arc(0, 0, coreRadius * (0.5 + index * 0.18), time * 0.3 + index, time * 0.3 + index + Math.PI * 1.2);
    ctx.stroke();
  }

  ctx.strokeStyle = palette.accent;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(-coreRadius * 0.48, 0);
  ctx.lineTo(coreRadius * 0.48, 0);
  ctx.moveTo(0, -coreRadius * 0.48);
  ctx.lineTo(0, coreRadius * 0.48);
  ctx.stroke();

  if (phaseName === "Ascended") {
    ctx.strokeStyle = palette.overload;
    ctx.lineWidth = 1.4;
    for (let index = 0; index < 8; index += 1) {
      ctx.beginPath();
      ctx.arc(0, 0, coreRadius * (1.1 + index * 0.11), time * 0.4 + index, time * 0.4 + index + Math.PI * 0.45);
      ctx.stroke();
    }
  }

  ctx.restore();
}

function drawShockwaves(ctx, center, shockwaves, palette) {
  ctx.save();
  shockwaves.forEach((wave) => {
    const t = Math.min(1, wave.progress);
    const eased = easeOutCubic(t);
    ctx.strokeStyle = t < 0.65 ? palette.overload : palette.accent;
    ctx.lineWidth = 3 * (1 - t) + 0.5;
    ctx.globalAlpha = 1 - t;
    ctx.beginPath();
    ctx.arc(center.x, center.y, wave.baseRadius + eased * wave.range, 0, Math.PI * 2);
    ctx.stroke();
  });
  ctx.restore();
}

function drawScanBeams(ctx, center, shortSide, palette, time) {
  ctx.save();
  ctx.translate(center.x, center.y);
  for (let index = 0; index < 3; index += 1) {
    ctx.rotate(time * 0.08 + index * 1.2);
    const gradient = ctx.createLinearGradient(0, 0, shortSide * 0.4, 0);
    gradient.addColorStop(0, `${palette.primary}66`);
    gradient.addColorStop(0.65, "rgba(0,0,0,0)");
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(shortSide * 0.4, 0);
    ctx.stroke();
  }
  ctx.restore();
}

export function createAltarRenderer(canvas) {
  const ctx = canvas.getContext("2d");
  let width = 1;
  let height = 1;
  let dpr = 1;

  function getMetrics(rotation = 0) {
    const shortSide = Math.min(width, height);
    const center = { x: width * 0.5, y: height * 0.5 };
    return {
      width,
      height,
      dpr,
      shortSide,
      center,
      coreRadius: shortSide * 0.145,
      nodeRadius: shortSide * 0.024,
      nodes: getNodeLayout({ center, shortSide, rotation }),
    };
  }

  return {
    resize(profile) {
      dpr = profile.pixelRatio;
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    },
    getMetrics,
    draw({ altar, view, now }) {
      const time = now / 1000;
      const metrics = getMetrics(view.rotation);
      const { center, shortSide } = metrics;
      const palette = getPhasePalette(altar.phase.name);

      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = palette.background;
      ctx.fillRect(0, 0, width, height);

      drawGrid(ctx, width, height, palette, time);
      drawWavePools(ctx, center, shortSide, palette, time, view.energy);
      drawCircuitField(ctx, width, height, center, shortSide, palette, time, view.energy);
      drawScanBeams(ctx, center, shortSide, palette, time);

      const nodeMap = new Map(metrics.nodes.map((node) => [node.id, node]));
      drawLinks(ctx, altar.state.links, nodeMap, palette, time);
      drawNodes(ctx, metrics.nodes, altar.state.activeNodes, palette, time);
      drawCore(ctx, center, shortSide, palette, view.rotation, time, altar.phase.name);
      drawShockwaves(ctx, center, view.shockwaves, palette);
    },
  };
}

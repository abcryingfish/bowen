import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";

const NODE_LAYOUT = [
  { id: "north", position: new THREE.Vector3(0, 2.2, -11), color: 0x3df6ff },
  { id: "south", position: new THREE.Vector3(0, 2.2, 11), color: 0xffcf59 },
  { id: "east", position: new THREE.Vector3(11, 2.2, 0), color: 0xff4fd8 },
  { id: "west", position: new THREE.Vector3(-11, 2.2, 0), color: 0xb4ff5e },
];

function makeLineRing(radius, segments, color, y = 0) {
  const points = [];
  for (let index = 0; index <= segments; index += 1) {
    const angle = (index / segments) * Math.PI * 2;
    points.push(new THREE.Vector3(Math.cos(angle) * radius, y, Math.sin(angle) * radius));
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity: 0.35,
  });
  return new THREE.Line(geometry, material);
}

function createStarfield(count, radius, color) {
  const positions = new Float32Array(count * 3);
  for (let index = 0; index < count; index += 1) {
    const angle = Math.random() * Math.PI * 2;
    const tilt = Math.acos(1 - Math.random() * 2);
    const distance = radius * (0.48 + Math.random() * 0.52);
    positions[index * 3] = Math.sin(tilt) * Math.cos(angle) * distance;
    positions[index * 3 + 1] = Math.cos(tilt) * distance * 0.72;
    positions[index * 3 + 2] = Math.sin(tilt) * Math.sin(angle) * distance;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  return new THREE.Points(
    geometry,
    new THREE.PointsMaterial({
      color,
      size: 0.22,
      transparent: true,
      opacity: 0.82,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
}

function createWaterfall(color, offsetX) {
  const count = 220;
  const geometry = new THREE.BufferGeometry();
  const positions = new Float32Array(count * 3);
  const speeds = new Float32Array(count);
  for (let index = 0; index < count; index += 1) {
    positions[index * 3] = offsetX + (Math.random() - 0.5) * 1.2;
    positions[index * 3 + 1] = Math.random() * 9;
    positions[index * 3 + 2] = (Math.random() - 0.5) * 1.2;
    speeds[index] = 0.6 + Math.random() * 1.2;
  }
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("speed", new THREE.BufferAttribute(speeds, 1));
  return new THREE.Points(
    geometry,
    new THREE.PointsMaterial({
      color,
      size: 0.16,
      transparent: true,
      opacity: 0.9,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
}

function createNode({ id, position, color }) {
  const group = new THREE.Group();
  group.position.copy(position);
  group.userData.nodeId = id;

  const body = new THREE.Mesh(
    new THREE.BoxGeometry(1.4, 4.8, 1.4),
    new THREE.MeshStandardMaterial({
      color: 0x101726,
      emissive: color,
      emissiveIntensity: 0.08,
      metalness: 0.75,
      roughness: 0.24,
    }),
  );

  const crown = new THREE.Mesh(
    new THREE.OctahedronGeometry(0.78, 0),
    new THREE.MeshStandardMaterial({
      color,
      emissive: color,
      emissiveIntensity: 0.85,
      transparent: true,
      opacity: 0.84,
    }),
  );
  crown.position.y = 3.2;

  const halo = new THREE.Mesh(
    new THREE.TorusGeometry(2.4, 0.05, 16, 120),
    new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.42,
    }),
  );
  halo.rotation.x = Math.PI / 2;

  const spine = makeLineRing(1.15, 64, color, 1.4);
  spine.rotation.z = Math.PI / 2;

  group.add(body, crown, halo, spine);

  return { id, color, group, body, crown, halo, spine, activationRadius: 4.6, activated: false };
}

export function createTempleScene({ canvas, profile }) {
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: profile.mode !== "mobile",
    alpha: true,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(profile.pixelRatio);
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x05060d);
  scene.fog = new THREE.FogExp2(0x060711, 0.026);

  const camera = new THREE.PerspectiveCamera(58, window.innerWidth / window.innerHeight, 0.1, 260);
  camera.position.set(8, 3.2, 18);

  scene.add(new THREE.AmbientLight(0x88aaff, 0.55));

  const sun = new THREE.DirectionalLight(0x7db7ff, 1.55);
  sun.position.set(9, 18, 7);
  scene.add(sun);

  const root = new THREE.Group();
  scene.add(root);

  const floor = new THREE.Mesh(
    new THREE.CircleGeometry(40, 96),
    new THREE.MeshStandardMaterial({
      color: 0x070910,
      emissive: 0x07111d,
      emissiveIntensity: 0.7,
      metalness: 0.8,
      roughness: 0.2,
      transparent: true,
      opacity: 0.92,
    }),
  );
  floor.rotation.x = -Math.PI / 2;
  root.add(floor);

  const floorRings = new THREE.Group();
  floorRings.add(makeLineRing(6, 128, 0x3df6ff, 0.04));
  floorRings.add(makeLineRing(12, 164, 0xff4fd8, 0.045));
  floorRings.add(makeLineRing(18, 192, 0xffcf59, 0.05));
  root.add(floorRings);

  const coreGroup = new THREE.Group();
  const outerShell = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1.8, 1),
    new THREE.MeshStandardMaterial({
      color: 0x12304a,
      emissive: 0x145f82,
      emissiveIntensity: 0.45,
      metalness: 0.76,
      roughness: 0.2,
      transparent: true,
      opacity: 0.76,
      flatShading: true,
    }),
  );
  const coreSphere = new THREE.Mesh(
    new THREE.SphereGeometry(0.95, 48, 32),
    new THREE.MeshStandardMaterial({
      color: 0x59ecff,
      emissive: 0x59ecff,
      emissiveIntensity: 1.6,
      metalness: 0.25,
      roughness: 0.18,
    }),
  );
  const coreSpindle = new THREE.Mesh(
    new THREE.TorusKnotGeometry(1.25, 0.2, 180, 24, 2, 5),
    new THREE.MeshStandardMaterial({
      color: 0xff4fd8,
      emissive: 0xff4fd8,
      emissiveIntensity: 0.9,
      metalness: 0.68,
      roughness: 0.26,
    }),
  );
  coreGroup.add(outerShell, coreSphere, coreSpindle);
  coreGroup.position.y = 3.1;
  root.add(coreGroup);

  const orbitRings = new THREE.Group();
  for (let index = 0; index < 4; index += 1) {
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(3.2 + index * 1.45, 0.06 + index * 0.02, 16, 132),
      new THREE.MeshBasicMaterial({
        color: [0x3df6ff, 0xff4fd8, 0xffcf59, 0xb4ff5e][index % 4],
        transparent: true,
        opacity: 0.26 + index * 0.06,
      }),
    );
    ring.rotation.x = Math.PI / (2 + index * 0.45);
    ring.rotation.y = Math.PI / (2.7 + index * 0.23);
    orbitRings.add(ring);
  }
  orbitRings.position.copy(coreGroup.position);
  root.add(orbitRings);

  const architecture = new THREE.Group();
  const gateGroup = new THREE.Group();
  for (let index = 0; index < 6; index += 1) {
    const arc = new THREE.Mesh(
      new THREE.TorusGeometry(14 + index * 1.15, 0.08, 12, 120, Math.PI * 0.62),
      new THREE.MeshBasicMaterial({
        color: index % 2 === 0 ? 0x173f63 : 0x421939,
        transparent: true,
        opacity: 0.28,
      }),
    );
    arc.rotation.x = Math.PI / 2 + index * 0.08;
    arc.rotation.y = index * (Math.PI / 3);
    gateGroup.add(arc);
  }
  architecture.add(gateGroup);

  const skyShell = new THREE.Mesh(
    new THREE.SphereGeometry(100, 64, 64),
    new THREE.MeshBasicMaterial({
      color: 0x0b1326,
      side: THREE.BackSide,
      transparent: true,
      opacity: 0.18,
    }),
  );
  architecture.add(skyShell);
  root.add(architecture);

  const starfield = createStarfield(profile.mode === "mobile" ? 1800 : 3200, 120, 0xe2fbff);
  scene.add(starfield);

  const waterfalls = new THREE.Group();
  waterfalls.add(createWaterfall(0x3df6ff, -6));
  waterfalls.add(createWaterfall(0xff4fd8, 6));
  waterfalls.position.y = 0.4;
  root.add(waterfalls);

  const nodes = NODE_LAYOUT.map((nodeConfig) => createNode(nodeConfig));
  nodes.forEach((node) => root.add(node.group));

  return {
    THREE,
    renderer,
    scene,
    camera,
    root,
    floor,
    floorRings,
    coreGroup,
    outerShell,
    coreSphere,
    coreSpindle,
    orbitRings,
    gateGroup,
    skyShell,
    starfield,
    waterfalls,
    nodes,
    resize(nextProfile) {
      renderer.setPixelRatio(nextProfile.pixelRatio);
      renderer.setSize(window.innerWidth, window.innerHeight, false);
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
    },
    reset() {
      root.rotation.set(0, 0, 0);
      camera.position.set(8, 3.2, 18);
    },
  };
}

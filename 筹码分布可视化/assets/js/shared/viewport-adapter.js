export function getViewportProfile({ width, height, touch, devicePixelRatio }) {
  const mobile = Boolean(touch) || width < 900;
  const cappedDpr = Math.min(devicePixelRatio || 1, mobile ? 1.75 : 2);

  return {
    mode: mobile ? "mobile" : "desktop",
    pixelRatio: cappedDpr,
    densityScale: mobile ? 0.58 : 1,
    bloomScale: mobile ? 0.72 : 1,
    shortSide: Math.min(width, height),
  };
}

export function readViewportProfile(target = window) {
  const nav = target.navigator ?? {};
  return getViewportProfile({
    width: target.innerWidth,
    height: target.innerHeight,
    touch: nav.maxTouchPoints > 0 || "ontouchstart" in target,
    devicePixelRatio: target.devicePixelRatio || 1,
  });
}

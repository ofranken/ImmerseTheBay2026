// Scrapp collage viewer effects (mode=view only; the editor never loads this).
//   Drift  : a slow, eased dolly + orbit that loops (the default, like a camera move in a film)
//   Tilt   : "window" parallax. The camera swings a small angle around the collage as you tilt the phone
//            (DeviceOrientation) or move the mouse on a desktop
//   Free   : plain drag-to-orbit
// plus soft per-sticker shadows so layers at different depths read as separate cards, not one flat sheet.
// Nothing here touches the saved scene: it only moves the camera and adds render-only children.
import * as THREE from 'three';

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const smooth = (x) => { x = clamp(x, 0, 1); return x * x * (3 - 2 * x); };

export function createViewerFx({ camera, controls, renderer, items, zone, onMode }) {
  const state = {
    mode: 'init', t0: 0, started: false,
    base: { az: 0, el: 0.3, dist: 4 }, target: new THREE.Vector3(),
    cur: { yaw: 0, pitch: 0 }, want: { yaw: 0, pitch: 0 },
    orient: null, neutral: null, sensor: false, pointerFx: false,
  };
  const reduceMotion = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
  const ui = buildUi();

  // ------------------------------------------------------------------ depth: soft shadows under stickers
  function silhouetteTexture(image) {
    const k = 256 / Math.max(image.width, image.height), pad = 28;
    const w = Math.round(image.width * k) + pad * 2, h = Math.round(image.height * k) + pad * 2;
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    const sil = document.createElement('canvas'); sil.width = w; sil.height = h;
    const sctx = sil.getContext('2d');
    sctx.drawImage(image, pad, pad, w - pad * 2, h - pad * 2);
    sctx.globalCompositeOperation = 'source-in'; sctx.fillStyle = '#2b1a10'; sctx.fillRect(0, 0, w, h);
    if ('filter' in ctx) { ctx.filter = 'blur(9px)'; ctx.drawImage(sil, 0, 0); }
    else { for (let i = 0; i < 14; i++) { ctx.globalAlpha = 0.12; ctx.drawImage(sil, Math.cos(i) * 6, Math.sin(i * 1.7) * 6); } }
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    return { tex, padX: pad / (w - pad * 2), padY: pad / (h - pad * 2) };
  }

  const shadowed = [];
  function addDepthShadows() {
    for (const it of items.values()) {
      if (it.kind === 'mesh' || !it.object.material?.map?.image || it.object.userData.fxShadow) continue;
      try {
        const { tex, padX, padY } = silhouetteTexture(it.object.material.map.image);
        const g = it.object.geometry.parameters;           // PlaneGeometry width/height
        const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.4, depthWrite: false, side: THREE.DoubleSide });
        const sh = new THREE.Mesh(new THREE.PlaneGeometry(g.width * (1 + padX * 2), g.height * (1 + padY * 2)), mat);
        sh.position.set(g.width * 0.03, -g.height * 0.045, -0.008);
        sh.renderOrder = -1;
        it.object.add(sh);
        it.object.userData.fxShadow = sh;
        shadowed.push(it.object);
      } catch (_) { /* a tainted image just goes without a shadow */ }
    }
  }
  const _n = new THREE.Vector3(), _d = new THREE.Vector3(), _q = new THREE.Quaternion();
  function updateShadows() {
    for (const o of shadowed) {  // only draw the shadow while we look at the sticker's front; from behind it would cover the card
      o.getWorldQuaternion(_q);
      _n.set(0, 0, 1).applyQuaternion(_q);
      _d.copy(camera.position).sub(o.position);
      o.userData.fxShadow.visible = _n.dot(_d) > 0;
    }
  }

  // ------------------------------------------------------------------ camera modes
  function poseFromCamera() {
    state.target.copy(controls.target);
    const off = camera.position.clone().sub(state.target);
    state.base.dist = Math.max(off.length(), 0.5);
    state.base.az = Math.atan2(off.x, off.z);
    state.base.el = Math.asin(clamp(off.y / state.base.dist, -1, 1));
  }
  // Phones are tall and narrow: pull the camera back until the whole collage fits the width as well as the height.
  const _box = new THREE.Box3(), _sz = new THREE.Vector3();
  function fitDistance() {
    _box.makeEmpty();
    for (const it of items.values()) _box.expandByObject(it.object);
    if (_box.isEmpty()) return;
    _box.getSize(_sz);
    const vfov = THREE.MathUtils.degToRad(camera.fov), hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
    const need = Math.max((_sz.x / 2) / Math.tan(hfov / 2), (_sz.y / 2) / Math.tan(vfov / 2)) * 1.12 + _sz.z / 2;
    state.base.dist = Math.max(state.base.dist, need);
    state.fitted = true;
  }
  function place(az, el, dist) {
    camera.position.set(
      state.target.x + dist * Math.cos(el) * Math.sin(az),
      state.target.y + dist * Math.sin(el),
      state.target.z + dist * Math.cos(el) * Math.cos(az));
    camera.lookAt(state.target);
  }

  function setMode(mode) {
    if (mode === state.mode) return;
    if (state.mode === 'free') poseFromCamera();            // remember where the user left the camera (state.target follows)
    const first = state.mode === 'init';
    state.mode = mode;
    controls.enabled = mode === 'free';
    controls.autoRotate = false;
    if (mode === 'drift') { state.t0 = performance.now(); if (!first) poseFromCamera(); }
    if (mode === 'tilt') { state.neutral = null; state.cur.yaw = state.cur.pitch = 0; state.want.yaw = state.want.pitch = 0; }
    if (mode === 'free') { controls.target.copy(state.target); if (first) place(state.base.az, state.base.el, state.base.dist); controls.update(); }
    ui.mark(mode);
    onMode?.(mode);
  }

  function tick(now) {
    if (!state.started) return;
    if (state.mode === 'drift') {
      const t = (now - state.t0) / 1000, e = smooth(t / 2.5);
      place(state.base.az + e * 0.34 * Math.sin((2 * Math.PI * t) / 20),
            state.base.el + e * 0.07 * Math.sin((2 * Math.PI * t) / 13 + 1.0),
            state.base.dist * (1 + e * 0.07 * Math.sin((2 * Math.PI * t) / 16 + 0.5)));
    } else if (state.mode === 'tilt') {
      const k = 0.09;  // smoothing: the lerp that makes it feel like a window, not a gyro readout
      state.cur.yaw += (state.want.yaw - state.cur.yaw) * k;
      state.cur.pitch += (state.want.pitch - state.cur.pitch) * k;
      place(state.base.az + state.cur.yaw, state.base.el + state.cur.pitch, state.base.dist);
    }
    updateShadows();
  }

  // ------------------------------------------------------------------ inputs
  const MAX_YAW = 0.42, MAX_PITCH = 0.22;      // a gentle range: about 24 and 12 degrees
  function onOrientation(e) {
    if (e.beta == null || e.gamma == null) return;
    state.sensor = true;
    const ang = (screen.orientation && screen.orientation.angle) || window.orientation || 0;
    let beta = e.beta, gamma = e.gamma;
    if (ang === 90) [beta, gamma] = [-gamma, beta]; else if (ang === 270 || ang === -90) [beta, gamma] = [gamma, -beta];
    if (!state.neutral) state.neutral = { beta, gamma };      // however you hold the phone first is "straight on"
    const dg = clamp((gamma - state.neutral.gamma) / 28, -1, 1), db = clamp((beta - state.neutral.beta) / 28, -1, 1);
    if (state.mode === 'tilt') { state.want.yaw = -dg * MAX_YAW; state.want.pitch = db * MAX_PITCH; }
  }
  function onPointer(e) {
    if (e.pointerType !== 'mouse' || state.sensor || state.mode !== 'tilt') return;
    state.want.yaw = -((e.clientX / innerWidth) * 2 - 1) * MAX_YAW;
    state.want.pitch = -((e.clientY / innerHeight) * 2 - 1) * MAX_PITCH;
  }
  addEventListener('pointermove', onPointer);
  let listening = false;
  async function enableTilt() {
    try {
      const DOE = window.DeviceOrientationEvent;
      if (DOE && typeof DOE.requestPermission === 'function') {         // iOS: must come from a tap
        const r = await DOE.requestPermission();
        if (r !== 'granted') { ui.say('Motion access was denied. Allow it in Settings to tilt.'); return false; }
      }
      if (DOE && !listening) { addEventListener('deviceorientation', onOrientation); listening = true; }
    } catch (e) { ui.say('Could not start tilt: ' + e.message); return false; }
    setMode('tilt');
    return true;
  }
  // dragging the picture means "I want to look around myself": drift stops
  renderer.domElement.addEventListener('pointerdown', () => { if (state.mode === 'drift') setMode('free'); });

  ui.onPick = async (m) => { if (m === 'tilt') await enableTilt(); else setMode(m); };
  ui.onTiltHint = async () => { await enableTilt(); ui.hideHint(); };

  // ------------------------------------------------------------------ public
  function start() {
    addDepthShadows();
    poseFromCamera();
    fitDistance();
    controls.maxDistance = Math.max(controls.maxDistance, state.base.dist * 2.5);
    state.started = true;
    setMode(reduceMotion ? 'free' : 'drift');
    if (isTouch) ui.showHint();
  }
  function refreshShadows() { addDepthShadows(); }
  return { start, tick, setMode, refreshShadows, get mode() { return state.mode; }, ui };
}

// ---------------------------------------------------------------------- UI (Scrapp look)
function buildUi() {
  const css = document.createElement('style');
  css.textContent = `
    #fx-bar{position:fixed;left:14px;bottom:14px;display:flex;gap:6px;z-index:5;font-family:Nunito,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
    .fx-pill{appearance:none;border:0;border-radius:999px;padding:9px 16px;font:800 14px/1 Nunito,system-ui,sans-serif;color:#5C3A26;background:#FFF0DE;
      box-shadow:0 3px 0 rgba(105,74,71,.22),inset 0 0 0 2px rgba(105,74,71,.14);cursor:pointer}
    .fx-pill.on{background:#96C1C5;box-shadow:0 3px 0 rgba(105,74,71,.28)}
    .fx-pill:active{transform:translateY(2px)}
    #fx-hint{position:fixed;left:50%;bottom:70px;transform:translateX(-50%);z-index:6;display:none;font:400 20px/1 Anton,Impact,sans-serif;letter-spacing:.6px;
      background:#96C1C5;color:#5C3A26;padding:13px 22px;border-radius:999px;box-shadow:0 4px 0 rgba(105,74,71,.28);cursor:pointer;white-space:nowrap}
    #fx-say{position:fixed;left:50%;top:70px;transform:translateX(-50%);z-index:7;display:none;background:#5C3A26;color:#fff;border-radius:999px;padding:10px 18px;font:800 14px Nunito,system-ui,sans-serif}`;
  document.head.appendChild(css);
  const bar = document.createElement('div'); bar.id = 'fx-bar';
  const labels = { drift: 'Drift', tilt: 'Tilt', free: 'Free orbit' };
  const buttons = {};
  const api = { onPick: null, onTiltHint: null };
  for (const [m, label] of Object.entries(labels)) {
    const b = document.createElement('button'); b.className = 'fx-pill'; b.textContent = label; b.dataset.mode = m;
    b.addEventListener('click', () => { api.onPick?.(m); api.hideHint(); });
    bar.appendChild(b); buttons[m] = b;
  }
  document.body.appendChild(bar);
  const hint = document.createElement('div'); hint.id = 'fx-hint'; hint.textContent = 'Tilt to look around';
  hint.addEventListener('click', () => api.onTiltHint?.());
  document.body.appendChild(hint);
  const say = document.createElement('div'); say.id = 'fx-say'; document.body.appendChild(say);
  let sayTimer, hintTimer;
  api.mark = (m) => { for (const [k, b] of Object.entries(buttons)) b.classList.toggle('on', k === m); };
  api.showHint = () => { hint.style.display = 'block'; clearTimeout(hintTimer); hintTimer = setTimeout(api.hideHint, 9000); };
  api.hideHint = () => { hint.style.display = 'none'; };
  api.say = (msg) => { say.textContent = msg; say.style.display = 'block'; clearTimeout(sayTimer); sayTimer = setTimeout(() => (say.style.display = 'none'), 4500); };
  api.bar = bar;
  return api;
}

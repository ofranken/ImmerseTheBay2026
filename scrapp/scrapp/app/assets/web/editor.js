// Scrapp 3D collage editor + viewer (three.js r187).
// Runs inside the app's WebView (mode=edit, mode=model) and as the public web viewer (mode=view).
// Flutter -> JS: window.ScrappEditor.command({cmd, ...})
// JS -> Flutter: Scrapp.postMessage(JSON)  (JavaScriptChannel; logged to console in a browser)
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { RenderPixelatedPass } from 'three/addons/postprocessing/RenderPixelatedPass.js';
import { AfterimagePass } from 'three/addons/postprocessing/AfterimagePass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const params = new URLSearchParams(location.search);
const MODE = params.get('mode') || 'edit';
const PAPER = 0xF1E7D3, INK = 0x5C3A26, TEAL = 0x96C1C5, SAGE = 0x7E8F62, RED = 0xC2564B;

const ZONE_PRESETS = {
  square: [1.2, 1.2, 1.2],
  portrait: [0.9, 1.6, 0.9],
  landscape: [1.6, 0.9, 0.9],
  tower: [0.6, 2.0, 0.6],
  panorama: [2.4, 0.8, 0.8],
};

// ------------------------------------------------------------------------------------ bridge
function post(msg) {
  const s = JSON.stringify(msg);
  if (window.Scrapp && window.Scrapp.postMessage) window.Scrapp.postMessage(s);
  else console.log('[scrapp]', s.length > 300 ? s.slice(0, 300) + '…' : s);
}

// ------------------------------------------------------------------------------------- scene
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setClearColor(0x000000, 0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.01, 100);
camera.position.set(2.4, 2.0, 3.2);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.6, 0);
controls.enableDamping = true;
controls.update();

scene.add(new THREE.HemisphereLight(0xfff6ea, 0xb9a48c, 2.2));
const sun = new THREE.DirectionalLight(0xffffff, 1.4);
sun.position.set(2, 4, 3);
scene.add(sun);

const helpers = new THREE.Group();   // never exported
scene.add(helpers);
const grid = new THREE.GridHelper(6, 24, INK, INK);
grid.material.transparent = true;
grid.material.opacity = 0.12;
helpers.add(grid);

const items = new Map();             // id -> { id, kind, ref_id, url, object, outline }
const content = new THREE.Group();
scene.add(content);
let selected = null;
let dragMode = 'move';

// ------------------------------------------------------------------------------- save zone
const zone = { center: new THREE.Vector3(0, 0.6, 0), size: new THREE.Vector3(...ZONE_PRESETS.square), visible: MODE === 'edit' };
const zoneBox = new THREE.Mesh(
  new THREE.BoxGeometry(1, 1, 1),
  new THREE.MeshBasicMaterial({ color: TEAL, transparent: true, opacity: 0.08, depthWrite: false }));
const zoneEdges = new THREE.LineSegments(
  new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
  new THREE.LineDashedMaterial({ color: INK, dashSize: 0.05, gapSize: 0.035, transparent: true, opacity: 0.8 }));
zoneEdges.computeLineDistances();
const zoneAnchor = new THREE.Mesh(new THREE.SphereGeometry(0.025, 16, 12), new THREE.MeshBasicMaterial({ color: INK }));
helpers.add(zoneBox, zoneEdges, zoneAnchor);

function updateZone() {
  for (const o of [zoneBox, zoneEdges]) {
    o.position.copy(zone.center);
    o.scale.copy(zone.size);
    o.visible = zone.visible;
  }
  zoneAnchor.position.copy(zone.center);
  zoneAnchor.visible = zone.visible;
  zoneEdges.computeLineDistances();
  refreshZoneStates();
}

function zoneBox3() {
  return new THREE.Box3().setFromCenterAndSize(zone.center, zone.size);
}

function isInside(item) {
  const c = new THREE.Box3().setFromObject(item.object).getCenter(new THREE.Vector3());
  return zoneBox3().containsPoint(c);
}

function refreshZoneStates() {
  let inside = 0, outside = 0;
  for (const it of items.values()) {
    const inZone = isInside(it);
    inZone ? inside++ : outside++;
    it.outline.visible = zone.visible || it === selected;
    it.outline.material.color.setHex(it === selected ? TEAL : (inZone ? SAGE : RED));
    it.outline.update();
  }
  if (MODE === 'edit') post({ type: 'zoneStats', inside, outside });
}

// ----------------------------------------------------------------------------------- items
const texLoader = new THREE.TextureLoader();
texLoader.setCrossOrigin('anonymous');
const gltfLoader = new GLTFLoader();
gltfLoader.setCrossOrigin('anonymous');
let seq = 0;
const newId = () => `i${Date.now().toString(36)}${(seq++).toString(36)}`;

function wrapItem(spec, object) {
  object.userData.itemId = spec.id;
  const outline = new THREE.BoxHelper(object, SAGE);
  outline.material.transparent = true;
  outline.material.opacity = 0.9;
  helpers.add(outline);
  const it = { ...spec, object, outline };
  items.set(spec.id, it);
  content.add(object);
  return it;
}

function applyTransform(object, spec, fallbackPos) {
  if (spec.position) object.position.fromArray(spec.position); else object.position.copy(fallbackPos);
  if (spec.quaternion) object.quaternion.fromArray(spec.quaternion);
  if (spec.scale != null) object.scale.setScalar(spec.scale);
}

function dropPoint() {
  // New items land near the zone centre, nudged so they do not stack perfectly.
  const n = items.size;
  return zone.center.clone().add(new THREE.Vector3(((n % 3) - 1) * 0.25, ((n % 2) ? 0.15 : -0.1), (n % 4) * 0.04));
}

// TextureLoader rejects with a bare DOM Event ('[object Event]') when an image fails to load; say what failed.
async function loadTexture(url) {
  try { return await texLoader.loadAsync(url); } catch (e) {
    let host = url; try { host = new URL(url).host; } catch (_) {}
    throw new Error(`image failed to load from ${host} (is the server reachable?)`);
  }
}

async function addSticker(spec) {
  const tex = await loadTexture(spec.url);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  const aspect = tex.image.width / tex.image.height;
  const h = 0.45, w = h * aspect;
  const mat = new THREE.MeshStandardMaterial({ map: tex, transparent: true, alphaTest: 0.04, side: THREE.DoubleSide, roughness: 0.85 });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), mat);
  const id = spec.id || newId();
  applyTransform(mesh, spec, dropPoint());
  if (!spec.quaternion) mesh.lookAt(camera.position.x, mesh.position.y, camera.position.z);
  const it = wrapItem({ id, kind: 'sticker', ref_id: spec.ref_id, url: spec.url, title: spec.title }, mesh);
  select(it);
  refreshZoneStates();
  return it;
}

async function addMesh(spec) {
  const gltf = await gltfLoader.loadAsync(spec.url);
  const root = gltf.scene;
  // Normalise to ~0.5 units tall, centred on its base.
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  const k = (spec.fit || 0.5) / Math.max(size.x, size.y, size.z, 1e-6);
  const holder = new THREE.Group();
  root.scale.setScalar(k);
  root.position.set(-(box.min.x + size.x / 2) * k, -box.min.y * k, -(box.min.z + size.z / 2) * k);
  holder.add(root);
  const id = spec.id || newId();
  applyTransform(holder, spec, dropPoint());
  const it = wrapItem({ id, kind: 'mesh', ref_id: spec.ref_id, url: spec.url, title: spec.title }, holder);
  select(it);
  refreshZoneStates();
  return it;
}

function removeItem(it) {
  content.remove(it.object);
  helpers.remove(it.outline);
  it.object.traverse(o => { o.geometry?.dispose?.(); if (o.material) { o.material.map?.dispose?.(); o.material.dispose?.(); } });
  items.delete(it.id);
  if (selected === it) select(null);
}

function select(it) {
  selected = it;
  post({ type: 'selection', id: it?.id ?? null, kind: it?.kind ?? null, title: it?.title ?? null });
  refreshZoneStates();
}

// ---------------------------------------------------------------------- touch manipulation
const raycaster = new THREE.Raycaster();
const pointers = new Map();
let drag = null;

function ndc(e) {
  const r = renderer.domElement.getBoundingClientRect();
  return new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
}

function pick(e) {
  raycaster.setFromCamera(ndc(e), camera);
  const hits = raycaster.intersectObjects(content.children, true);
  for (const h of hits) {
    let o = h.object;
    while (o && !o.userData.itemId) o = o.parent;
    if (o) return items.get(o.userData.itemId);
  }
  return null;
}

function onDown(e) {
  if (MODE !== 'edit') return;
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pointers.size === 1) {
    const it = pick(e);
    if (it) {
      select(it);
      controls.enabled = false;
      const normal = camera.getWorldDirection(new THREE.Vector3()).negate();
      drag = {
        plane: new THREE.Plane().setFromNormalAndCoplanarPoint(normal, it.object.position),
        startObj: it.object.position.clone(),
        startHit: null, last: { x: e.clientX, y: e.clientY },
      };
      raycaster.setFromCamera(ndc(e), camera);
      drag.startHit = raycaster.ray.intersectPlane(drag.plane, new THREE.Vector3());
    } else if (!it) {
      select(null);
    }
  } else if (pointers.size === 2 && selected) {
    const [a, b] = [...pointers.values()];
    drag = { pinch: true, dist: Math.hypot(a.x - b.x, a.y - b.y), angle: Math.atan2(b.y - a.y, b.x - a.x),
             scale: selected.object.scale.x, quat: selected.object.quaternion.clone() };
    controls.enabled = false;
  }
}

function onMove(e) {
  if (!pointers.has(e.pointerId) || !drag || !selected) return;
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  const obj = selected.object;
  if (drag.pinch && pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    const d = Math.hypot(a.x - b.x, a.y - b.y);
    const ang = Math.atan2(b.y - a.y, b.x - a.x);
    obj.scale.setScalar(THREE.MathUtils.clamp(drag.scale * d / drag.dist, 0.05, 20));
    const axis = camera.getWorldDirection(new THREE.Vector3());
    obj.quaternion.copy(drag.quat).premultiply(new THREE.Quaternion().setFromAxisAngle(axis, ang - drag.angle));
  } else if (!drag.pinch) {
    const dx = e.clientX - drag.last.x, dy = e.clientY - drag.last.y;
    drag.last = { x: e.clientX, y: e.clientY };
    if (dragMode === 'move' && drag.startHit) {
      raycaster.setFromCamera(ndc(e), camera);
      const hit = raycaster.ray.intersectPlane(drag.plane, new THREE.Vector3());
      if (hit) obj.position.copy(drag.startObj).add(hit.sub(drag.startHit));
    } else if (dragMode === 'depth') {
      const fwd = camera.getWorldDirection(new THREE.Vector3());
      obj.position.addScaledVector(fwd, -dy * 0.005);
    } else if (dragMode === 'rotate') {
      obj.rotateOnWorldAxis(new THREE.Vector3(0, 1, 0), dx * 0.01);
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
      obj.rotateOnWorldAxis(right, dy * 0.01);
    } else if (dragMode === 'scale') {
      obj.scale.setScalar(THREE.MathUtils.clamp(obj.scale.x * (1 - dy * 0.006), 0.05, 20));
    }
  }
  refreshZoneStates();
}

function onUp(e) {
  pointers.delete(e.pointerId);
  if (pointers.size === 0) {
    drag = null;
    controls.enabled = true;
  }
}

renderer.domElement.addEventListener('pointerdown', onDown, { capture: true });
renderer.domElement.addEventListener('pointermove', onMove);
window.addEventListener('pointerup', onUp);
window.addEventListener('pointercancel', onUp);
// OrbitControls listens on the same element; while dragging an item we disable it in onDown (capture phase).

// --------------------------------------------------------------------------------- filters
const filters = { pixelate: 0, motionBlur: 0 };
let composer = null;

function pixelPass(size, cam) {
  const pass = new RenderPixelatedPass(size, scene, cam);
  // Edge outlines are off: the pass draws them from a depth/normal render that ignores sticker
  // transparency, which would outline each sticker's full rectangle.
  pass.normalEdgeStrength = 0;
  pass.depthEdgeStrength = 0;
  return pass;
}

function rebuildComposer() {
  composer?.dispose?.();
  composer = null;
  if (!filters.pixelate && !filters.motionBlur) return;
  composer = new EffectComposer(renderer);
  if (filters.pixelate) composer.addPass(pixelPass(filters.pixelate, camera));
  else composer.addPass(new RenderPass(scene, camera));
  if (filters.motionBlur) composer.addPass(new AfterimagePass(0.6 + 0.36 * filters.motionBlur));
  composer.addPass(new OutputPass());
  composer.setSize(window.innerWidth, window.innerHeight);
}

// ---------------------------------------------------------------------------------- export
function sceneJson() {
  return {
    version: 1,
    items: [...items.values()].map(it => ({
      id: it.id, kind: it.kind, ref_id: it.ref_id, title: it.title,
      position: it.object.position.toArray(),
      quaternion: it.object.quaternion.toArray(),
      scale: it.object.scale.x,
    })),
    zone: { center: zone.center.toArray(), size: zone.size.toArray() },
    filters: { ...filters },
    camera: { position: camera.position.toArray(), target: controls.target.toArray() },
  };
}

function exportCamera(aspect) {
  const dir = camera.getWorldDirection(new THREE.Vector3());
  const r = zone.size.length() / 2;
  const cam = new THREE.PerspectiveCamera(35, aspect, 0.01, 100);
  const dist = (r / Math.sin(THREE.MathUtils.degToRad(cam.fov / 2))) * 0.92;
  cam.position.copy(zone.center).addScaledVector(dir, -dist);
  cam.up.copy(camera.up);
  cam.lookAt(zone.center);
  cam.updateMatrixWorld();
  return cam;
}

async function loadImage(src) {
  const img = new Image();
  img.src = src;
  await img.decode();
  return img;
}

async function exportCollage({ resolution = 2048, background = 'paper', stereo = false }) {
  const aspect = THREE.MathUtils.clamp(zone.size.x / zone.size.y, 0.4, 2.5);
  const H = aspect >= 1 ? Math.round(resolution / aspect) : resolution;
  const W = aspect >= 1 ? resolution : Math.round(resolution * aspect);

  // Only what is inside the save zone is rendered. The workspace itself is left untouched.
  const hidden = [];
  for (const it of items.values()) if (!isInside(it)) { it.object.visible = false; hidden.push(it); }
  helpers.visible = false;

  const prev = { size: renderer.getSize(new THREE.Vector2()), ratio: renderer.getPixelRatio() };
  renderer.setPixelRatio(1);
  renderer.setSize(W, H, false);
  const opaque = background === 'paper' || filters.motionBlur > 0;
  renderer.setClearColor(PAPER, opaque ? 1 : 0);

  const out = document.createElement('canvas');
  out.width = stereo ? W * 2 : W;
  out.height = H;
  const ctx = out.getContext('2d');
  const eyes = stereo ? [-1, 1] : [0];
  const subframes = filters.motionBlur > 0 ? 10 : 1;

  eyes.forEach((eye, e) => {
    const base = exportCamera(W / H);
    const right = new THREE.Vector3().setFromMatrixColumn(base.matrixWorld, 0);
    const eyeSep = base.position.distanceTo(zone.center) * 0.035;
    for (let i = 0; i < subframes; i++) {
      const cam = base.clone();
      cam.position.addScaledVector(right, eye * eyeSep);
      if (subframes > 1) cam.position.addScaledVector(right, (i / (subframes - 1) - 0.5) * 0.12 * filters.motionBlur * zone.size.x);
      cam.lookAt(zone.center);
      if (filters.pixelate) {
        const c = new EffectComposer(renderer);
        c.setPixelRatio(1);
        c.setSize(W, H);
        c.addPass(pixelPass(Math.max(1, Math.round(filters.pixelate * W / window.innerWidth)), cam));
        c.addPass(new OutputPass());
        c.render();
        c.dispose();
      } else {
        renderer.render(scene, cam);
      }
      ctx.globalAlpha = 1 / (i + 1);  // running average = motion blur
      ctx.drawImage(renderer.domElement, e * W, 0, W, H);
    }
  });
  ctx.globalAlpha = 1;

  if (background === 'paper') {
    try {
      const grain = await loadImage('textures/paper_grain.png');
      ctx.fillStyle = ctx.createPattern(grain, 'repeat');
      ctx.fillRect(0, 0, out.width, out.height);
    } catch (_) { /* texture optional */ }
  }

  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(prev.ratio);
  renderer.setSize(prev.size.x, prev.size.y, false);
  helpers.visible = true;
  hidden.forEach(it => { it.object.visible = true; });
  rebuildComposer();

  const dataUrl = out.toDataURL('image/png');
  const b64 = dataUrl.slice(dataUrl.indexOf(',') + 1);
  const id = newId();
  const CHUNK = 256 * 1024;
  const total = Math.ceil(b64.length / CHUNK);
  for (let i = 0; i < total; i++) post({ type: 'export_chunk', id, index: i, total, data: b64.slice(i * CHUNK, (i + 1) * CHUNK) });
  post({ type: 'export_done', id, width: out.width, height: out.height, scene: sceneJson() });
  return { width: out.width, height: out.height, bytes: b64.length * 0.75 };
}

// ----------------------------------------------------------------------------- scene load
async function loadScene(data) {
  for (const it of [...items.values()]) removeItem(it);
  if (data.zone) {
    zone.center.fromArray(data.zone.center);
    zone.size.fromArray(data.zone.size);
  }
  for (const spec of data.items || []) {
    if (!spec.url) continue;
    try {
      if (spec.kind === 'mesh') await addMesh(spec); else await addSticker(spec);
    } catch (err) { post({ type: 'error', message: `Could not load ${spec.title || spec.kind}: ${err}` }); }
  }
  if (data.camera) {
    camera.position.fromArray(data.camera.position);
    controls.target.fromArray(data.camera.target);
    controls.update();
  }
  if (data.filters) { Object.assign(filters, data.filters); rebuildComposer(); }
  select(null);
  updateZone();
}

// ------------------------------------------------------------------------------- commands
const api = {
  async command(c) {
    try {
      switch (c.cmd) {
        case 'addSticker': return void await addSticker(c);
        case 'addMesh': return void await addMesh(c);
        case 'setMode': dragMode = c.mode; return;
        case 'deleteSelected': if (selected) removeItem(selected); refreshZoneStates(); return;
        case 'duplicateSelected': {
          if (!selected) return;
          const s = selected;
          const spec = { ref_id: s.ref_id, url: s.url, title: s.title, quaternion: s.object.quaternion.toArray(), scale: s.object.scale.x,
                         position: s.object.position.clone().add(new THREE.Vector3(0.12, 0.08, 0)).toArray() };
          return void await (s.kind === 'mesh' ? addMesh(spec) : addSticker(spec));
        }
        case 'zone':
          if (c.visible != null) zone.visible = c.visible;
          if (c.preset && ZONE_PRESETS[c.preset]) zone.size.fromArray(ZONE_PRESETS[c.preset]);  // snaps around the fixed centre anchor
          if (c.size) zone.size.fromArray(c.size);
          return updateZone();
        case 'zoneToSelection':
          if (selected) zone.center.copy(new THREE.Box3().setFromObject(selected.object).getCenter(new THREE.Vector3()));
          return updateZone();
        case 'clear': {
          for (const it of [...items.values()]) {
            const inZone = isInside(it);
            if (c.which === 'all' || (c.which === 'inside' && inZone) || (c.which === 'outside' && !inZone)) removeItem(it);
          }
          return refreshZoneStates();
        }
        case 'filters':
          if (c.pixelate != null) filters.pixelate = c.pixelate;
          if (c.motionBlur != null) filters.motionBlur = c.motionBlur;
          return rebuildComposer();
        case 'export': return await exportCollage(c);
        case 'load': return await loadScene(c.scene);
        case 'getScene': return post({ type: 'scene', scene: sceneJson() });
        default: post({ type: 'error', message: `unknown command ${c.cmd}` });
      }
    } catch (err) {
      post({ type: 'error', message: String(err) });
    }
  },
  _debug: { items, zone, scene, camera },
};
window.ScrappEditor = api;

// --------------------------------------------------------------------- viewer / model modes
async function startViewer() {
  zone.visible = false;
  updateZone();
  grid.visible = false;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 1.2;
  const src = params.get('src');
  try {
    const res = await fetch(src);
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    document.getElementById('title').textContent = data.title || 'Scrapp collage';
    document.getElementById('title').style.display = 'block';
    document.getElementById('brand').style.display = 'block';
    await loadScene(data.scene);
    for (const it of items.values()) it.outline.visible = false;
  } catch (err) {
    const m = document.getElementById('msg');
    m.textContent = 'This collage could not be loaded.';
    m.style.display = 'flex';
  }
}

async function startModelPreview() {
  // Mesh preview sits on a fuzzy grass pedestal (mesh-generation UI language).
  zone.visible = false;
  updateZone();
  grid.visible = false;
  controls.autoRotate = true;
  // The preview is the model on its own: fill it (it used to float small in the frame) and light it from several sides,
  // because black or dark PBR models vanished under the single key light used for collages.
  camera.position.set(2.2, 1.5, 3.0);
  controls.target.set(zone.center.x, zone.center.y + 0.4, zone.center.z);
  controls.minDistance = 0.8;
  controls.maxDistance = 6;
  controls.update();
  scene.children.filter((o) => o.isHemisphereLight).forEach((o) => { o.intensity = 3.2; });
  sun.intensity = 2.4;
  const fill = new THREE.DirectionalLight(0xfff1de, 1.6);
  fill.position.set(-3, 2, 2);
  const rim = new THREE.DirectionalLight(0xdfeaff, 1.8);
  rim.position.set(0, 3, -4);
  const under = new THREE.DirectionalLight(0xffffff, 0.9);
  under.position.set(0, -2, 3);
  scene.add(fill, rim, under);
  const grass = await texLoader.loadAsync('textures/fuzz_grass.jpg');
  grass.colorSpace = THREE.SRGBColorSpace;
  grass.wrapS = grass.wrapT = THREE.RepeatWrapping;
  grass.repeat.set(2, 2);
  const pedestal = new THREE.Mesh(new THREE.CylinderGeometry(0.7, 0.75, 0.08, 64),
    new THREE.MeshStandardMaterial({ map: grass, roughness: 1 }));
  pedestal.position.copy(zone.center).setY(zone.center.y - 0.04);
  helpers.add(pedestal);
  const src = params.get('src');
  if (src) {
    const it = await addMesh({ url: src, position: zone.center.toArray(), fit: 0.95 });
    it.outline.visible = false;
    selected = null;
  }
}

// ---------------------------------------------------------------------------------- loop
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  composer?.setSize(window.innerWidth, window.innerHeight);
});

renderer.setAnimationLoop(() => {
  controls.update();
  for (const it of items.values()) if (it.outline.visible) it.outline.update();
  if (composer) composer.render(); else renderer.render(scene, camera);
});

updateZone();
if (MODE === 'view') startViewer();
else if (MODE === 'model') startModelPreview();
post({ type: 'ready', mode: MODE });

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { HeadTracker, DEFAULT_CALIB, canvasPhysicalRect } from './headtrack.js';

const $ = (id) => document.getElementById(id);

// A 401 from any studio call means the session ended: go back to the login page
const _fetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const res = await _fetch(...args);
  const url = String(args[0]?.url || args[0]);
  if (res.status === 401 && url.startsWith('/api/') && !url.startsWith('/api/auth/')) location.href = '/login';
  return res;
};
const store = {
  get: (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};
const POLL_MS = 4000;
const MAX_SIDE = 2048; // downscale big photos before upload (faster, well within Meshy limits)

// =====================================================================
// three.js viewer
// =====================================================================
const canvas = $('viewer');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.shadowMap.enabled = true;

const scene = new THREE.Scene();
// Scrapp palette: warm cream paper by default, dark ink as the alternative
const paperBg = new THREE.Color(0xf1e7d3);
const darkBg = new THREE.Color(0x231c18);
scene.background = paperBg;
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
camera.position.set(2.6, 1.6, 2.6);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.autoRotate = false;
controls.autoRotateSpeed = 1.2;
controls.target.set(0, 0.5, 0);

const key = new THREE.DirectionalLight(0xffffff, 1.6);
key.position.set(3, 5, 2);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
Object.assign(key.shadow.camera, { left: -2, right: 2, top: 2, bottom: -2, near: 0.1, far: 20 });
scene.add(key, new THREE.HemisphereLight(0xffffff, 0x334, 0.4));

const ground = new THREE.Mesh(new THREE.CircleGeometry(3, 64), new THREE.ShadowMaterial({ opacity: 0.35 }));
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
const grid = new THREE.GridHelper(6, 24, 0xc9b597, 0xdccfb6);
scene.add(ground, grid);

const loader = new GLTFLoader();
const clock = new THREE.Clock();
let wireframe = false;

// =====================================================================
// Scene: several models at once
// headPivot → sceneRoot → one wrapper group per model
// → one wrapper group per model (moved / rotated / scaled with the gizmo).
// =====================================================================
const headPivot = new THREE.Group();
const sceneRoot = new THREE.Group();
sceneRoot.name = 'Scene';
headPivot.add(sceneRoot);
scene.add(headPivot);

const ITEM_SIZE = 1.0;  // every model is normalised so its largest side is 1 unit
const items = [];       // { uid, task, obj, mixer, tris, clips }
let uidSeq = 0;
let restoring = false;

const transform = new TransformControls(camera, canvas);
transform.setSize(0.8);
scene.add(transform.getHelper());
transform.addEventListener('dragging-changed', (e) => {
  controls.enabled = !e.value && head.mode === 'off';
  if (!e.value) { saveScene(); refitShadows(); updateHud(); }
});
let selected = null;
let selBox = null;

function sceneBox() {
  sceneRoot.updateMatrixWorld(true);
  const box = new THREE.Box3();
  for (const it of items) box.expandByObject(it.obj);
  return box;
}

// 2D sticker: the cut-out image on a double-sided card, standing on the floor
const textureLoader = new THREE.TextureLoader();
async function loadSticker(task) {
  const tex = await textureLoader.loadAsync(task.image);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  const { width: w, height: h } = tex.image;
  const sw = w >= h ? ITEM_SIZE : ITEM_SIZE * (w / h);
  const sh = h >= w ? ITEM_SIZE : ITEM_SIZE * (h / w);
  const mat = new THREE.MeshStandardMaterial({
    name: 'Sticker', map: tex, alphaTest: 0.5, side: THREE.DoubleSide, roughness: 0.6, // cut-out (glTF MASK)
  });
  const card = new THREE.Mesh(new THREE.PlaneGeometry(sw, sh), mat);
  card.name = 'StickerCard';
  card.position.y = sh / 2;
  card.castShadow = true;
  // Cut-out shadows: use the image's alpha so the shadow has the sticker's shape, not a rectangle
  card.customDepthMaterial = new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking, map: tex, alphaTest: 0.5 });
  mat.wireframe = wireframe;
  const obj = new THREE.Group();
  obj.name = task.name;
  obj.add(card);
  const item = {
    uid: ++uidSeq,
    task: { kind: 'sticker2d', id: task.id || null, name: task.name, image: task.image, stickerId: task.stickerId || null },
    obj, mixer: null, tris: 2, clips: [], billboard: false,
  };
  obj.userData.itemUid = item.uid;
  return item;
}

async function loadItem(task) {
  if (task.kind === 'sticker2d') return loadSticker(task);
  const gltf = await loader.loadAsync(task.glb);
  const model = gltf.scene;
  const box = new THREE.Box3().setFromObject(model);
  const size = box.getSize(new THREE.Vector3());
  model.scale.setScalar(ITEM_SIZE / Math.max(size.x, size.y, size.z));
  box.setFromObject(model);
  const c = box.getCenter(new THREE.Vector3());
  model.position.sub(new THREE.Vector3(c.x, box.min.y, c.z)); // centred, sitting on y = 0

  let tris = 0;
  model.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = true;
    o.receiveShadow = true;
    for (const m of [].concat(o.material)) m.wireframe = wireframe;
    const g = o.geometry;
    tris += (g.index ? g.index.count : g.attributes.position.count) / 3;
  });
  const obj = new THREE.Group();
  obj.name = task.name;
  obj.add(model);
  let mixer = null;
  if (gltf.animations?.length) {
    mixer = new THREE.AnimationMixer(model);
    mixer.clipAction(gltf.animations[0]).play();
  }
  const item = {
    uid: ++uidSeq,
    task: {
      id: task.id || null, name: task.name, glb: task.glb, dummy: Boolean(task.dummy), sample: Boolean(task.sample),
      meshId: task.meshId || task.mongoSave?.meshId || null, // "meshes" _id, if it lives in MongoDB
    },
    obj, mixer, tris, clips: gltf.animations || [],
  };
  obj.userData.itemUid = item.uid;
  return item;
}

function setLoading(on) { $('loading').hidden = !on; }

// Add a model next to what's already in the scene (or at a saved transform)
async function addToScene(task, saved = null) {
  setLoading(true);
  try {
    const item = await loadItem(task);
    if (saved?.collage) {
      // From a Scrapp collage: undo the unit conversion done in buildCollageScene()
      const c = saved.collage;
      item.obj.quaternion.fromArray(c.quaternion || [0, 0, 0, 1]);
      const sc = Number.isFinite(c.scale) ? c.scale : 1;
      if (item.task.kind === 'sticker2d') {
        const h = item.obj.children[0].geometry.parameters.height;
        const k = (SCRAPP_STICKER_H * sc) / UNIT / h;
        item.obj.scale.setScalar(k);
        const centre = new THREE.Vector3().fromArray(c.position || [0, 0, 0]).divideScalar(UNIT);
        item.obj.position.copy(centre.sub(new THREE.Vector3(0, (h * k) / 2, 0).applyQuaternion(item.obj.quaternion)));
      } else {
        item.obj.scale.setScalar(sc);
        item.obj.position.fromArray(c.position || [0, 0, 0]).divideScalar(UNIT);
      }
    } else if (saved) {
      item.obj.position.fromArray(saved.p);
      item.obj.quaternion.fromArray(saved.q);
      item.obj.scale.fromArray(saved.s);
      item.billboard = Boolean(saved.bb);
    } else if (items.length) {
      // Place it to the right of everything, in sceneRoot's local space
      const inv = sceneRoot.matrixWorld.clone().invert();
      const local = sceneBox().applyMatrix4(inv);
      const own = new THREE.Box3().setFromObject(item.obj);
      item.obj.position.set(local.max.x + 0.25 + (own.max.x - own.min.x) / 2, 0, (local.min.z + local.max.z) / 2);
    }
    sceneRoot.add(item.obj);
    items.push(item);
    afterSceneChange({ fit: !saved });
    return item;
  } catch (e) {
    console.error(e);
    if (!saved) flash(`Couldn't load "${task.name}": ${e.message}`);
    return null;
  } finally {
    setLoading(false);
  }
}

function disposeObject(obj) {
  obj.traverse((o) => {
    if (!o.isMesh) return;
    o.geometry.dispose();
    for (const m of [].concat(o.material)) {
      for (const v of Object.values(m)) if (v?.isTexture) v.dispose();
      m.dispose();
    }
  });
}

function removeItem(item, { quiet = false } = {}) {
  if (selected === item) deselect();
  sceneRoot.remove(item.obj);
  disposeObject(item.obj);
  items.splice(items.indexOf(item), 1);
  if (!quiet) afterSceneChange({ fit: false });
}

function clearScene() {
  for (const it of [...items]) removeItem(it, { quiet: true });
  afterSceneChange({ fit: false });
}

// Clicking a model in the gallery shows it on its own
async function showModel(task) {
  clearScene();
  return addToScene(task);
}

// Finished generations: replace the scene if it only holds the sample, otherwise add
function showOrAdd(task) {
  return items.every((i) => i.task.sample) ? showModel(task) : addToScene(task);
}

function afterSceneChange({ fit }) {
  updateHud();
  if (!restoring) saveScene();
  if (fit && head.mode === 'off') fitCamera();
  refitShadows();
}

function fitCamera() {
  if (!items.length) { resetCamera(); return; }
  const box = sceneBox();
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z, 0.5);
  const dist = (maxDim / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2))) * 1.5 + maxDim * 0.5;
  const dir = new THREE.Vector3(1, 0.6, 1).normalize();
  camera.position.copy(center).addScaledVector(dir, dist);
  controls.target.copy(center);
  camera.near = dist / 100;
  camera.far = dist * 30;
  camera.updateProjectionMatrix();
  controls.update();
}

function refitShadows() {
  const box = sceneBox();
  const size = items.length ? box.getSize(new THREE.Vector3()) : new THREE.Vector3(1, 1, 1);
  const c = items.length ? box.getCenter(new THREE.Vector3()) : new THREE.Vector3();
  const r = Math.max(2, Math.max(size.x, size.z) * 0.9);
  Object.assign(key.shadow.camera, { left: -r, right: r, top: r, bottom: -r });
  key.shadow.camera.updateProjectionMatrix();
  key.position.set(c.x + 3, 5 + size.y, c.z + 2);
  key.target.position.set(c.x, 0, c.z);
  key.target.updateMatrixWorld();
  ground.scale.setScalar(Math.max(1, r / 2));
  ground.position.set(c.x, 0.001, c.z);
}

function updateHud() {
  const n = items.length;
  $('toolbar').hidden = false;
  $('placeholder').hidden = n > 0;
  if (!n) $('placeholder').querySelector('p').textContent = 'The scene is empty. Click a model, + to add one, or 2D for a sticker.';
  $('modelTitle').textContent = n === 1
    ? items[0].task.name + (items[0].task.dummy ? ' (dummy)' : '')
    : `Scene · ${n} items`;
  $('stats').hidden = !n;
  const tris = items.reduce((a, i) => a + i.tris, 0);
  const stickers = items.filter((i) => i.task.kind === 'sticker2d').length;
  const models = n - stickers;
  const parts = [models && `${models} model${models === 1 ? '' : 's'}`, stickers && `${stickers} sticker${stickers === 1 ? '' : 's'}`].filter(Boolean);
  $('stats').textContent = `${parts.join(' + ') || 'empty'} · ${Math.round(tris).toLocaleString()} triangles` +
    (selected ? ` · selected: ${selected.task.name}` : ' · click an item to move it');
  $('clearBtn').disabled = !n;
}

function saveScene() {
  store.set('scene', items.map((i) => ({
    task: i.task, p: i.obj.position.toArray(), q: i.obj.quaternion.toArray(), s: i.obj.scale.toArray(),
    ...(i.billboard ? { bb: true } : {}),
  })));
}

async function restoreScene() {
  const saved = store.get('scene', []);
  if (!Array.isArray(saved) || !saved.length) return false;
  restoring = true;
  const loaded = await Promise.all(saved.map((s) => addToScene(s.task, s)));
  restoring = false;
  saveScene();
  if (head.mode === 'off') fitCamera();
  return loaded.some(Boolean);
}

const _camLocal = new THREE.Vector3();
function faceCamera() {
  for (const it of items) {
    if (!it.billboard) continue;
    it.obj.parent.updateWorldMatrix(true, false);
    _camLocal.copy(camera.position);
    it.obj.parent.worldToLocal(_camLocal);
    it.obj.rotation.set(0, Math.atan2(_camLocal.x - it.obj.position.x, _camLocal.z - it.obj.position.z), 0);
  }
}

// ----- selection + gizmo -----
function select(item) {
  if (selected === item) return;
  deselect();
  selected = item;
  transform.attach(item.obj);
  selBox = new THREE.BoxHelper(item.obj, 0x4e8288);
  scene.add(selBox);
  $('selBar').hidden = false;
  $('selName').textContent = item.task.name;
  $('billboardBtn').hidden = item.task.kind !== 'sticker2d';
  $('billboardBtn').classList.toggle('on', Boolean(item.billboard));
  updateHud();
}

function deselect() {
  if (!selected) return;
  transform.detach();
  if (selBox) { scene.remove(selBox); selBox.geometry.dispose(); selBox = null; }
  selected = null;
  $('selBar').hidden = true;
  updateHud();
}

function setGizmoMode(mode) {
  transform.setMode(mode);
  document.querySelectorAll('#selBar [data-mode]').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
}

const raycaster = new THREE.Raycaster();
let downAt = null;
canvas.addEventListener('pointerdown', (e) => { downAt = { x: e.clientX, y: e.clientY }; });
canvas.addEventListener('pointerup', (e) => {
  if (!downAt || transform.dragging) return;
  const moved = Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y);
  downAt = null;
  if (moved > 5) return; // that was an orbit / drag, not a click
  const r = canvas.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const hit = raycaster.intersectObjects(sceneRoot.children, true)[0];
  let o = hit?.object;
  while (o && o.userData.itemUid === undefined) o = o.parent;
  const item = o && items.find((i) => i.uid === o.userData.itemUid);
  if (item) select(item);
  else deselect();
});

window.addEventListener('keydown', (e) => {
  if (e.target.closest('input, textarea, select')) return;
  const k = e.key.toLowerCase();
  if (k === 'escape') deselect();
  if (!selected) return;
  if (k === 'w') setGizmoMode('translate');
  if (k === 'e') setGizmoMode('rotate');
  if (k === 'r') setGizmoMode('scale');
  if (k === 'delete' || k === 'backspace') { e.preventDefault(); removeItem(selected); }
});

$('selBar').addEventListener('click', async (e) => {
  const b = e.target.closest('button');
  if (!b || !selected) return;
  if (b.dataset.mode) setGizmoMode(b.dataset.mode);
  if (b.dataset.sel === 'remove') removeItem(selected);
  if (b.dataset.sel === 'billboard') {
    selected.billboard = !selected.billboard;
    b.classList.toggle('on', selected.billboard);
    if (!selected.billboard) selected.obj.rotation.set(0, 0, 0);
    saveScene();
  }
  if (b.dataset.sel === 'duplicate') {
    const src = selected;
    const copy = await addToScene(src.task, {
      p: src.obj.position.clone().add(new THREE.Vector3(0.3, 0, 0.3)).toArray(),
      q: src.obj.quaternion.toArray(), s: src.obj.scale.toArray(),
    });
    if (copy) { copy.billboard = src.billboard; saveScene(); select(copy); }
  }
  if (b.dataset.sel === 'ground') {
    // Drop onto the floor: lowest point at y = 0
    const inv = sceneRoot.matrixWorld.clone().invert();
    const bb = new THREE.Box3().setFromObject(selected.obj).applyMatrix4(inv);
    selected.obj.position.y -= bb.min.y;
    saveScene();
  }
});

// Export everything in the scene as one GLB (original file when it's a single untouched model)
async function downloadScene() {
  if (!items.length) return;
  const one = items.length === 1 ? items[0] : null;
  if (one && one.task.glb && one.obj.position.lengthSq() === 0 && one.obj.quaternion.equals(new THREE.Quaternion()) && one.obj.scale.equals(new THREE.Vector3(1, 1, 1))) {
    const a = Object.assign(document.createElement('a'), { href: one.task.glb, download: `${slug(one.task.name)}.glb` });
    a.click();
    return;
  }
  const exporter = new GLTFExporter();
  const wasWire = wireframe;
  if (wasWire) setWireframe(false);
  const glb = await exporter.parseAsync(items.map((i) => i.obj), {
    binary: true, animations: items.flatMap((i) => i.clips),
  });
  if (wasWire) setWireframe(true);
  const url = URL.createObjectURL(new Blob([glb], { type: 'model/gltf-binary' }));
  Object.assign(document.createElement('a'), { href: url, download: one ? `${slug(one.task.name)}.glb` : 'scene.glb' }).click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

function setWireframe(on) {
  wireframe = on;
  for (const it of items) it.obj.traverse((o) => o.isMesh && [].concat(o.material).forEach((m) => (m.wireframe = on)));
}

// =====================================================================
// Save the scene as a Scrapp collage
// Scrapp's editor normalises meshes to 0.5 units (largest side, base-centred) and stickers to
// 0.45 units tall (positioned by their centre), with one uniform scale. Convert to that.
// =====================================================================
const SCRAPP_MESH = 0.5, SCRAPP_STICKER_H = 0.45;
const UNIT = SCRAPP_MESH / ITEM_SIZE; // our units → Scrapp units

function buildCollageScene() {
  const out = [], skipped = [];
  const box = new THREE.Box3();
  items.forEach((it, i) => {
    it.obj.updateMatrix(); // local to sceneRoot, so head-mode fitting doesn't leak in
    const s = it.obj.scale;
    const uni = Math.cbrt(Math.abs(s.x * s.y * s.z)) || 1;
    const name = it.task.name;
    if (it.task.kind === 'sticker2d') {
      if (!it.task.stickerId) { skipped.push(`${name} (not from the stickers collection)`); return; }
      const card = it.obj.children[0];
      const h = card.geometry.parameters.height;
      const centre = new THREE.Vector3(0, h / 2, 0).applyMatrix4(it.obj.matrix);
      out.push({
        id: `w${i + 1}`, kind: 'sticker', ref_id: it.task.stickerId, title: name,
        position: centre.multiplyScalar(UNIT).toArray(), quaternion: it.obj.quaternion.toArray(),
        scale: +((h * uni * UNIT) / SCRAPP_STICKER_H).toFixed(4),
      });
    } else {
      const meshId = it.task.meshId || tasks.find((t) => t.id && t.id === it.task.id)?.mongoSave?.meshId;
      if (!meshId) { skipped.push(`${name} (${it.task.sample || it.task.dummy ? 'sample/dummy model' : 'model'} not saved in MongoDB)`); return; }
      out.push({
        id: `w${i + 1}`, kind: 'mesh', ref_id: meshId, title: name,
        position: it.obj.position.clone().multiplyScalar(UNIT).toArray(), quaternion: it.obj.quaternion.toArray(),
        scale: +uni.toFixed(4),
      });
    }
    const b = new THREE.Box3().setFromObject(it.obj);
    // setFromObject is in world space; undo sceneRoot's head-mode fit to get sceneRoot-local space
    b.applyMatrix4(sceneRoot.matrixWorld.clone().invert());
    box.union(b);
  });

  // Save zone: snug around what's included, in Scrapp units
  let zone = { center: [0, 0.6, 0], size: [1.2, 1.2, 1.2] };
  if (!box.isEmpty()) {
    const c = box.getCenter(new THREE.Vector3()).multiplyScalar(UNIT);
    const sz = box.getSize(new THREE.Vector3()).multiplyScalar(UNIT * 1.15).max(new THREE.Vector3(0.3, 0.3, 0.3));
    zone = { center: c.toArray(), size: sz.toArray() };
  }
  // Camera: current view when orbiting; otherwise a front-ish view of the zone
  const target = new THREE.Vector3().fromArray(zone.center);
  let camPos;
  if (head.mode === 'off') {
    camPos = camera.position.clone().multiplyScalar(UNIT);
    target.copy(controls.target).multiplyScalar(UNIT);
  } else {
    const r = new THREE.Vector3().fromArray(zone.size).length();
    camPos = target.clone().add(new THREE.Vector3(0.5, 0.45, 1).normalize().multiplyScalar(r * 1.4));
  }
  return {
    scene: {
      version: 1, items: out, zone, filters: { pixelate: 0, motionBlur: 0 },
      camera: { position: camPos.toArray(), target: target.toArray() },
    },
    skipped,
  };
}

// PNG of the current view (without gizmo / selection box / head-mode room) for the collage thumbnail
function snapshot(maxSide = 640) {
  const hidden = [transform.getHelper(), selBox, head.room].filter(Boolean).filter((o) => o.visible);
  hidden.forEach((o) => (o.visible = false));
  renderer.render(scene, camera);
  const src = renderer.domElement;
  const k = Math.min(1, maxSide / Math.max(src.width, src.height));
  const c = Object.assign(document.createElement('canvas'), { width: Math.round(src.width * k), height: Math.round(src.height * k) });
  c.getContext('2d').drawImage(src, 0, 0, c.width, c.height);
  hidden.forEach((o) => (o.visible = true));
  return c.toDataURL('image/png');
}

function openCollageDialog() {
  if (!items.length) return flash('Add something to the scene first.');
  const { scene: sc, skipped } = buildCollageScene();
  const last = store.get('lastCollage', null);
  $('collageTitle').value = last?.title || (items.length === 1 ? items[0].task.name : 'Web scene');
  $('collageUpdateWrap').hidden = !last;
  $('collageUpdate').checked = Boolean(last);
  if (last) $('collageUpdateLabel').textContent = `Update "${last.title}" instead of saving a new collage`;
  $('collageSummary').textContent = sc.items.length
    ? `${sc.items.filter((i) => i.kind === 'mesh').length} model(s) and ${sc.items.filter((i) => i.kind === 'sticker').length} sticker(s) will be saved.`
    : 'Nothing in this scene can be saved yet.';
  $('collageSkipped').hidden = !skipped.length;
  $('collageSkipped').textContent = skipped.length ? `Left out (not in MongoDB): ${skipped.join(', ')}` : '';
  $('collageSave').disabled = !sc.items.length;
  $('collageResult').hidden = true;
  $('collageDialog').showModal();
}

$('collageSave').onclick = async () => {
  const { scene: sc } = buildCollageScene();
  const last = store.get('lastCollage', null);
  const title = $('collageTitle').value.trim() || 'Web scene';
  const btn = $('collageSave');
  btn.disabled = true;
  btn.textContent = 'Saving…';
  try {
    const res = await fetch('/api/collages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title, scene: sc, thumbnail: snapshot(),
        collageId: $('collageUpdate').checked && last ? last.id : undefined,
      }),
    });
    const data = await readJson(res);
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    store.set('lastCollage', { id: data.id, title: data.title });
    loadCollages();
    $('collageResult').className = 'ok-text';
    $('collageResult').textContent = `${data.updated ? 'Updated' : 'Saved'} "${data.title}" to collages · ${data.itemCount} item(s)` +
      (data.dropped?.length ? ` · ${data.dropped.length} reference(s) no longer in MongoDB were dropped` : '');
  } catch (err) {
    $('collageResult').className = 'error';
    $('collageResult').textContent = `Couldn't save: ${err.message}`;
  } finally {
    $('collageResult').hidden = false;
    btn.disabled = false;
    btn.textContent = 'Save collage';
  }
};

let flashTimer;
// Read a JSON response; an HTML page back means the route doesn't exist on the running server
async function readJson(res) {
  const text = await res.text();
  try { return text ? JSON.parse(text) : {}; } catch {
    const missing = /Cannot (GET|POST|PUT|DELETE)/.test(text) || res.status === 404;
    throw new Error(missing
      ? `the server doesn't have this feature yet (${res.status}). Restart it (Ctrl+C, then npm start) so it runs the latest code.`
      : `the server sent back a page instead of data (${res.status}).`);
  }
}

function flash(msg, kind = 'error') {
  $('flash').textContent = msg;
  $('flash').className = `flash ${kind}`;
  $('flash').hidden = false;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => ($('flash').hidden = true), 4000);
}

function resize() {
  const { clientWidth: w, clientHeight: h } = canvas.parentElement;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  if (head.mode === 'off') camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(canvas.parentElement);

// =====================================================================
// Off-axis projection ("looking through a window")
// The canvas is treated as a real window in the physical screen. The camera is placed
// where the viewer's eyes are and an asymmetric frustum is aimed through the canvas
// rectangle, so the model appears to sit *behind* the glass and shifts with your head.
// =====================================================================
const head = {
  mode: 'off',          // 'off' | 'webcam' | 'mouse'
  tracker: new HeadTracker(store.get('headCalib', DEFAULT_CALIB)),
  mouseEye: { x: 0, y: 0, z: 60 },
  strength: store.get('headStrength', 1),  // exaggerates sideways/vertical motion
  popOut: store.get('headPopOut', 0.4),    // how far the model pokes out of the screen (0–1)
  dragging: null,
  room: null,
  roomSize: '',
};

// Wireframe room behind the glass — strong depth cue (Johnny Lee style)
function buildRoom(w, h, depth) {
  const key = `${w.toFixed(3)}x${h.toFixed(3)}x${depth.toFixed(3)}`;
  if (head.roomSize === key && head.room) return;
  if (head.room) { scene.remove(head.room); head.room.geometry.dispose(); }
  const pts = [];
  const line = (a, b) => pts.push(...a, ...b);
  const x0 = -w / 2, x1 = w / 2, y0 = -h / 2, y1 = h / 2, z0 = 0, z1 = -depth;
  const N = 8;
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    const x = x0 + (x1 - x0) * t, y = y0 + (y1 - y0) * t, z = z0 + (z1 - z0) * t;
    line([x, y0, z0], [x, y0, z1]); line([x, y1, z0], [x, y1, z1]);  // floor + ceiling, lengthwise
    line([x0, y, z0], [x0, y, z1]); line([x1, y, z0], [x1, y, z1]);  // side walls, lengthwise
    line([x, y0, z1], [x, y1, z1]); line([x0, y, z1], [x1, y, z1]);  // back wall grid
    line([x0, y0, z], [x1, y0, z]); line([x0, y1, z], [x1, y1, z]);  // depth rings
    line([x0, y0, z], [x0, y1, z]); line([x1, y0, z], [x1, y1, z]);
  }
  const geo = new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
  head.room = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0x4e8288, transparent: true, opacity: 0.35 }));
  head.roomSize = key;
  scene.add(head.room);
}

function currentEyeCm() {
  if (head.mode === 'mouse') return head.mouseEye;
  return head.tracker.eye;
}

// The view you were on when head mode started. The canvas becomes a window onto exactly that view:
// with your head centred (or the mouse in the middle) you see the same picture, and moving your head
// shifts the perspective around it.
const base = { target: new THREE.Vector3(), quat: new THREE.Quaternion(), dist: 3 };
const NEUTRAL_EYE_CM = 60;
function captureBaseView() {
  base.target.copy(controls.target);
  base.quat.copy(camera.quaternion);
  base.dist = Math.max(camera.position.distanceTo(controls.target), 0.05);
}
// Drag / auto-rotate in head mode: orbit the base view around its target (world up)
const _yAxis = new THREE.Vector3(0, 1, 0);
function orbitBase(dTheta) {
  base.quat.premultiply(new THREE.Quaternion().setFromAxisAngle(_yAxis, dTheta));
}
function basePosition(out = new THREE.Vector3()) {
  return out.set(0, 0, 1).applyQuaternion(base.quat).multiplyScalar(base.dist).add(base.target);
}

const _right = new THREE.Vector3(), _up = new THREE.Vector3(), _back = new THREE.Vector3(), _centre = new THREE.Vector3();
function applyOffAxis() {
  const calib = head.tracker.calib;
  const rect = canvasPhysicalRect(canvas, calib.screenWidthCm);
  _right.set(1, 0, 0).applyQuaternion(base.quat);
  _up.set(0, 1, 0).applyQuaternion(base.quat);
  _back.set(0, 0, 1).applyQuaternion(base.quat);

  // Glass plane: through the target at Pop-out 40%; more pop-out pushes it behind the target
  const planeDist = base.dist * (1 + (head.popOut - 0.4) * 0.8);
  const winH = 2 * planeDist * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2); // same framing as the orbit view
  const winW = winH * (rect.width / rect.height);
  const k = winH / rect.height; // world units per cm of head movement across the canvas

  const eye = currentEyeCm();
  // Eye relative to the canvas centre (webcam mode); mouse mode is already canvas-relative.
  const rel = head.mode === 'mouse' ? eye : { x: eye.x - rect.cx, y: eye.y - rect.cy, z: eye.z };
  const ex = rel.x * k * head.strength;
  const ey = rel.y * k * head.strength;
  const ez = Math.max(planeDist * (rel.z / NEUTRAL_EYE_CM), planeDist * 0.25); // 60 cm away = the orbit view

  // Window centre sits planeDist in front of where the orbit camera was
  basePosition(_centre).addScaledVector(_back, -planeDist);
  buildRoom(winW, winH, planeDist * 1.2);
  head.room.position.copy(_centre);
  head.room.quaternion.copy(base.quat);

  camera.position.copy(_centre).addScaledVector(_right, ex).addScaledVector(_up, ey).addScaledVector(_back, ez);
  camera.quaternion.copy(base.quat); // keeps your angle; the frustum does the skewing
  const n = planeDist * 0.01, far = planeDist * 60;
  camera.near = n; camera.far = far;
  camera.projectionMatrix.makePerspective(
    ((-winW / 2 - ex) * n) / ez, ((winW / 2 - ex) * n) / ez,
    ((winH / 2 - ey) * n) / ez, ((-winH / 2 - ey) * n) / ez,
    n, far,
  );
  camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
}

renderer.setAnimationLoop(() => {
  const dt = clock.getDelta();
  for (const it of items) it.mixer?.update(dt);
  faceCamera();
  selBox?.update();
  if (head.mode === 'off') {
    controls.update();
  } else {
    if (controls.autoRotate && !head.dragging) orbitBase(dt * 0.35);
    applyOffAxis();
    updateHeadStatus();
  }
  renderer.render(scene, camera);
});

function resetCamera() {
  camera.position.set(2.6, 1.6, 2.6);
  controls.target.set(0, 0.5, 0);
  controls.update();
}

// Toolbar
$('toolbar').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-action]');
  if (!btn) return;
  switch (btn.dataset.action) {
    case 'rotate':
      controls.autoRotate = !controls.autoRotate;
      btn.classList.toggle('on', controls.autoRotate);
      break;
    case 'wireframe':
      setWireframe(!wireframe);
      btn.classList.toggle('on', wireframe);
      break;
    case 'bg': {
      const dark = scene.background !== darkBg;
      scene.background = dark ? darkBg : paperBg;
      grid.material.opacity = dark ? 0.35 : 1;
      grid.material.transparent = dark;
      btn.classList.toggle('on', dark);
      break;
    }
    case 'reset':
      fitCamera();
      if (head.mode !== 'off') captureBaseView();
      break;
    case 'download':
      downloadScene().catch((err) => flash(`Export failed: ${err.message}`));
      break;
    case 'addSample':
      addToScene(SAMPLE);
      break;
    case 'clear':
      clearScene();
      break;
    case 'collage':
      openCollageDialog();
      break;
    case 'head':
      if (head.mode === 'off') enterHeadMode(store.get('headSource', 'webcam'));
      else exitHeadMode();
      break;
    case 'snippet':
      openSnippet();
      break;
  }
});

// =====================================================================
// Head-tracking mode: UI + lifecycle
// =====================================================================
async function enterHeadMode(source) {
  const prev = head.mode;
  head.mode = source;
  store.set('headSource', source);
  controls.enabled = false;
  grid.visible = false;
  $('headPanel').hidden = false;
  $('headBtn').classList.add('on');
  $('headSource').value = source;
  $('headVideoWrap').hidden = source !== 'webcam';
  $('headError').hidden = true;
  if (source === 'webcam' && !head.tracker.running) {
    $('headStatus').textContent = 'Starting camera…';
    try {
      await head.tracker.start($('headVideo'));
    } catch (e) {
      console.error(e);
      $('headError').textContent = `Webcam unavailable (${e.message}). Using the mouse instead.`;
      $('headError').hidden = false;
      head.mode = 'mouse';
      $('headSource').value = 'mouse';
      $('headVideoWrap').hidden = true;
    }
  }
  if (source === 'mouse' && head.tracker.running) head.tracker.stop();
  if (prev === 'off') captureBaseView(); // keep the angle you were looking from
}

function exitHeadMode() {
  head.mode = 'off';
  head.tracker.stop();
  if (head.room) { scene.remove(head.room); head.room = null; head.roomSize = ''; }
  controls.enabled = true;
  grid.visible = true;
  $('headPanel').hidden = true;
  $('headBtn').classList.remove('on');
  camera.near = 0.01; camera.far = 100;
  camera.quaternion.identity();
  basePosition(camera.position);
  camera.quaternion.copy(base.quat);
  controls.target.copy(base.target);
  camera.near = base.dist / 100;
  camera.far = base.dist * 30;
  camera.updateProjectionMatrix();
  controls.update();
  refitShadows();
}

function updateHeadStatus() {
  if (head.mode === 'mouse') {
    $('headStatus').textContent = 'Mouse mode: move the pointer over the view';
    return;
  }
  const t = head.tracker;
  if (!t.running) return;
  $('headStatus').textContent = t.tracking
    ? `Tracking · ${Math.round(t.eye.z)} cm away · x ${t.eye.x.toFixed(1)} y ${t.eye.y.toFixed(1)}`
    : 'Looking for your face…';
  // Eye markers on the (mirrored) preview
  const dots = $('headDots');
  if (t.raw) {
    const { rEye, lEye } = t.raw;
    dots.hidden = false;
    dots.children[0].style.cssText = `left:${(1 - rEye.x) * 100}%;top:${rEye.y * 100}%`;
    dots.children[1].style.cssText = `left:${(1 - lEye.x) * 100}%;top:${lEye.y * 100}%`;
  } else dots.hidden = true;
}

// Mouse fallback: pointer position = where your head is (great for testing without a webcam)
canvas.addEventListener('pointermove', (e) => {
  if (head.mode === 'off') return;
  const r = canvas.getBoundingClientRect();
  if (head.dragging && !transform.dragging) {
    orbitBase(-(e.clientX - head.dragging.x) * 0.01);
    head.dragging.x = e.clientX;
  }
  if (head.mode === 'mouse') {
    const rect = canvasPhysicalRect(canvas, head.tracker.calib.screenWidthCm);
    // Edge of the canvas ≈ your head level with that edge of the window
    head.mouseEye.x = ((e.clientX - r.left) / r.width - 0.5) * rect.width;
    head.mouseEye.y = -((e.clientY - r.top) / r.height - 0.5) * rect.height;
  }
});
canvas.addEventListener('pointerdown', (e) => {
  if (head.mode === 'off' || transform.dragging || transform.axis) return;
  head.dragging = { x: e.clientX };
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointerup', () => { head.dragging = null; });
canvas.addEventListener('wheel', (e) => {
  if (head.mode !== 'mouse') return;
  e.preventDefault();
  head.mouseEye.z = THREE.MathUtils.clamp(head.mouseEye.z + e.deltaY * 0.05, 20, 150);
}, { passive: false });

$('headSource').onchange = (e) => enterHeadMode(e.target.value);
$('headClose').onclick = exitHeadMode;

// Calibration sliders (persisted)
const calibInputs = {
  screenWidthCm: { el: 'calScreen', fmt: (v) => `${v} cm` },
  cameraFovDeg: { el: 'calFov', fmt: (v) => `${v}°` },
  smoothing: { el: 'calSmooth', fmt: (v) => Number(v).toFixed(2) },
};
for (const [key, { el, fmt }] of Object.entries(calibInputs)) {
  const input = $(el);
  input.value = head.tracker.calib[key];
  input.nextElementSibling.textContent = fmt(input.value);
  input.oninput = () => {
    head.tracker.calib[key] = Number(input.value);
    input.nextElementSibling.textContent = fmt(input.value);
    store.set('headCalib', head.tracker.calib);
  };
}
for (const [key, el, fmt] of [['strength', 'calStrength', (v) => `${Number(v).toFixed(1)}×`], ['popOut', 'calPop', (v) => `${Math.round(v * 100)}%`]]) {
  const input = $(el);
  input.value = head[key];
  input.nextElementSibling.textContent = fmt(input.value);
  input.oninput = () => {
    head[key] = Number(input.value);
    input.nextElementSibling.textContent = fmt(input.value);
    store.set(key === 'strength' ? 'headStrength' : 'headPopOut', head[key]);
  };
}
$('calReset').onclick = () => {
  head.tracker.calib = { ...DEFAULT_CALIB };
  store.set('headCalib', head.tracker.calib);
  for (const [key, { el, fmt }] of Object.entries(calibInputs)) {
    $(el).value = DEFAULT_CALIB[key];
    $(el).nextElementSibling.textContent = fmt(DEFAULT_CALIB[key]);
  }
};

function openSnippet() {
  if (!items.length) return;
  const file = items.length === 1 ? `${slug(items[0].task.name)}.glb` : 'scene.glb';
  $('snippetCode').textContent = `import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const loader = new GLTFLoader();
loader.load('/models/${file}', (gltf) => {
  const model = gltf.scene;

  // Meshy models come in arbitrary units — normalize to 1 unit tall
  const box = new THREE.Box3().setFromObject(model);
  const size = box.getSize(new THREE.Vector3());
  model.scale.setScalar(1 / size.y);
  box.setFromObject(model);
  model.position.y -= box.min.y; // sit on the ground

  model.traverse((o) => {
    if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; }
  });

  scene.add(model);
});

// PBR materials look best with an environment map:
// import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
// scene.environment = new THREE.PMREMGenerator(renderer)
//   .fromScene(new RoomEnvironment(), 0.04).texture;`;
  $('snippetDialog').showModal();
}
$('copySnippet').onclick = async () => {
  await navigator.clipboard.writeText($('snippetCode').textContent);
  $('copySnippet').textContent = 'Copied ✓';
  setTimeout(() => ($('copySnippet').textContent = 'Copy'), 1500);
};

// =====================================================================
// App shell: Scrap / Book / Studio / Friends (same sections as the Scrapp app, minus Hunts)
// =====================================================================
let tasks = [];
let activeId = null;
let me = null;          // users._id of the signed-in Scrapp account (set at boot from /api/config)
let mongoCfg = null;
const DONE = (t) => t.glb || t.status === 'FAILED' || t.status === 'CANCELED';
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const icon = (name, cls = '') => `<svg class="ic ${cls}"><use href="#i-${name}" /></svg>`;

async function api(url, opts) {
  const res = await fetch(url, opts && opts.body && typeof opts.body !== 'string'
    ? { ...opts, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(opts.body) } : opts);
  if (res.status === 401) { location.href = '/login'; throw new Error('Please sign in.'); }
  const data = res.status === 204 ? null : await readJson(res);
  if (!res.ok) throw new Error(data?.error || `Request failed (${res.status})`);
  return data;
}

function emptyCard(iconName, title, body) {
  return `<div class="card empty">${icon(iconName, 'xl')}<div><strong>${esc(title)}</strong><p>${esc(body)}</p></div></div>`;
}

// ----- tabs -----
let tab = store.get('tab', 'scrap');
const loaded = new Set();
function showTab(name) {
  tab = name;
  store.set('tab', name);
  document.querySelectorAll('.bottom-nav button').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach((p) => (p.hidden = p.dataset.panel !== name));
  if (!loaded.has(name)) { loaded.add(name); refreshTab(name); }
}
function refreshTab(name = tab) {
  if (name === 'scrap') capBrowser.load(true);
  if (name === 'book') bookBrowser.load(true);
  if (name === 'studio') { loadCollages(); if (studioView === '3d') meshBrowser.load(true); }
  if (name === 'friends') loadFriends();
}
document.querySelectorAll('.bottom-nav button').forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));

// Segmented controls (the app's pill toggles with a ✓ on the selected half)
function segmented(id, onChange) {
  const root = $(id);
  // Material SegmentedButton: the selected segment shows a ✓ in place of its icon
  root.querySelectorAll('button').forEach((b) => {
    const use = b.querySelector('use');
    if (use) b.dataset.icon = use.getAttribute('href');
  });
  const set = (v) => {
    root.querySelectorAll('button').forEach((b) => {
      const on = b.dataset.v === v;
      b.classList.toggle('on', on);
      b.querySelector('use')?.setAttribute('href', on ? '#i-check' : b.dataset.icon);
    });
  };
  set(root.querySelector('.on')?.dataset.v);
  root.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b || b.disabled || b.classList.contains('on')) return;
    set(b.dataset.v);
    onChange(b.dataset.v);
  });
  return { set, get: () => root.querySelector('.on')?.dataset.v };
}

// =====================================================================
// Image / model browsers (Recent captures, Sticker book, Studio › 3D)
// =====================================================================
const PAGE_SIZE = 24;
const badImages = new Set();

class Browser {
  constructor(rootId, opts) {
    this.root = $(rootId);
    this.opts = opts; // { kind: 'images'|'meshes', source, query(), empty(), pickable }
    this.items = [];
    this.page = 1;
    this.total = 0;
    this.picked = new Set();
    this.root.innerHTML = `
      <ul class="grid"></ul>
      <div class="browser-msg"></div>
      <button type="button" class="btn quiet block more" hidden>Load more</button>
      <div class="pick-bar" hidden>
        <span class="pick-count"></span>
        <button type="button" class="link pick-clear">Clear</button>
        <button type="button" class="btn primary pick-go">${icon('sparkle')} <span>Make 3D</span></button>
      </div>`;
    this.grid = this.root.querySelector('.grid');
    this.msg = this.root.querySelector('.browser-msg');
    this.more = this.root.querySelector('.more');
    this.more.onclick = () => { this.page++; this.load(); };
    this.root.querySelector('.pick-clear').onclick = () => { this.picked.clear(); this.render(); };
    this.root.querySelector('.pick-go').onclick = () => convertPicked(this);
  }

  async load(reset = false) {
    if (!mongoCfg?.configured) { this.msg.innerHTML = ''; this.grid.replaceChildren(); return; }
    const q = this.opts.query();
    if (q === null) return; // query() already showed a message (e.g. "pick who you are")
    if (reset) { this.page = 1; this.items = []; this.picked.clear(); }
    this.msg.innerHTML = '<p class="muted small">Loading…</p>';
    try {
      const params = new URLSearchParams({ ...q, page: this.page, limit: PAGE_SIZE });
      const url = this.opts.kind === 'meshes' ? `/api/mongo/meshes?${params}` : `/api/mongo/images?source=${this.opts.source}&${params}`;
      const data = await api(url);
      this.items.push(...data.items);
      this.total = data.total;
      this.msg.innerHTML = '';
      this.render();
    } catch (err) {
      this.msg.innerHTML = `<p class="error">Couldn't load: ${esc(err.message)}</p>`;
    }
  }

  taskFor(item) {
    return tasks.find((t) => t.mongo && t.mongo.source === this.opts.source && t.mongo.docId === item.docId);
  }

  render() {
    if (!this.items.length && !this.msg.innerHTML) {
      const [ic, title, body] = this.opts.empty();
      this.msg.innerHTML = emptyCard(ic, title, body);
    }
    this.grid.replaceChildren(...this.items.map((it) => (this.opts.kind === 'meshes' ? this.meshTile(it) : this.imageTile(it))));
    this.more.hidden = this.items.length >= this.total;
    const bar = this.root.querySelector('.pick-bar');
    bar.hidden = !this.picked.size;
    this.root.querySelector('.pick-count').textContent = `${this.picked.size} selected`;
    this.root.querySelector('.pick-go span').textContent = $('dummyMode').checked ? `Make 3D (dummy) · ${this.picked.size}` : `Make 3D · ${this.picked.size}`;
  }

  imageTile(item) {
    const li = document.createElement('li');
    const t = this.taskFor(item);
    const ready = t?.glb;
    const failed = t && ['FAILED', 'CANCELED'].includes(t.status);
    const busy = t && !ready && !failed;
    const dbMesh = !t && item.mesh && !item.mesh.dummy ? item.mesh : null;
    const realReady = (ready && !t.dummy) || dbMesh;
    li.className = ['tile', this.opts.source === 'stickers' ? 'sticker' : 'photo', this.picked.has(item.docId) && 'sel', badImages.has(item.docId) && 'bad'].filter(Boolean).join(' ');
    li.title = [item.title, item.date && new Date(item.date).toLocaleDateString()].filter(Boolean).join(' · ');
    li.innerHTML = `
      <div class="tile-img"><img src="${esc(item.image)}" alt="" loading="lazy" /></div>
      <div class="tile-cap">${item.starred ? icon('star', 'sm star') : ''}<span>${esc(item.title || (this.opts.source === 'stickers' ? 'Sticker' : 'Capture'))}</span></div>
      <div class="tile-actions"></div>`;
    li.querySelector('img').onerror = () => {
      badImages.add(item.docId);
      this.picked.delete(item.docId);
      li.classList.add('bad');
      li.title = 'Unsupported image format (Meshy needs JPEG, PNG or WebP)';
    };
    const actions = li.querySelector('.tile-actions');
    // Status badge
    const badge = (text, cls = '') => { const b = document.createElement('span'); b.className = `badge ${cls}`; b.textContent = text; li.append(b); };
    if (ready) badge(t.dummy ? 'Dummy 3D' : '3D ✓', 'ok');
    else if (failed) badge('Failed', 'fail');
    else if (busy) badge(`${t.progress || 0}%`);
    else if (dbMesh) badge('3D ✓', 'ok');
    // Actions: 2D sticker, + 3D model
    const act = (label, title, fn, cls = '') => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = `tile-btn ${cls}`;
      b.title = title;
      b.innerHTML = label;
      b.onclick = (e) => { e.stopPropagation(); fn(); };
      actions.append(b);
    };
    if (this.opts.source === 'captures' && !badImages.has(item.docId) && cutterCfg?.configured) {
      act(icon('cut', 'sm'), 'Cut stickers out of this photo (SAM 3)', () => openCutter({ docId: item.docId }));
    }
    if (!badImages.has(item.docId)) {
      act('2D', 'Add to the scene as a 2D sticker', () => addToScene({
        kind: 'sticker2d', name: item.title || 'Sticker', image: item.image,
        stickerId: this.opts.source === 'stickers' ? item.docId : null,
      }));
    }
    if (ready) act(`${icon('plus', 'sm')}3D`, 'Add the 3D model to the scene', () => addToScene(t), 'accent');
    else if (dbMesh) act(`${icon('plus', 'sm')}3D`, 'Add the 3D model to the scene', () => addToScene({ name: item.title || 'Model', glb: dbMesh.glb, meshId: dbMesh.id }), 'accent');

    li.onclick = () => {
      if (realReady) {
        activeId = ready ? t.id : null;
        showModel(ready ? t : { name: item.title || 'Model', glb: dbMesh.glb, meshId: dbMesh.id });
        return;
      }
      if (busy || badImages.has(item.docId) || !this.opts.pickable) return;
      this.picked.has(item.docId) ? this.picked.delete(item.docId) : this.picked.add(item.docId);
      this.render();
    };
    if (ready && t.dummy) li.ondblclick = () => showModel(t);
    return li;
  }

  meshTile(m) {
    const li = document.createElement('li');
    li.className = 'tile model';
    li.title = [m.name, m.source && `from ${m.source}`, m.date && new Date(m.date).toLocaleDateString()].filter(Boolean).join(' · ');
    li.innerHTML = `
      <div class="tile-img">${m.thumb ? `<img src="${esc(m.thumb)}" alt="" loading="lazy" />` : icon('cube', 'xl')}</div>
      <div class="tile-cap"><span>${esc(m.name)}</span></div>
      <div class="tile-actions"></div>`;
    const img = li.querySelector('img');
    if (img) img.onerror = () => { img.outerHTML = icon('cube', 'xl'); };
    const task = { name: m.name, glb: m.glb, dummy: m.dummy, meshId: m.id };
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'tile-btn accent';
    b.title = 'Add to the scene';
    b.innerHTML = `${icon('plus', 'sm')}Add`;
    b.onclick = (e) => { e.stopPropagation(); addToScene(task); };
    li.querySelector('.tile-actions').append(b);
    li.onclick = () => { activeId = null; showModel(task); };
    return li;
  }
}

// Recent captures (Scrap)
let capScope = 'mine';
const capBrowser = new Browser('capBrowser', {
  kind: 'images', source: 'captures', pickable: true,
  query: () => (capScope === 'mine' && me ? { owner: me } : {}),
  empty: () => ['scrap', 'No captures yet', capScope === 'mine' ? 'Scrapbook something with the glasses and it shows up here.' : 'Nobody has captured anything yet.'],
});
const capSeg = segmented('capScope', (v) => { capScope = v; capBrowser.load(true); });

// Sticker book (Book)
let bookScope = 'mine', bookStar = 'all';
const bookBrowser = new Browser('bookBrowser', {
  kind: 'images', source: 'stickers', pickable: true,
  query: () => {
    if (!me) return {};
    if (bookScope === 'friends') return { sharedTo: me };
    return { owner: me, ...(bookStar === 'starred' ? { starred: '1' } : {}) };
  },
  empty: () => (bookScope === 'friends'
    ? ['gift', 'Nothing from friends yet', 'Stickers your friends send you show up here.']
    : bookStar === 'starred'
      ? ['star', 'No starred scrapps', 'Tap All, then star the ones you want here (in the app).']
      : ['book', 'No stickers yet', 'Stickers cut from your captures show up here.']),
});
const bookStarSeg = segmented('bookStar', (v) => { bookStar = v; bookBrowser.load(true); });
const bookScopeSeg = segmented('bookScope', (v) => {
  bookScope = v;
  $('bookStar').hidden = v === 'friends'; // like the app: starring is for your own stickers
  bookBrowser.load(true);
});

// Studio: Collages | 3D
let studioView = 'collages';
segmented('studioSeg', (v) => {
  studioView = v;
  $('studioCollages').hidden = v !== 'collages';
  $('studio3d').hidden = v !== '3d';
  if (v === '3d') meshBrowser.load(true); else loadCollages();
});
let meshScope = 'mine';
const meshBrowser = new Browser('meshBrowser', {
  kind: 'meshes', pickable: false,
  query: () => (meshScope === 'mine' && me ? { owner: me } : {}),
  empty: () => ['cube', 'No 3D models yet', 'Models made here or in the app show up here.'],
});
const meshSeg = segmented('meshScope', (v) => { meshScope = v; meshBrowser.load(true); });

// Turn picked captures / stickers into 3D
async function convertPicked(browser) {
  const ids = [...browser.picked];
  if (!ids.length) return;
  const dummy = $('dummyMode').checked;
  if (!dummy && ids.length > 3 && !confirm(`Make ${ids.length} 3D models? Each one uses Meshy credits.`)) return;
  const options = readOptions();
  const failures = [];
  for (const docId of ids) {
    try {
      const data = await api('/api/generate', { method: 'POST', body: { mongo: { source: browser.opts.source, docId }, options } });
      tasks = tasks.filter((t) => !(t.mongo && t.mongo.source === browser.opts.source && t.mongo.docId === docId));
      tasks.unshift(data);
      browser.picked.delete(docId);
    } catch (err) { failures.push(err.message); }
  }
  renderTasks();
  browser.render();
  if (failures.length) flash(`${failures.length} couldn't start: ${[...new Set(failures)].join('; ')}`);
  else flash(`Started ${ids.length} — progress shows in Scrap › In progress`, 'ok');
}

// =====================================================================
// Scrap: upload a photo → 3D
// =====================================================================
let imageDataUri = null;

const dz = $('dropzone');
dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('drag'); });
dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
dz.addEventListener('drop', (e) => {
  e.preventDefault();
  dz.classList.remove('drag');
  if (e.dataTransfer.files[0]) pickFile(e.dataTransfer.files[0]);
});
dz.addEventListener('keydown', (e) => (e.key === 'Enter' || e.key === ' ') && $('fileInput').click());
$('fileInput').addEventListener('change', (e) => e.target.files[0] && pickFile(e.target.files[0]));

async function pickFile(file) {
  showError('');
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return showError('Please choose a JPEG, PNG or WebP image.');
  try {
    imageDataUri = await toDataUri(file);
  } catch (e) {
    return showError(`Couldn't read image: ${e.message}`);
  }
  $('preview').src = imageDataUri;
  $('preview').hidden = false;
  $('dropText').hidden = true;
  if (!$('name').value) $('name').value = file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ');
  $('generateBtn').disabled = false;
  $('cutUploadBtn').disabled = !cutterCfg?.configured;
}

// Reads the file, downscaling to MAX_SIDE if needed (always re-encodes oversized images as JPEG).
async function toDataUri(file) {
  const bitmap = await createImageBitmap(file);
  const { width: w, height: h } = bitmap;
  if (Math.max(w, h) <= MAX_SIDE && file.size < 15 * 1024 * 1024) {
    bitmap.close();
    return new Promise((res, rej) => {
      const r = new FileReader();
      r.onload = () => res(r.result);
      r.onerror = () => rej(r.error);
      r.readAsDataURL(file);
    });
  }
  const s = MAX_SIDE / Math.max(w, h);
  const c = document.createElement('canvas');
  c.width = Math.round(w * Math.min(s, 1));
  c.height = Math.round(h * Math.min(s, 1));
  c.getContext('2d').drawImage(bitmap, 0, 0, c.width, c.height);
  bitmap.close();
  return c.toDataURL('image/jpeg', 0.92);
}

$('target_polycount').addEventListener('input', (e) => ($('polyOut').textContent = Number(e.target.value).toLocaleString()));
$('should_texture').addEventListener('change', (e) => {
  $('enable_pbr').disabled = !e.target.checked;
  $('texture_prompt').disabled = !e.target.checked;
});
$('should_remesh').addEventListener('change', (e) => {
  $('target_polycount').disabled = !e.target.checked;
  $('topology').disabled = !e.target.checked;
});
$('settingsBtn').onclick = () => $('settingsDialog').showModal();

function readOptions() {
  const options = {
    ai_model: $('ai_model').value,
    should_remesh: $('should_remesh').checked,
    should_texture: $('should_texture').checked,
    enable_pbr: $('should_texture').checked && $('enable_pbr').checked,
    texture_prompt: $('texture_prompt').value.trim() || undefined,
    dummy: $('dummyMode').checked,
  };
  if (options.should_remesh) {
    options.target_polycount = Number($('target_polycount').value);
    options.topology = $('topology').value;
  }
  return options;
}

$('genForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!imageDataUri) return;
  showError('');
  const btn = $('generateBtn');
  btn.disabled = true;
  btn.querySelector('span').textContent = 'Uploading…';
  try {
    const data = await api('/api/generate', {
      method: 'POST',
      body: { image: imageDataUri, name: $('name').value.trim() || 'Untitled', options: readOptions() },
    });
    tasks.unshift(data);
    activeId = data.id;
    renderTasks();
    resetForm();
  } catch (err) {
    showError(err.message);
    btn.disabled = false;
  } finally {
    btn.querySelector('span').textContent = 'Make 3D model';
  }
});

function resetForm() {
  imageDataUri = null;
  $('fileInput').value = '';
  $('preview').hidden = true;
  $('dropText').hidden = false;
  $('name').value = '';
  $('generateBtn').disabled = true;
  $('cutUploadBtn').disabled = true;
}

function showError(msg) {
  $('formError').textContent = msg;
  $('formError').hidden = !msg;
}

// =====================================================================
// Sticker cutter: SAM 3 on the Scrapp backend (same model + die-cut as the app)
// =====================================================================
let cutterCfg = null;
const CUT_COLORS = ['#4e8288', '#7e8f62', '#c2564b', '#d9a441', '#694a47', '#5b8fb9', '#a35f8c', '#3f7f5f'];
const cut = { captureId: null, token: null, cands: [], picked: new Set(), busy: false };

function cutBusy(msg) {
  cut.busy = Boolean(msg);
  $('cutBusy').hidden = !msg;
  if (msg) $('cutBusy').querySelector('span').textContent = msg;
}
function cutMsg(text, kind = '') {
  $('cutMsg').hidden = !text;
  $('cutMsg').textContent = text || '';
  $('cutMsg').className = `small ${kind === 'error' ? 'error' : kind === 'ok' ? 'ok-text' : 'muted'}`;
}

function renderCut() {
  const svg = $('cutSvg');
  svg.innerHTML = cut.cands.map((c, n) => {
    const color = CUT_COLORS[n % CUT_COLORS.length];
    const on = cut.picked.has(c.index);
    const d = c.outline.map((poly) => `M${poly.map(([x, y]) => `${x},${y}`).join('L')}Z`).join(' ');
    return `<path data-i="${c.index}" d="${d}" fill="${color}" fill-opacity="${on ? 0.45 : 0.14}"
      stroke="${on ? '#fff0de' : color}" stroke-width="${on ? 3 : 2}" fill-rule="evenodd" />`;
  }).join('');
  $('cutList').replaceChildren(...cut.cands.map((c, n) => {
    const li = document.createElement('li');
    li.className = cut.picked.has(c.index) ? 'on' : '';
    li.innerHTML = `<span class="tick">${cut.picked.has(c.index) ? '✓' : ''}</span>
      <span class="sw" style="background:${CUT_COLORS[n % CUT_COLORS.length]}"></span>
      <span>Object ${n + 1}</span><span class="sc">${Math.round(c.area * 100)}% of photo</span>`;
    li.onclick = () => toggleCut(c.index);
    return li;
  }));
  const k = cut.picked.size;
  $('cutMake').disabled = !k || cut.busy;
  $('cutMake').querySelector('span').textContent = k ? `Make ${k} sticker${k === 1 ? '' : 's'}` : 'Pick objects to make stickers';
}

function toggleCut(i) {
  cut.picked.has(i) ? cut.picked.delete(i) : cut.picked.add(i);
  renderCut();
}

async function openCutter({ docId, image, name }) {
  Object.assign(cut, { captureId: null, token: null, cands: [], picked: new Set() });
  $('cutImg').removeAttribute('src');
  $('cutPrompt').value = '';
  $('cutTitle').value = name || '';
  $('cutDone').hidden = true;
  $('cutMade').replaceChildren();
  cutMsg('');
  renderCut();
  $('cutDialog').showModal();
  cutBusy(image ? 'Saving your photo as a capture…' : 'Opening photo…');
  try {
    const start = await api('/api/cut/start', { method: 'POST', body: { docId, image, name } });
    cut.captureId = start.captureId;
    if (!$('cutTitle').value) $('cutTitle').value = start.title || '';
    await new Promise((res, rej) => { $('cutImg').onload = res; $('cutImg').onerror = () => rej(new Error('Photo failed to load')); $('cutImg').src = start.image; });
    if (image) { capBrowser.load(true); resetForm(); }
    cutBusy('');
    await findObjects();
  } catch (err) {
    cutBusy('');
    cutMsg(err.message, 'error');
  }
}

async function findObjects() {
  if (!cut.captureId || cut.busy) return;
  const prompt = $('cutPrompt').value.trim();
  cutBusy(prompt ? `Looking for “${prompt}” with SAM 3…` : 'Finding objects with SAM 3… (the first run loads the model, which can take a minute)');
  cutMsg('');
  try {
    const r = await api('/api/cut/segment', { method: 'POST', body: { captureId: cut.captureId, prompt } });
    cut.token = r.token;
    cut.cands = r.candidates;
    cut.picked = new Set(r.candidates.slice(0, 1).map((c) => c.index)); // like the app: the best one is the hero
    if (!r.candidates.length) cutMsg(prompt ? `No “${prompt}” found. Try another word, or tap the object.` : 'Nothing obvious found. Tap an object to cut it out.');
  } catch (err) {
    cutMsg(err.message, 'error');
  } finally {
    cutBusy('');
    renderCut();
  }
}
$('cutFind').addEventListener('submit', (e) => { e.preventDefault(); findObjects(); });

// Tap: on an outline = pick/unpick; anywhere else = tap-to-cut there
$('cutFrame').addEventListener('click', async (e) => {
  if (cut.busy || !cut.captureId) return;
  const path = e.target.closest('path[data-i]');
  if (path) return toggleCut(Number(path.dataset.i));
  const r = $('cutImg').getBoundingClientRect();
  const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return;
  const tap = $('cutTap');
  Object.assign(tap.style, { left: `${x * 100}%`, top: `${y * 100}%` });
  tap.hidden = false;
  cutBusy('Cutting what you tapped…');
  try {
    const res = await api('/api/cut/point', { method: 'POST', body: { captureId: cut.captureId, x, y, token: cut.token } });
    cut.token = res.token;
    cut.cands.push(res.candidate);
    cut.picked.add(res.candidate.index);
    cutMsg('');
  } catch (err) {
    cutMsg(err.message, 'error');
  } finally {
    tap.hidden = true;
    cutBusy('');
    renderCut();
  }
});

$('cutMake').onclick = async () => {
  if (!cut.picked.size || !cut.token) return;
  cutBusy('Making stickers…');
  try {
    const r = await api('/api/cut/stickers', { method: 'POST', body: { token: cut.token, indices: [...cut.picked], title: $('cutTitle').value.trim() } });
    $('cutDone').hidden = false;
    for (const s of r.stickers) {
      const f = document.createElement('figure');
      f.innerHTML = `<img src="${esc(s.image)}" alt="" />`;
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'tile-btn';
      b.textContent = '2D';
      b.title = 'Add to the scene as a 2D sticker';
      b.onclick = () => addToScene({ kind: 'sticker2d', name: s.title || 'Sticker', image: s.image, stickerId: s.id });
      f.append(b);
      $('cutMade').append(f);
    }
    cut.picked.clear();
    cutMsg(`Made ${r.stickers.length} sticker${r.stickers.length === 1 ? '' : 's'}.`, 'ok');
    bookBrowser.load(true);
  } catch (err) {
    cutMsg(err.message, 'error');
  } finally {
    cutBusy('');
    renderCut();
  }
};
$('cutClose').onclick = () => $('cutDialog').close();
$('cutUploadBtn').onclick = () => imageDataUri && openCutter({ image: imageDataUri, name: $('name').value.trim() });

// =====================================================================
// Local generations: "In progress" (Scrap) and "Made here" (Studio › 3D)
// =====================================================================
function statusLabel(t) {
  if (t.glb) {
    const parts = [t.dummy ? 'Dummy ready' : 'Ready'];
    if (t.mongoSave?.meshId) parts.push('saved to MongoDB');
    else if (t.mongoSave?.error) return { text: `${parts[0]} · couldn't save to MongoDB`, cls: 'fail', retry: true };
    return { text: parts.join(' · '), cls: 'ok' };
  }
  if (t.status === 'FAILED') return { text: t.error || 'Failed', cls: 'fail' };
  if (t.status === 'CANCELED') return { text: 'Canceled', cls: 'fail' };
  if (t.status === 'DOWNLOADING') return { text: 'Saving model…', cls: '' };
  if (t.status === 'PENDING') return { text: t.queue ? `Queued (${t.queue} ahead)` : 'Queued…', cls: '' };
  return { text: `Growing… ${t.progress || 0}%`, cls: '' };
}

function taskRow(t) {
  const li = document.createElement('li');
  li.className = `row card${t.id === activeId ? ' active' : ''}`;
  const s = statusLabel(t);
  li.innerHTML = `
    <img class="row-thumb" src="${esc(t.thumbnail || t.input)}" alt="" loading="lazy" />
    <div class="row-main">
      <div class="row-title"></div>
      <div class="row-sub ${s.cls}"></div>
      ${DONE(t) ? '' : `<div class="bar"><i style="width:${t.progress || 0}%"></i></div>`}
    </div>
    <span class="row-actions">
      ${t.glb ? `<button class="icon-btn add" title="Add to scene">${icon('plus')}</button>` : ''}
      ${s.retry ? '<button class="icon-btn retry" title="Retry saving to MongoDB">↻</button>' : ''}
      <button class="icon-btn del" title="Remove from this list">×</button>
    </span>`;
  li.querySelector('.row-title').textContent = t.name;
  li.querySelector('.row-sub').textContent = s.text;
  if (s.retry) li.querySelector('.row-sub').title = t.mongoSave.error;
  li.querySelector('.add')?.addEventListener('click', (e) => { e.stopPropagation(); addToScene(t); });
  li.querySelector('.retry')?.addEventListener('click', async (e) => {
    e.stopPropagation();
    e.currentTarget.disabled = true;
    Object.assign(t, await fetch(`/api/tasks/${t.id}/save`, { method: 'POST' }).then((r) => r.json()));
    renderTasks();
  });
  li.onclick = () => {
    activeId = t.id;
    renderTasks();
    if (t.glb) showModel(t);
  };
  li.querySelector('.del').onclick = async (e) => {
    e.stopPropagation();
    if (!confirm(`Remove "${t.name}" from this list? (Anything saved to MongoDB stays there.)`)) return;
    await fetch(`/api/tasks/${t.id}`, { method: 'DELETE' });
    tasks = tasks.filter((x) => x.id !== t.id);
    for (const it of items.filter((i) => i.task.id === t.id)) removeItem(it);
    if (activeId === t.id) activeId = null;
    if (!items.length) showSample();
    renderTasks();
  };
  return li;
}

function renderTasks() {
  const pending = tasks.filter((t) => !DONE(t));
  $('progressWrap').hidden = !pending.length;
  $('progressList').replaceChildren(...pending.map(taskRow));
  $('taskList').replaceChildren(...tasks.filter(DONE).map(taskRow));
  $('emptyGallery').hidden = tasks.some(DONE);
}
const renderList = renderTasks; // used by the viewer code

async function poll() {
  const pending = tasks.filter((t) => !DONE(t));
  let finishedSaved = false;
  await Promise.all(pending.map(async (t) => {
    try {
      const res = await fetch(`/api/tasks/${t.id}`);
      if (!res.ok) return;
      const updated = await res.json();
      const wasReady = Boolean(t.glb);
      Object.assign(t, updated);
      if (!wasReady && t.glb && t.id === activeId) showOrAdd(t);
      if (!wasReady && t.glb && t.mongoSave?.meshId) finishedSaved = true;
    } catch { /* network blip — try again next tick */ }
  }));
  if (pending.length) {
    renderTasks();
    for (const b of [capBrowser, bookBrowser]) if (b.items.length) b.render();
    if (finishedSaved && tab === 'studio' && studioView === '3d') meshBrowser.load(true);
  }
  setTimeout(poll, POLL_MS);
}

// =====================================================================
// Studio › Collages
// =====================================================================
async function loadCollages() {
  const list = $('collageList');
  if (!mongoCfg?.configured) { list.replaceChildren(); return; }
  list.innerHTML = '<li class="muted small">Loading…</li>';
  try {
    const rows = await api(`/api/collages${me ? `?owner=${me}` : ''}`);
    const last = store.get('lastCollage', null);
    if (!rows.length) {
      list.innerHTML = `<li>${emptyCard('layers', 'No collages yet', 'Arrange stickers and 3D models in space, then save what is inside the box.')}</li>`;
      return;
    }
    list.replaceChildren(...rows.map((c) => {
      const li = document.createElement('li');
      li.className = `row card${last?.id === c.id ? ' active' : ''}`;
      li.innerHTML = `
        ${c.thumb ? `<img class="row-thumb" src="${esc(c.thumb)}" alt="" loading="lazy" />` : `<span class="row-thumb">${icon('layers')}</span>`}
        <div class="row-main">
          <div class="row-title">${esc(c.title)}</div>
          <div class="row-sub">${c.itemCount} item${c.itemCount === 1 ? '' : 's'} · ${new Date(c.updated).toLocaleDateString()}${c.via === 'web-app' ? ' · web' : ''}</div>
        </div>
        ${icon('chevron')}`;
      li.onclick = () => loadCollage(c.id);
      return li;
    }));
  } catch (err) {
    list.innerHTML = `<li class="error">Couldn't load collages: ${esc(err.message)}</li>`;
  }
}

async function loadCollage(id) {
  try {
    setLoading(true);
    const c = await api(`/api/collages/${id}`);
    clearScene();
    restoring = true;
    for (const it of c.scene.items) {
      const task = it.kind === 'sticker'
        ? { kind: 'sticker2d', name: it.title || 'Sticker', image: it.url, stickerId: it.ref_id }
        : { name: it.title || 'Model', glb: it.url, meshId: it.ref_id };
      await addToScene(task, { collage: it });
    }
    restoring = false;
    saveScene();
    fitCamera();
    if (head.mode !== 'off') captureBaseView();
    store.set('lastCollage', { id: c.id, title: c.title });
    loadCollages();
    flash(`Opened "${c.title}"${c.scene.items.length ? '' : ' (it has nothing that still exists in MongoDB)'}`, 'ok');
  } catch (err) {
    restoring = false;
    flash(`Couldn't open collage: ${err.message}`);
  } finally {
    setLoading(false);
  }
}

$('newCollageBtn').onclick = () => {
  clearScene();
  store.set('lastCollage', null);
  loadCollages();
  flash('Fresh scene. Add stickers from the Book (2D) or models from Studio › 3D.', 'ok');
};
$('saveCollageBtn').onclick = () => openCollageDialog();

// =====================================================================
// Friends: add by username, inbox, requests
// =====================================================================
async function loadFriends() {
  const needMe = (msg) => {
    $('inboxList').innerHTML = `<li>${emptyCard('person', 'Who are you?', msg)}</li>`;
    $('friendChips').replaceChildren();
    $('requestsWrap').hidden = true;
  };
  if (!mongoCfg?.configured) return needMe('Connect MongoDB to see friends.');
  if (!me) return needMe('Pick your Scrapp user at the top to see your inbox and friends.');
  try {
    const [fr, inbox] = await Promise.all([api(`/api/friends?me=${me}`), api(`/api/inbox?me=${me}`)]);
    // Inbox
    $('inboxList').replaceChildren(...(inbox.length ? inbox.map(inboxRow) : [Object.assign(document.createElement('li'), {
      innerHTML: emptyCard('mail', 'Nothing yet', 'When a friend sends you a sticker, model or collage it shows up here.'),
    })]));
    // Requests
    $('requestsWrap').hidden = !fr.incoming.length && !fr.outgoing.length;
    $('requestList').replaceChildren(
      ...fr.incoming.map((r) => {
        const li = document.createElement('li');
        li.className = 'row card';
        li.innerHTML = `<span class="row-thumb round">${icon('person')}</span>
          <div class="row-main"><div class="row-title">@${esc(r.from.username)}</div><div class="row-sub">wants to be friends</div></div>
          <button class="btn primary sm">Accept</button>`;
        li.querySelector('button').onclick = async () => {
          try { await api(`/api/friends/${r.request_id}/accept`, { method: 'POST', body: { me } }); loadFriends(); }
          catch (err) { flash(err.message); }
        };
        return li;
      }),
      ...fr.outgoing.map((u) => {
        const li = document.createElement('li');
        li.className = 'row card quiet';
        li.innerHTML = `<span class="row-thumb round">${icon('person')}</span>
          <div class="row-main"><div class="row-title">@${esc(u.username)}</div><div class="row-sub">request sent</div></div>`;
        return li;
      }),
    );
    // Friends
    $('friendChips').innerHTML = fr.friends.length
      ? fr.friends.map((u) => `<span class="pill">${icon('person', 'sm')} @${esc(u.username)}</span>`).join('')
      : '<p class="muted small">No friends yet. Add someone by username.</p>';
  } catch (err) {
    $('inboxList').innerHTML = `<li class="error">Couldn't load: ${esc(err.message)}</li>`;
  }
}

function inboxRow(s) {
  const li = document.createElement('li');
  li.className = 'row card';
  const what = { sticker: 'a sticker', mesh: 'a 3D model', collage: 'a collage' }[s.kind];
  const who = s.from ? s.from.username : 'Someone';
  li.innerHTML = `
    ${s.image ? `<img class="row-thumb ${s.kind === 'sticker' ? 'sticker' : ''}" src="${esc(s.image)}" alt="" loading="lazy" />` : `<span class="row-thumb">${icon(s.kind === 'collage' ? 'layers' : 'cube')}</span>`}
    <div class="row-main">
      <div class="row-title">${esc(who)} sent ${what}</div>
      ${s.message ? `<div class="row-quote">“${esc(s.message)}”</div>` : ''}
      <div class="row-sub">${s.kind === 'sticker' ? 'Place it in your scene' : s.kind === 'mesh' ? 'Add it to your scene' : 'Open it in the studio'}</div>
    </div>
    <button class="icon-btn" title="${s.kind === 'collage' ? 'Open' : 'Add to scene'}">${icon(s.kind === 'collage' ? 'chevron' : 'studio')}</button>`;
  const go = () => {
    if (s.kind === 'sticker') addToScene({ kind: 'sticker2d', name: s.title || 'Sticker', image: s.image, stickerId: s.itemId });
    else if (s.kind === 'mesh' && s.glb) addToScene({ name: s.title || 'Model', glb: s.glb, meshId: s.itemId });
    else if (s.kind === 'collage') loadCollage(s.itemId);
  };
  li.querySelector('button').onclick = (e) => { e.stopPropagation(); go(); };
  li.onclick = go;
  return li;
}

$('addFriendForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = $('friendName').value.trim();
  if (!username) return;
  const msg = $('friendMsg');
  try {
    if (!me) throw new Error('Pick your Scrapp user at the top first.');
    const r = await api('/api/friends/request', { method: 'POST', body: { me, username } });
    msg.textContent = r.status === 'accepted' ? `You and @${username.replace(/^@/, '')} are now friends.` : `Request sent to @${username.replace(/^@/, '')}.`;
    msg.className = 'small ok-text';
    $('friendName').value = '';
    loadFriends();
  } catch (err) {
    msg.textContent = err.message;
    msg.className = 'small error';
  }
  msg.hidden = false;
});

// =====================================================================
// Account: the studio uses your Scrapp login (same accounts as the phone app)
// =====================================================================
function showAccount(user) {
  $('whoami').textContent = `@${user.username}`;
  $('whoami').title = user.display_name || user.username;
}
$('signOut').onclick = async () => {
  try { await fetch('/api/auth/logout', { method: 'POST' }); } catch { /* going to the login page anyway */ }
  store.set('tab', 'scrap');
  location.href = '/login';
};

function slug(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'model';
}

// Default preview: the sample coffee mug (also what dummy mode returns)
const SAMPLE = { name: 'Sample: coffee mug', glb: '/sample/coffee-mug.glb', sample: true };
const showSample = () => { activeId = null; renderTasks(); showModel(SAMPLE); };

// boot
(async () => {
  const cfgRes = await fetch('/api/config');
  if (cfgRes.status === 401) { location.href = '/login'; return; }
  const cfg = await cfgRes.json();
  me = cfg.user.id;
  showAccount(cfg.user);
  const dummyBox = $('dummyMode');
  dummyBox.checked = cfg.dummy.forced || store.get('dummyMode', true);
  dummyBox.disabled = cfg.dummy.forced;
  if (cfg.dummy.forced) $('dummyHint').textContent = 'Dummy mode is forced on (MESHY_DUMMY=1): a sample mug comes back, nothing is spent.';
  const syncDummy = () => {
    $('keyWarning').hidden = cfg.hasKey || dummyBox.checked;
    dummyBox.closest('.pill').classList.toggle('on', dummyBox.checked);
    $('dummyHint').hidden = !dummyBox.checked;
    for (const b of [capBrowser, bookBrowser]) if (b.picked.size) b.render();
  };
  dummyBox.onchange = () => { store.set('dummyMode', dummyBox.checked); syncDummy(); };
  syncDummy();
  $('dbSaveHint').innerHTML = cfg.mongo.saveMeshes
    ? `${icon('check', 'sm')} Saves to MongoDB`
    : 'Not saving to MongoDB';
  mongoCfg = cfg.mongo;
  cutterCfg = { configured: Boolean(cfg.cutter?.configured && cfg.mongo.configured), api: cfg.cutter?.api };
  if (!cutterCfg.configured) $('cutUploadBtn').title = 'Sticker cutting is off: set SCRAPP_WEBAPP_KEY in .env (and WEBAPP_KEY in the backend)';
  $('mongoWarning').hidden = mongoCfg.configured;
  $('collageBtn').hidden = !mongoCfg.configured;
  $('saveCollageBtn').disabled = !mongoCfg.configured;
  tasks = await fetch('/api/tasks').then((r) => r.json());
  renderTasks();
  capScope = meshScope = bookScope = 'mine';
  showTab(tab);
  if (!(await restoreScene())) showSample(); // saved scene from last visit, else the sample mug
  poll();
})();

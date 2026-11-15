import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const $ = (id) => document.getElementById(id);
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
const darkBg = new THREE.Color(0x0e0f13);
const lightBg = new THREE.Color(0xe9ebf0);
scene.background = darkBg;
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
camera.position.set(2.6, 1.6, 2.6);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.autoRotate = true;
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
const grid = new THREE.GridHelper(6, 24, 0x2a2e38, 0x1c1f27);
scene.add(ground, grid);

const loader = new GLTFLoader();
const clock = new THREE.Clock();
let current = null; // { root, mixer }
let wireframe = false;

function resize() {
  const { clientWidth: w, clientHeight: h } = canvas.parentElement;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(canvas.parentElement);

renderer.setAnimationLoop(() => {
  const dt = clock.getDelta();
  current?.mixer?.update(dt);
  controls.update();
  renderer.render(scene, camera);
});

function disposeCurrent() {
  if (!current) return;
  scene.remove(current.root);
  current.root.traverse((o) => {
    if (!o.isMesh) return;
    o.geometry.dispose();
    for (const m of [].concat(o.material)) {
      for (const v of Object.values(m)) if (v?.isTexture) v.dispose();
      m.dispose();
    }
  });
  current = null;
}

function resetCamera() {
  camera.position.set(2.6, 1.6, 2.6);
  controls.target.set(0, 0.5, 0);
  controls.update();
}

async function showModel(task) {
  $('placeholder').hidden = true;
  $('loading').hidden = false;
  try {
    const gltf = await loader.loadAsync(task.glb);
    disposeCurrent();
    const root = gltf.scene;

    // Normalize: scale to ~1.6 units tall/wide, center on X/Z, sit on the ground.
    const box = new THREE.Box3().setFromObject(root);
    const size = box.getSize(new THREE.Vector3());
    const scale = 1.6 / Math.max(size.x, size.y, size.z);
    root.scale.setScalar(scale);
    box.setFromObject(root);
    const center = box.getCenter(new THREE.Vector3());
    root.position.sub(new THREE.Vector3(center.x, box.min.y, center.z));

    let tris = 0;
    root.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = true;
      o.receiveShadow = true;
      for (const m of [].concat(o.material)) m.wireframe = wireframe;
      const g = o.geometry;
      tris += (g.index ? g.index.count : g.attributes.position.count) / 3;
    });

    let mixer = null;
    if (gltf.animations?.length) {
      mixer = new THREE.AnimationMixer(root);
      mixer.clipAction(gltf.animations[0]).play();
    }
    scene.add(root);
    current = { root, mixer };
    resetCamera();
    controls.target.set(0, (box.max.y - box.min.y) / 2, 0);

    $('toolbar').hidden = false;
    $('modelTitle').textContent = task.name;
    $('downloadBtn').href = task.glb;
    $('downloadBtn').download = `${slug(task.name)}.glb`;
    $('stats').hidden = false;
    $('stats').textContent =
      `${Math.round(tris).toLocaleString()} triangles · ${(size.x).toFixed(2)} × ${(size.y).toFixed(2)} × ${(size.z).toFixed(2)} (orig. units)` +
      (gltf.animations?.length ? ` · ${gltf.animations.length} animation(s)` : '');
  } catch (e) {
    console.error(e);
    $('placeholder').hidden = false;
    $('placeholder').querySelector('p').textContent = `Couldn't load model: ${e.message}`;
  } finally {
    $('loading').hidden = true;
  }
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
      wireframe = !wireframe;
      btn.classList.toggle('on', wireframe);
      current?.root.traverse((o) => o.isMesh && [].concat(o.material).forEach((m) => (m.wireframe = wireframe)));
      break;
    case 'bg': {
      const light = scene.background === darkBg;
      scene.background = light ? lightBg : darkBg;
      grid.visible = !light;
      btn.classList.toggle('on', light);
      break;
    }
    case 'reset':
      resetCamera();
      if (current) controls.target.set(0, new THREE.Box3().setFromObject(current.root).getSize(new THREE.Vector3()).y / 2, 0);
      break;
    case 'snippet':
      openSnippet();
      break;
  }
});

function openSnippet() {
  const task = tasks.find((t) => t.id === activeId);
  if (!task) return;
  const file = `${slug(task.name)}.glb`;
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
// Upload + generation form
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

function readOptions() {
  const options = {
    ai_model: $('ai_model').value,
    should_remesh: $('should_remesh').checked,
    should_texture: $('should_texture').checked,
    enable_pbr: $('should_texture').checked && $('enable_pbr').checked,
    texture_prompt: $('texture_prompt').value.trim() || undefined,
  };
  if (options.should_remesh) {
    options.target_polycount = Number($('target_polycount').value);
    options.topology = $('topology').value;
  }
  return options;
}

$('genForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (activeTab === 'mongo') return convertSelected();
  if (!imageDataUri) return;
  showError('');
  const btn = $('generateBtn');
  btn.disabled = true;
  btn.textContent = 'Uploading…';
  const options = readOptions();

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: imageDataUri, name: $('name').value.trim() || 'Untitled', options }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    tasks.unshift(data);
    activeId = data.id;
    renderList();
    resetForm();
  } catch (err) {
    showError(err.message);
    btn.disabled = false;
  } finally {
    btn.textContent = 'Generate 3D model';
  }
});

function resetForm() {
  imageDataUri = null;
  $('fileInput').value = '';
  $('preview').hidden = true;
  $('dropText').hidden = false;
  $('name').value = '';
  $('texture_prompt').value = '';
  $('generateBtn').disabled = true;
}

function showError(msg) {
  $('formError').textContent = msg;
  $('formError').hidden = !msg;
}

// =====================================================================
// MongoDB image source
// =====================================================================
let activeTab = 'upload';
let mongoCfg = null;
let mongoItems = [];
let mongoPage = 1;
let mongoTotal = 0;
const selected = new Set(); // docIds
const badImages = new Set(); // docIds the browser couldn't decode
const PAGE_SIZE = 24;

document.querySelectorAll('.tab').forEach((tab) => {
  tab.onclick = () => {
    activeTab = tab.dataset.tab;
    document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t === tab));
    $('panel-upload').hidden = activeTab !== 'upload';
    $('panel-mongo').hidden = activeTab !== 'mongo';
    showError('');
    if (activeTab === 'mongo' && !mongoItems.length) loadMongo(true);
    updateGenerateButton();
  };
});

function updateGenerateButton() {
  const btn = $('generateBtn');
  if (activeTab === 'mongo') {
    btn.textContent = selected.size ? `Convert ${selected.size} image${selected.size > 1 ? 's' : ''}` : 'Select images to convert';
    btn.disabled = selected.size === 0;
  } else {
    btn.textContent = 'Generate 3D model';
    btn.disabled = !imageDataUri;
  }
}

// Live conversion state comes from the local task list (so polling updates badges too)
function mongoTaskFor(item) {
  const source = $('mongoSource').value;
  return tasks.find((t) => t.mongo && t.mongo.source === source && t.mongo.docId === item.docId);
}

async function loadMongo(reset = false) {
  if (!mongoCfg?.configured) return;
  $('mongoError').hidden = true;
  if (reset) { mongoPage = 1; mongoItems = []; selected.clear(); }
  $('mongoCount').textContent = 'Loading…';
  try {
    const q = new URLSearchParams({ source: $('mongoSource').value, page: mongoPage, limit: PAGE_SIZE });
    const res = await fetch(`/api/mongo/images?${q}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    mongoItems.push(...data.items);
    mongoTotal = data.total;
    renderGrid();
  } catch (err) {
    $('mongoError').textContent = `Couldn't load images: ${err.message}`;
    $('mongoError').hidden = false;
    $('mongoCount').textContent = '';
  }
  updateGenerateButton();
}

function renderGrid() {
  $('mongoGrid').replaceChildren(...mongoItems.map((item) => {
    const li = document.createElement('li');
    const t = mongoTaskFor(item);
    const ready = t?.glb;
    const failed = t && ['FAILED', 'CANCELED'].includes(t.status);
    const busy = t && !ready && !failed;
    li.className = [selected.has(item.docId) && 'sel', (ready || busy) && 'done'].filter(Boolean).join(' ');
    const date = item.date ? new Date(item.date).toLocaleDateString() : '';
    li.title = [item.title, date].filter(Boolean).join(' · ') || item.docId;
    li.innerHTML = `<img src="${item.image}" alt="" loading="lazy" />`;
    if (badImages.has(item.docId)) li.classList.add('bad');
    li.querySelector('img').onerror = () => {
      // Browser can't display it (e.g. HEIC) — Meshy won't accept it either
      badImages.add(item.docId);
      selected.delete(item.docId);
      li.classList.add('bad');
      li.classList.remove('sel');
      li.title = 'Unsupported image format (Meshy needs JPEG, PNG or WebP)';
      updateGenerateButton();
    };
    if (t) {
      const b = document.createElement('span');
      b.className = `badge ${ready ? 'ok' : failed ? 'fail' : ''}`;
      b.textContent = ready ? '3D ✓' : failed ? 'Failed' : `${t.progress || 0}%`;
      li.append(b);
    }
    li.onclick = () => {
      if (ready) { activeId = t.id; renderList(); showModel(t); return; }
      if (busy || badImages.has(item.docId)) return;
      selected.has(item.docId) ? selected.delete(item.docId) : selected.add(item.docId);
      renderGrid();
      updateGenerateButton();
    };
    return li;
  }));
  const done = mongoItems.filter((i) => mongoTaskFor(i)?.glb).length;
  $('mongoCount').textContent = `${mongoItems.length} of ${mongoTotal} shown · ${done} converted`;
  $('mongoMore').hidden = mongoItems.length >= mongoTotal;
}

$('mongoSource').onchange = () => loadMongo(true);
$('mongoRefresh').onclick = () => loadMongo(true);
$('mongoMore').onclick = () => { mongoPage++; loadMongo(); };
$('selectNone').onclick = () => { selected.clear(); renderGrid(); updateGenerateButton(); };
$('selectNew').onclick = () => {
  for (const i of mongoItems) {
    const t = mongoTaskFor(i);
    if (badImages.has(i.docId)) continue;
    if (!t || ['FAILED', 'CANCELED'].includes(t.status)) selected.add(i.docId);
  }
  renderGrid();
  updateGenerateButton();
};

async function convertSelected() {
  const ids = [...selected];
  if (!ids.length) return;
  if (ids.length > 3 && !confirm(`Convert ${ids.length} images? Each one uses Meshy credits.`)) return;
  showError('');
  const btn = $('generateBtn');
  btn.disabled = true;
  const options = readOptions();
  const source = $('mongoSource').value;
  const failures = [];
  for (const [n, docId] of ids.entries()) {
    btn.textContent = `Starting ${n + 1} of ${ids.length}…`;
    try {
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mongo: { source, docId }, options }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
      tasks = tasks.filter((t) => !(t.mongo && t.mongo.source === source && t.mongo.docId === docId));
      tasks.unshift(data);
      selected.delete(docId);
      renderList();
      renderGrid();
    } catch (err) {
      failures.push(err.message);
    }
  }
  if (failures.length) showError(`${failures.length} failed: ${[...new Set(failures)].join('; ')}`);
  updateGenerateButton();
}

// =====================================================================
// Gallery + polling
// =====================================================================
let tasks = [];
let activeId = null;
const DONE = (t) => t.glb || t.status === 'FAILED' || t.status === 'CANCELED';

function statusLabel(t) {
  if (t.glb) return { text: 'Ready', cls: 'ok' };
  if (t.status === 'FAILED') return { text: t.error || 'Failed', cls: 'fail' };
  if (t.status === 'CANCELED') return { text: 'Canceled', cls: 'fail' };
  if (t.status === 'DOWNLOADING') return { text: 'Saving model…', cls: '' };
  if (t.status === 'PENDING') return { text: t.queue ? `Queued (${t.queue} ahead)` : 'Queued…', cls: '' };
  return { text: `Generating… ${t.progress || 0}%`, cls: '' };
}

function renderList() {
  const ul = $('taskList');
  ul.replaceChildren(...tasks.map((t) => {
    const li = document.createElement('li');
    li.className = `task${t.id === activeId ? ' active' : ''}`;
    const s = statusLabel(t);
    li.innerHTML = `
      <img src="${t.thumbnail || t.input}" alt="" loading="lazy" />
      <div>
        <div class="name"></div>
        <div class="status ${s.cls}"></div>
        ${DONE(t) ? '' : `<div class="bar"><i style="width:${t.progress || 0}%"></i></div>`}
      </div>
      <button class="del" title="Remove from gallery">×</button>`;
    li.querySelector('.name').textContent = t.name;
    li.querySelector('.status').textContent = s.text;
    li.onclick = () => {
      activeId = t.id;
      renderList();
      if (t.glb) showModel(t);
    };
    li.querySelector('.del').onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`Remove "${t.name}" from your gallery?`)) return;
      await fetch(`/api/tasks/${t.id}`, { method: 'DELETE' });
      tasks = tasks.filter((x) => x.id !== t.id);
      if (activeId === t.id) {
        activeId = null;
        disposeCurrent();
        $('toolbar').hidden = $('stats').hidden = true;
        $('placeholder').hidden = false;
      }
      renderList();
    };
    return li;
  }));
  $('emptyGallery').hidden = tasks.length > 0;
}

async function poll() {
  const pending = tasks.filter((t) => !DONE(t));
  await Promise.all(pending.map(async (t) => {
    try {
      const res = await fetch(`/api/tasks/${t.id}`);
      if (!res.ok) return;
      const updated = await res.json();
      const wasReady = Boolean(t.glb);
      Object.assign(t, updated);
      if (!wasReady && t.glb && t.id === activeId) showModel(t);
    } catch { /* network blip — try again next tick */ }
  }));
  if (pending.length) {
    renderList();
    if (activeTab === 'mongo') renderGrid();
  }
  setTimeout(poll, POLL_MS);
}

function slug(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'model';
}

// boot
(async () => {
  const cfg = await fetch('/api/config').then((r) => r.json());
  $('keyWarning').hidden = cfg.hasKey;
  mongoCfg = cfg.mongo;
  $('mongoWarning').hidden = mongoCfg.configured;
  $('mongoSource').replaceChildren(...mongoCfg.sources.map((s) => new Option(s.label, s.id)));
  $('mongoSource').disabled = $('mongoRefresh').disabled = !mongoCfg.configured;
  tasks = await fetch('/api/tasks').then((r) => r.json());
  renderList();
  const firstReady = tasks.find((t) => t.glb);
  if (firstReady) {
    activeId = firstReady.id;
    renderList();
    showModel(firstReady);
  }
  poll();
})();

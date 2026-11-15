// Meshy 3D Studio — tiny Express backend.
// Keeps your Meshy API key off the browser, proxies Image-to-3D tasks,
// downloads finished GLBs locally, and saves them to the Scrapp MongoDB
// (GridFS "media" + a "meshes" doc, same shape the Scrapp backend writes).

import express from 'express';
import { MongoClient, GridFSBucket, ObjectId } from 'mongodb';
import fs from 'node:fs/promises';
import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { randomUUID, createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT) || 3000;
const API_KEY = process.env.MESHY_API_KEY;
const MESHY_BASE = (process.env.MESHY_BASE_URL || 'https://api.meshy.ai').replace(/\/$/, '');
const flag = (v, dflt) => (v === undefined || v === '' ? dflt : /^(1|true|yes|on)$/i.test(v));

// Dummy mode: skip Meshy entirely and return a bundled sample model (no credits spent).
const DUMMY_FORCED = flag(process.env.MESHY_DUMMY, false);
const DUMMY_GLB = path.join(__dirname, 'assets', 'dummy.glb');
const DUMMY_DURATION_MS = 8000;

const DATA_DIR = path.join(__dirname, 'data');
const MODELS_DIR = path.join(DATA_DIR, 'models');
const INPUTS_DIR = path.join(DATA_DIR, 'inputs');
const DB_FILE = path.join(DATA_DIR, 'tasks.json');
for (const d of [DATA_DIR, MODELS_DIR, INPUTS_DIR]) if (!existsSync(d)) mkdirSync(d, { recursive: true });

// Scrapp backend (Python, GPU): sticker cutting uses its SAM 3 model through the /webapp bridge
const SCRAPP_API_URL = (process.env.SCRAPP_API_URL || 'http://localhost:8000').replace(/\/$/, '');
const SCRAPP_WEBAPP_KEY = process.env.SCRAPP_WEBAPP_KEY || '';
const MESHY_DAILY_CAP = Number(process.env.STUDIO_MESHY_DAILY_CAP ?? 10); // real (credit-spending) generations per user per day

// ---------- tiny JSON "database" (local gallery) ----------
let db = existsSync(DB_FILE) ? JSON.parse(await fs.readFile(DB_FILE, 'utf8')) : {};
for (const t of Object.values(db)) t.owner ||= t.actingAs || null; // tasks from before logins: ownerless ones stay hidden
let saveChain = Promise.resolve();
const saveDb = () => (saveChain = saveChain.then(() => fs.writeFile(DB_FILE, JSON.stringify(db, null, 2))));

const httpError = (status, message) => Object.assign(new Error(message), { status });

async function scrapp(pathname, body) {
  if (!SCRAPP_WEBAPP_KEY) throw httpError(503, 'Sticker cutting is off. Set SCRAPP_WEBAPP_KEY (and WEBAPP_KEY in the backend) and restart.');
  let res;
  try {
    res = await fetch(`${SCRAPP_API_URL}${pathname}`, {
      method: body ? 'POST' : 'GET',
      headers: { 'X-Webapp-Key': SCRAPP_WEBAPP_KEY, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(180_000), // first SAM 3 call loads the model
    });
  } catch (e) {
    throw httpError(502, `Can't reach the Scrapp backend at ${SCRAPP_API_URL} (${e.cause?.code || e.name}). Is it running?`);
  }
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text.slice(0, 200) }; }
  if (!res.ok) {
    const d = data.detail;
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map((x) => x.msg).join('; ') : `Backend error (${res.status})`;
    throw httpError(res.status === 404 && /Not Found/i.test(msg) ? 501 : res.status,
      res.status === 404 && /Not Found/i.test(msg) ? 'The backend has no /webapp routes yet. Pull the latest backend and restart it.' : msg);
  }
  return data;
}

// ---------- Meshy helpers ----------
async function meshy(pathname, init = {}) {
  if (!API_KEY) throw httpError(500, 'MESHY_API_KEY is not set. Add it to .env and restart, or use the dummy model.');
  const res = await fetch(`${MESHY_BASE}${pathname}`, {
    ...init,
    headers: { Authorization: `Bearer ${API_KEY}`, 'Content-Type': 'application/json', ...(init.headers || {}) },
  });
  const text = await res.text();
  let body;
  try { body = text ? JSON.parse(text) : {}; } catch { body = { message: text }; }
  if (!res.ok) throw httpError(res.status, body.message || `Meshy API error (${res.status})`);
  return body;
}

async function fetchBytes(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  return Buffer.from(await res.arrayBuffer());
}

// Allowed options forwarded to Meshy (whitelist so the client can't send arbitrary fields).
const OPTION_KEYS = [
  'ai_model', 'model_type', 'geometry_resolution', 'should_texture', 'enable_pbr',
  'texture_resolution', 'texture_prompt', 'should_remesh', 'topology', 'target_polycount',
  'pose_mode', 'image_enhancement', 'remove_lighting', 'auto_size', 'origin_at',
];

const DATA_URI_RE = /^data:image\/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=]+)$/;
const FAILED = (s) => s === 'FAILED' || s === 'CANCELED';

// Meshy accepts JPEG / PNG / WebP — detect from the bytes, not the stored metadata.
function sniffImageType(buf) {
  if (buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'jpeg';
  if (buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return 'png';
  if (buf.toString('ascii', 0, 4) === 'RIFF' && buf.toString('ascii', 8, 12) === 'WEBP') return 'webp';
  return null;
}

// ---------- MongoDB (Scrapp schema by default) ----------
const MONGO_URI = process.env.MONGO_URI;
const MONGO_DB = process.env.MONGO_DB || 'scrapp';
const MONGO_BUCKET = process.env.MONGO_BUCKET || 'media';
const MONGO_SAVE_MESHES = flag(process.env.MONGO_SAVE_MESHES, true);
const MONGO_SAVE_DUMMIES = flag(process.env.MONGO_SAVE_DUMMIES, false);

// meshField: field on a "meshes" doc that points back at this source's doc (Scrapp uses sticker_id).
const DEFAULT_SOURCES = {
  captures: {
    label: 'Captures (original photos)',
    collection: 'captures',
    fileField: 'original_file_id',
    titleFields: ['place_name', 'transcript', 'prompt'],
    dateField: 'captured_at',
    meshSource: 'capture',
    meshField: 'capture_id',
  },
  stickers: {
    label: 'Stickers (cut-out objects)',
    collection: 'stickers',
    fileField: 'image_file_id',
    titleFields: ['title', 'place_name'],
    dateField: 'created_at',
    meshSource: 'sticker',
    meshField: 'sticker_id',
  },
};
let SOURCES = DEFAULT_SOURCES;
if (process.env.MONGO_SOURCES_JSON) {
  try { SOURCES = JSON.parse(process.env.MONGO_SOURCES_JSON); }
  catch (e) { console.error('Invalid MONGO_SOURCES_JSON, using defaults:', e.message); }
}

let mongoPromise = null;
function mongo() {
  if (!MONGO_URI) throw httpError(503, 'MONGO_URI is not set. Add it to .env and restart.');
  if (!mongoPromise) {
    mongoPromise = new MongoClient(MONGO_URI, { serverSelectionTimeoutMS: 5000 }).connect()
      .then((client) => {
        const mdb = client.db(MONGO_DB);
        return { mdb, bucket: new GridFSBucket(mdb, { bucketName: MONGO_BUCKET }) };
      })
      .catch((e) => { mongoPromise = null; e.status = 503; throw e; });
  }
  return mongoPromise;
}

function getSource(name) {
  const src = SOURCES[name];
  if (!src) throw httpError(400, `Unknown source "${name}"`);
  return src;
}

function toObjectId(id) {
  if (!ObjectId.isValid(id)) throw httpError(400, 'Invalid id');
  return new ObjectId(id);
}

async function readGridFile(bucket, fileId) {
  const chunks = [];
  for await (const c of bucket.openDownloadStream(fileId)) chunks.push(c);
  return Buffer.concat(chunks);
}

// Same layout as the Scrapp backend's storage.put_bytes()
function putGridFile(bucket, bytes, filename, contentType, ownerId, kind) {
  return new Promise((resolve, reject) => {
    const up = bucket.openUploadStream(filename, { metadata: { content_type: contentType, owner_id: ownerId, kind } });
    up.on('error', reject).on('finish', () => resolve(up.id));
    up.end(bytes);
  });
}

const mongoKey = (source, docId) => `${source}:${docId}`;
// Latest local task per Mongo image. Real conversions win over dummy ones.
function conversionsIndex(owner) {
  const map = new Map();
  for (const t of Object.values(db)) {
    if (!t.mongo || t.owner !== owner) continue;
    const key = mongoKey(t.mongo.source, t.mongo.docId);
    const cur = map.get(key);
    const better = !cur || (cur.dummy && !t.dummy) || (cur.dummy === t.dummy && t.createdAt > cur.createdAt);
    if (better) map.set(key, t);
  }
  return map;
}

// Loads a Mongo image doc and returns { bytes, type, title, ref }
async function loadMongoImage(sourceName, docId, ownerId) {
  const src = getSource(sourceName);
  const { mdb, bucket } = await mongo();
  const doc = await mdb.collection(src.collection).findOne({ _id: toObjectId(docId), owner_id: new ObjectId(ownerId) });
  if (!doc) throw httpError(404, 'Image document not found in MongoDB');
  const fileId = doc[src.fileField];
  if (!fileId) throw httpError(422, `Document has no "${src.fileField}"`);
  const bytes = await readGridFile(bucket, fileId);
  const type = sniffImageType(bytes);
  if (!type) throw httpError(422, 'Stored file is not a JPEG, PNG or WebP image');
  const title = src.titleFields.map((f) => doc[f]).find((v) => typeof v === 'string' && v.trim());
  return {
    bytes, type, title,
    ref: {
      source: sourceName, docId: String(doc._id), fileId: String(fileId),
      ownerId: doc.owner_id ? String(doc.owner_id) : null,
    },
  };
}

// Existing real (non-dummy, non-failed) Scrapp mesh for a source doc, if any.
async function findScrappMesh(sourceName, docId) {
  const src = getSource(sourceName);
  if (!src.meshField || !MONGO_URI) return null;
  const { mdb } = await mongo();
  return mdb.collection('meshes').findOne(
    { [src.meshField]: toObjectId(docId), status: { $nin: ['FAILED', 'CANCELED'] }, dummy: { $ne: true } },
    { sort: { created_at: -1 } },
  );
}

// Save a finished model into MongoDB: GLB + thumbnail into GridFS, plus a "meshes" document.
async function saveMeshToMongo(record) {
  if (record.mongoSave?.meshId) return record.mongoSave;
  if (!MONGO_URI) return (record.mongoSave = { skipped: 'MongoDB not configured' });
  if (!MONGO_SAVE_MESHES) return (record.mongoSave = { skipped: 'Saving disabled (MONGO_SAVE_MESHES=0)' });
  if (record.dummy && !MONGO_SAVE_DUMMIES) return (record.mongoSave = { skipped: 'Dummy model (set MONGO_SAVE_DUMMIES=1 to save)' });

  const { mdb, bucket } = await mongo();
  const ownerRaw = record.owner; // always the signed-in user who started the job
  const ownerId = ownerRaw && ObjectId.isValid(ownerRaw) ? new ObjectId(ownerRaw) : null;

  const glbBytes = await fs.readFile(path.join(DATA_DIR, record.glb.replace(/^\/+/, '')));
  const glbFileId = await putGridFile(bucket, glbBytes, 'model.glb', 'model/gltf-binary', ownerId, 'mesh');

  let thumbFileId = null;
  const thumbPath = record.thumbnail || record.input;
  if (thumbPath) {
    try {
      const thumb = await fs.readFile(path.join(DATA_DIR, thumbPath.replace(/^\/+/, '')));
      const t = sniffImageType(thumb) || 'png';
      thumbFileId = await putGridFile(bucket, thumb, `thumb.${t === 'jpeg' ? 'jpg' : t}`, `image/${t}`, ownerId, 'mesh_thumb');
    } catch (e) { console.warn('thumbnail save failed:', e.message); }
  }

  const src = record.mongo ? SOURCES[record.mongo.source] : null;
  const doc = {
    owner_id: ownerId,
    source: src?.meshSource || (record.mongo ? record.mongo.source : 'upload'),
    ...(src?.meshField ? { [src.meshField]: new ObjectId(record.mongo.docId) } : {}),
    prompt: record.name,
    meshy_task_id: record.dummy ? null : record.id,
    stage: 'image',
    status: 'SUCCEEDED',
    progress: 100,
    glb_file_id: glbFileId,
    ...(thumbFileId ? { thumb_file_id: thumbFileId } : {}),
    created_at: new Date(record.createdAt),
    created_via: 'web-app',
    ...(record.dummy ? { dummy: true } : {}),
  };
  const { insertedId } = await mdb.collection('meshes').insertOne(doc);
  record.mongoSave = {
    meshId: String(insertedId), glbFileId: String(glbFileId),
    thumbFileId: thumbFileId ? String(thumbFileId) : null, savedAt: Date.now(),
  };
  return record.mongoSave;
}

// ---------- finishing a task ----------
const finalizing = new Map(); // taskId -> Promise (avoid double downloads / double saves)

function finalize(record, task) {
  if (finalizing.has(record.id)) return finalizing.get(record.id);
  const job = (async () => {
    const glbFile = path.join(MODELS_DIR, `${record.id}.glb`);
    if (record.dummy) {
      await fs.copyFile(DUMMY_GLB, glbFile);
    } else {
      const glbUrl = task.model_urls?.glb;
      if (!glbUrl) throw new Error('Task succeeded but no GLB was returned.');
      await fs.writeFile(glbFile, await fetchBytes(glbUrl));
      if (task.thumbnail_url) {
        try {
          await fs.writeFile(path.join(MODELS_DIR, `${record.id}.png`), await fetchBytes(task.thumbnail_url));
          record.thumbnail = `/models/${record.id}.png`;
        } catch { /* thumbnail is optional */ }
      }
      record.credits = task.consumed_credits ?? null;
    }
    record.glb = `/models/${record.id}.glb`;
    record.status = 'SUCCEEDED';
    record.progress = 100;
    record.finishedAt = Date.now();
    try { await saveMeshToMongo(record); }
    catch (e) {
      console.error('Saving to MongoDB failed:', e);
      record.mongoSave = { error: e.message };
    }
    await saveDb();
  })().finally(() => finalizing.delete(record.id));
  finalizing.set(record.id, job);
  return job;
}

// ---------- app ----------
const app = express();

// ---------- accounts: the same Scrapp accounts (and JWT) as the phone app ----------
// Login is proxied to the Scrapp API (/auth/login). The JWT lives in an HttpOnly cookie; every request is checked against the
// API (/auth/me, cached for a minute) and the user it names is the ONLY identity used for data access: ids sent by the browser
// (owner, me, actingAs, sharedTo) are ignored. There is no shared password any more.
const COOKIE = 'scrapp_studio';
const SESSION_DAYS = 14;
const sessionCache = new Map(); // token -> { user, until }
const revoked = new Set();      // tokens signed out here: a copied cookie stops working too (JWTs are otherwise stateless)
const parseCookies = (h = '') => Object.fromEntries(h.split(/;\s*/).filter(Boolean).map((c) => { const i = c.indexOf('='); return [c.slice(0, i), decodeURIComponent(c.slice(i + 1))]; }));

async function apiAuth(pathname, init) {
  let res;
  for (let attempt = 1; ; attempt++) {  // one retry: a pooled keep-alive socket can be reset between calls
    try { res = await fetch(`${SCRAPP_API_URL}${pathname}`, { ...init, signal: AbortSignal.timeout(15_000) }); break; }
    catch (e) { if (attempt >= 2) throw httpError(502, "Can't reach the Scrapp server. Is it running?"); }
  }
  const text = await res.text();
  let data = {}; try { data = text ? JSON.parse(text) : {}; } catch { /* non-JSON error page */ }
  return { ok: res.ok, status: res.status, data };
}

async function userFromToken(token) {
  if (!token || revoked.has(token)) return null;
  const hit = sessionCache.get(token);
  if (hit && hit.until > Date.now()) return hit.user;
  const r = await apiAuth('/auth/me', { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok || !r.data?.id) { sessionCache.delete(token); return null; }
  const user = { id: String(r.data.id), username: r.data.username, display_name: r.data.display_name || r.data.username };
  sessionCache.set(token, { user, until: Date.now() + 60_000 });
  if (sessionCache.size > 500) for (const [k, v] of sessionCache) if (v.until < Date.now()) sessionCache.delete(k);
  return user;
}

// Sliding-window limiter (per IP) for sign-in attempts
const loginHits = new Map();
function loginThrottled(ip) {
  const now = Date.now(), q = (loginHits.get(ip) || []).filter((t) => now - t < 10 * 60_000);
  if (q.length >= 15) { loginHits.set(ip, q); return Math.ceil((10 * 60_000 - (now - q[0])) / 1000); }
  q.push(now); loginHits.set(ip, q);
  if (loginHits.size > 2000) for (const [k, v] of loginHits) if (!v.length || now - v.at(-1) > 600_000) loginHits.delete(k);
  return 0;
}
const clientIp = (req) => req.headers['cf-connecting-ip'] || req.socket.remoteAddress || 'unknown';
const isHttps = (req) => req.headers['x-forwarded-proto'] === 'https' || Boolean(req.headers['cf-connecting-ip']);

app.use(express.json({ limit: '30mb' }));

// Block cross-site form posts: state-changing requests must come from this site (or have no Origin, e.g. curl)
app.use((req, res, next) => {
  const o = req.headers.origin;
  if (req.method !== 'GET' && req.method !== 'HEAD' && o) {
    try { if (new URL(o).host !== req.headers.host) return res.status(403).json({ error: 'Cross-site request blocked' }); }
    catch { return res.status(403).json({ error: 'Bad origin' }); }
  }
  next();
});

app.get('/healthz', (_req, res) => res.json({ ok: true }));
app.get('/login', (req, res) => res.set('Cache-Control', 'no-store').sendFile(path.join(__dirname, 'public', 'login.html')));

app.post('/api/auth/login', async (req, res, next) => {
  try {
    const wait = loginThrottled(clientIp(req));
    if (wait) return res.status(429).set('Retry-After', String(wait)).json({ error: `Too many sign-in attempts. Try again in ${Math.ceil(wait / 60)} min.` });
    const who = String(req.body?.username || req.body?.username_or_email || '').trim();
    const password = String(req.body?.password || '');
    if (!who || !password) throw httpError(400, 'Enter your username (or email) and password.');
    const r = await apiAuth('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'cf-connecting-ip': clientIp(req) }, body: JSON.stringify({ username_or_email: who, password }) });
    if (r.status === 401 || r.status === 400 || r.status === 404) throw httpError(401, 'Wrong username or password.');
    if (r.status === 429) throw httpError(429, r.data?.detail || 'Too many attempts. Try again in a few minutes.');
    if (!r.ok || !r.data?.token) throw httpError(502, 'Sign-in is unavailable right now.');
    res.append('Set-Cookie', `${COOKIE}=${encodeURIComponent(r.data.token)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${SESSION_DAYS * 86400}${isHttps(req) ? '; Secure' : ''}`);
    const user = { id: String(r.data.user.id), username: r.data.user.username, display_name: r.data.user.display_name || r.data.user.username };
    sessionCache.set(r.data.token, { user, until: Date.now() + 60_000 });
    loginHits.delete(clientIp(req)); // a successful sign-in resets the attempt count (only failures are throttled)
    res.json({ user });
  } catch (e) { next(e); }
});

app.post('/api/auth/logout', (req, res) => {
  const t = parseCookies(req.headers.cookie)[COOKIE];
  if (t) { sessionCache.delete(t); revoked.add(t); if (revoked.size > 5000) revoked.delete(revoked.values().next().value); }
  res.append('Set-Cookie', `${COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0${isHttps(req) ? '; Secure' : ''}`);
  res.json({ ok: true });
});

// Everything below needs a signed-in user. Pages redirect to /login; API calls get a 401.
app.use(async (req, res, next) => {
  try {
    const user = await userFromToken(parseCookies(req.headers.cookie)[COOKIE]);
    if (user) { req.user = user; return next(); }
  } catch (e) { return next(e); }
  const wantsPage = req.method === 'GET' && (req.headers.accept || '').includes('text/html') && !req.path.startsWith('/api/');
  if (wantsPage) return res.redirect('/login');
  res.status(401).json({ error: 'Please sign in.' });
});
app.get('/api/auth/me', (req, res) => res.json({ user: req.user }));

// The page's own files (HTML, CSS, JS) are never cached by browsers or by Cloudflare: Cloudflare rewrites a short max-age on
// static files to its 4-hour "Browser Cache TTL", which kept an old copy of this studio's CSS/JS alive in people's browsers
// and paired it with newer HTML (unstyled page, giant icons). `private, no-cache, no-store` stops that, and the URLs below
// carry a content hash so any copy cached before this fix is bypassed.
const NO_CACHE = 'private, no-cache, no-store, must-revalidate';
const PUBLIC_DIR = path.join(__dirname, 'public');
const BUILD = (() => {
  const h = createHash('sha1');
  for (const f of ['index.html', 'style.css', 'app.js', 'headtrack.js']) h.update(readFileSync(path.join(PUBLIC_DIR, f)));
  return h.digest('hex').slice(0, 10);
})();
const versioned = {
  index: readFileSync(path.join(PUBLIC_DIR, 'index.html'), 'utf8')
    .replace('href="/style.css"', `href="/style.css?v=${BUILD}"`).replace('src="/app.js"', `src="/app.js?v=${BUILD}"`),
  app: readFileSync(path.join(PUBLIC_DIR, 'app.js'), 'utf8').replace("'./headtrack.js'", `'./headtrack.js?v=${BUILD}'`),
};
const sendText = (res, type, body) => res.set({ 'Content-Type': type, 'Cache-Control': NO_CACHE }).send(body);
app.get(['/', '/index.html'], (_req, res) => sendText(res, 'text/html; charset=utf-8', versioned.index));
app.get('/app.js', (_req, res) => sendText(res, 'application/javascript; charset=utf-8', versioned.app));
app.use(express.static(PUBLIC_DIR, { setHeaders: (res) => res.setHeader('Cache-Control', NO_CACHE) }));
// Generated models and the images they came from: only the signed-in owner of the task may fetch them
function ownTaskFile(dir) {
  return (req, res, next) => {
    const file = path.basename(req.path);
    const taskId = file.replace(/\.[^.]+$/, '');
    if (db[taskId]?.owner !== req.user.id) return res.status(404).end();
    res.sendFile(path.join(dir, file), { headers: { 'Cache-Control': 'private, no-store' } }, (err) => err && next()); // per-user: never cache at the edge
  };
}
app.use('/models', ownTaskFile(MODELS_DIR));
app.use('/inputs', ownTaskFile(INPUTS_DIR));
app.get('/sample/coffee-mug.glb', (_req, res) => res.sendFile(DUMMY_GLB, { maxAge: '1d' })); // default preview model
app.use('/vendor/three', express.static(path.join(__dirname, 'node_modules', 'three')));
app.use('/vendor/mediapipe', express.static(path.join(__dirname, 'node_modules', '@mediapipe', 'tasks-vision')));
app.use('/vendor/fontsource', express.static(path.join(__dirname, 'node_modules', '@fontsource'), { maxAge: '7d' }));

// Face-detector model for head tracking: downloaded once from Google, then served locally
const FACE_MODEL = path.join(__dirname, 'assets', 'blaze_face_short_range.tflite');
const FACE_MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite';
app.get('/models-ml/blaze_face_short_range.tflite', async (_req, res, next) => {
  try {
    if (!existsSync(FACE_MODEL)) {
      const bytes = await fetchBytes(FACE_MODEL_URL);
      await fs.writeFile(FACE_MODEL, bytes);
    }
    res.sendFile(FACE_MODEL, { maxAge: '7d' });
  } catch (e) { next(httpError(502, `Couldn't download the face model: ${e.message}`)); }
});

app.get('/api/config', (req, res) => res.json({
  user: req.user,
  hasKey: Boolean(API_KEY),
  cutter: { configured: Boolean(SCRAPP_WEBAPP_KEY), api: SCRAPP_API_URL },
  dummy: { forced: DUMMY_FORCED },
  mongo: {
    configured: Boolean(MONGO_URI),
    db: MONGO_DB,
    saveMeshes: Boolean(MONGO_URI) && MONGO_SAVE_MESHES,
    saveDummies: MONGO_SAVE_DUMMIES,
    sources: [
      ...Object.entries(SOURCES).map(([id, s]) => ({ id, label: s.label || id })),
      { id: '__meshes', label: '3D models (meshes)', models: true },
    ],
  },
}));

// ----- MongoDB: list images from a source (paged, newest first) -----
app.get('/api/mongo/images', async (req, res, next) => {
  try {
    const sourceName = req.query.source || Object.keys(SOURCES)[0];
    const src = getSource(sourceName);
    const limit = Math.min(Math.max(Number(req.query.limit) || 24, 1), 100);
    const page = Math.max(Number(req.query.page) || 1, 1);
    const { mdb } = await mongo();
    const coll = mdb.collection(src.collection);
    const filter = { [src.fileField]: { $exists: true, $ne: null }, ...(src.filter || {}) };
    const me = new ObjectId(req.user.id);
    if (req.query.starred === '1') filter.starred = true;
    if (req.query.sharedTo) {
      // "From friends": items of this kind shared with the signed-in user (never anyone else's id)
      const kind = src.meshSource || sourceName;
      const ids = await mdb.collection('shares').distinct('item_id', { to_id: me, kind });
      filter._id = { $in: ids };
    } else {
      filter.owner_id = me;
    }
    const [total, docs] = await Promise.all([
      coll.countDocuments(filter),
      coll.find(filter, { projection: { [src.fileField]: 1, [src.dateField]: 1, starred: 1, owner_id: 1, ...Object.fromEntries(src.titleFields.map((f) => [f, 1])) } })
        .sort({ [src.dateField]: -1, _id: -1 }).skip((page - 1) * limit).limit(limit).toArray(),
    ]);

    // Models already stored in Scrapp's "meshes" collection for these docs (made here or in the app)
    const meshes = new Map();
    if (src.meshField && docs.length) {
      const found = await mdb.collection('meshes')
        .find({ [src.meshField]: { $in: docs.map((d) => d._id) }, glb_file_id: { $exists: true } })
        .sort({ created_at: -1 }).toArray();
      for (const m of found) {
        const k = String(m[src.meshField]);
        const cur = meshes.get(k);
        if (!cur || (cur.dummy && !m.dummy)) meshes.set(k, m);
      }
    }

    const conversions = conversionsIndex(req.user.id);
    res.json({
      source: sourceName, page, limit, total,
      items: docs.map((d) => {
        const t = conversions.get(mongoKey(sourceName, String(d._id)));
        const m = meshes.get(String(d._id));
        return {
          docId: String(d._id),
          fileId: String(d[src.fileField]),
          title: src.titleFields.map((f) => d[f]).find((v) => typeof v === 'string' && v.trim()) || null,
          date: d[src.dateField] || d._id.getTimestamp(),
          image: `/api/mongo/file/${d[src.fileField]}`,
          starred: Boolean(d.starred),
          ownerId: d.owner_id ? String(d.owner_id) : null,
          mine: String(d.owner_id) === req.user.id,
          task: t ? { id: t.id, status: t.glb ? 'READY' : t.status, dummy: Boolean(t.dummy) } : null,
          mesh: m ? {
            id: String(m._id), glb: `/api/mongo/file/${m.glb_file_id}`,
            via: m.created_via || 'scrapp', dummy: Boolean(m.dummy),
          } : null,
        };
      }),
    });
  } catch (e) { next(e); }
});

// ----- MongoDB: every finished 3D model in the "meshes" collection (newest first) -----
app.get('/api/mongo/meshes', async (req, res, next) => {
  try {
    const limit = Math.min(Math.max(Number(req.query.limit) || 24, 1), 100);
    const page = Math.max(Number(req.query.page) || 1, 1);
    const { mdb } = await mongo();
    const coll = mdb.collection('meshes');
    const filter = { glb_file_id: { $exists: true, $ne: null } };
    if (req.query.dummies !== '1') filter.dummy = { $ne: true };
    filter.owner_id = new ObjectId(req.user.id);
    const [total, docs] = await Promise.all([
      coll.countDocuments(filter),
      coll.find(filter).sort({ created_at: -1, _id: -1 }).skip((page - 1) * limit).limit(limit).toArray(),
    ]);
    // Name: the mesh's prompt, else its sticker's title, else a short id
    const stickerIds = docs.filter((m) => !m.prompt && m.sticker_id).map((m) => m.sticker_id);
    const titles = new Map();
    if (stickerIds.length) {
      for (const st of await mdb.collection('stickers').find({ _id: { $in: stickerIds } }, { projection: { title: 1 } }).toArray()) {
        if (st.title) titles.set(String(st._id), st.title);
      }
    }
    res.json({
      page, limit, total,
      items: docs.map((m) => ({
        id: String(m._id),
        name: (typeof m.prompt === 'string' && m.prompt.trim()) || titles.get(String(m.sticker_id))
          || `${m.source || 'model'} ${String(m._id).slice(-6)}`,
        source: m.source || null,
        via: m.created_via || 'scrapp',
        dummy: Boolean(m.dummy),
        date: m.created_at || m._id.getTimestamp(),
        glb: `/api/mongo/file/${m.glb_file_id}`,
        thumb: m.thumb_file_id ? `/api/mongo/file/${m.thumb_file_id}` : null,
      })),
    });
  } catch (e) { next(e); }
});

// ----- Scrapp users: the web app now has real logins, so there is nothing to pick and no user list to leak -----
const userOut = (u) => ({ id: String(u._id), username: u.username, display_name: u.display_name || u.username });
const meId = (req) => new ObjectId(req.user.id);

// ----- Collages: list + load back into the scene -----
app.get('/api/collages', async (req, res, next) => {
  try {
    const { mdb } = await mongo();
    const filter = { owner_id: meId(req) };
    const docs = await mdb.collection('collages').find(filter, { projection: { title: 1, thumbnail_file_id: 1, updated_at: 1, created_via: 1, 'scene.items': 1 } })
      .sort({ updated_at: -1 }).limit(200).toArray();
    res.json(docs.map((c) => ({
      id: String(c._id), title: c.title || 'Untitled collage',
      thumb: c.thumbnail_file_id ? `/api/mongo/file/${c.thumbnail_file_id}` : null,
      updated: c.updated_at || c._id.getTimestamp(), via: c.created_via || 'scrapp',
      itemCount: c.scene?.items?.length || 0,
    })));
  } catch (e) { next(e); }
});

// Scene with a URL for every sticker / mesh (like the backend's _resolve_scene_urls)
app.get('/api/collages/:id', async (req, res, next) => {
  try {
    const { mdb } = await mongo();
    const c = await mdb.collection('collages').findOne({ _id: toObjectId(req.params.id) });
    const shared = c && String(c.owner_id) !== req.user.id && await mdb.collection('shares').findOne({ to_id: meId(req), kind: 'collage', item_id: c._id });
    if (!c || (String(c.owner_id) !== req.user.id && !shared)) throw httpError(404, 'Collage not found');
    const items = [];
    for (const it of c.scene?.items || []) {
      if (!ObjectId.isValid(it.ref_id)) continue;
      if (it.kind === 'sticker') {
        const st = await mdb.collection('stickers').findOne({ _id: new ObjectId(it.ref_id) }, { projection: { image_file_id: 1, title: 1 } });
        if (st?.image_file_id) items.push({ ...it, title: it.title || st.title || 'Sticker', url: `/api/mongo/file/${st.image_file_id}` });
      } else if (it.kind === 'mesh') {
        const m = await mdb.collection('meshes').findOne({ _id: new ObjectId(it.ref_id) }, { projection: { glb_file_id: 1, prompt: 1 } });
        if (m?.glb_file_id) items.push({ ...it, title: it.title || m.prompt || 'Model', url: `/api/mongo/file/${m.glb_file_id}` });
      }
    }
    res.json({ id: String(c._id), title: c.title, scene: { ...c.scene, items } });
  } catch (e) { next(e); }
});

// ----- Friends (same rules as the backend's routers/social.py) -----
app.get('/api/friends', async (req, res, next) => {
  try {
    const me = meId(req);
    const { mdb } = await mongo();
    const fr = mdb.collection('friendships');
    const accepted = await fr.find({ status: 'accepted', $or: [{ requester_id: me }, { addressee_id: me }] }).toArray();
    const friendIds = accepted.map((f) => (String(f.requester_id) === String(me) ? f.addressee_id : f.requester_id));
    const incoming = await fr.find({ addressee_id: me, status: 'pending' }).toArray();
    const outgoing = await fr.find({ requester_id: me, status: 'pending' }).toArray();
    const ids = [...friendIds, ...incoming.map((f) => f.requester_id), ...outgoing.map((f) => f.addressee_id)];
    const users = new Map((await mdb.collection('users').find({ _id: { $in: ids } }).toArray()).map((u) => [String(u._id), userOut(u)]));
    res.json({
      friends: friendIds.map((id) => users.get(String(id))).filter(Boolean),
      incoming: incoming.map((f) => ({ request_id: String(f._id), from: users.get(String(f.requester_id)) })).filter((x) => x.from),
      outgoing: outgoing.map((f) => users.get(String(f.addressee_id))).filter(Boolean),
    });
  } catch (e) { next(e); }
});

app.post('/api/friends/request', async (req, res, next) => {
  try {
    const me = meId(req);
    const username = String(req.body?.username || '').trim().replace(/^@/, '').toLowerCase();
    if (!username) throw httpError(400, 'Type a username.');
    const { mdb } = await mongo();
    const other = await mdb.collection('users').findOne({ username });
    if (!other || String(other._id) === String(me)) throw httpError(404, 'No such user');
    const fr = mdb.collection('friendships');
    const reverse = await fr.findOne({ requester_id: other._id, addressee_id: me });
    if (reverse) { // they already asked: accept
      await fr.updateOne({ _id: reverse._id }, { $set: { status: 'accepted' } });
      return res.json({ status: 'accepted' });
    }
    const existing = await fr.findOne({ requester_id: me, addressee_id: other._id });
    if (!existing) await fr.insertOne({ requester_id: me, addressee_id: other._id, status: 'pending', created_at: new Date() });
    res.json({ status: existing?.status || 'pending' });
  } catch (e) { next(e); }
});

app.post('/api/friends/:id/accept', async (req, res, next) => {
  try {
    const me = meId(req);
    const { mdb } = await mongo();
    const r = await mdb.collection('friendships').updateOne({ _id: toObjectId(req.params.id), addressee_id: me }, { $set: { status: 'accepted' } });
    if (!r.modifiedCount && !r.matchedCount) throw httpError(404, 'Request not found');
    res.json({ status: 'accepted' });
  } catch (e) { next(e); }
});

// ----- Inbox: things friends sent you (hunts are left out of the web app) -----
app.get('/api/inbox', async (req, res, next) => {
  try {
    const me = meId(req);
    const { mdb } = await mongo();
    const shares = await mdb.collection('shares').find({ to_id: me, kind: { $in: ['sticker', 'mesh', 'collage'] } })
      .sort({ created_at: -1 }).limit(100).toArray();
    const out = [];
    for (const s of shares) {
      const coll = { sticker: 'stickers', mesh: 'meshes', collage: 'collages' }[s.kind];
      const item = await mdb.collection(coll).findOne({ _id: s.item_id });
      if (!item) continue;
      const from = await mdb.collection('users').findOne({ _id: s.from_id }, { projection: { username: 1, display_name: 1 } });
      const file = (id) => (id ? `/api/mongo/file/${id}` : null);
      out.push({
        id: String(s._id), kind: s.kind, message: s.message || null, created: s.created_at,
        from: from ? userOut(from) : null, itemId: String(item._id),
        title: item.title || item.prompt || null,
        image: s.kind === 'sticker' ? file(item.image_file_id) : s.kind === 'mesh' ? file(item.thumb_file_id) : file(item.thumbnail_file_id),
        glb: s.kind === 'mesh' ? file(item.glb_file_id) : null,
      });
    }
    res.json(out);
  } catch (e) { next(e); }
});

// ----- Sticker cutter (SAM 3 on the Scrapp backend) -----
app.get('/api/cut/health', async (_req, res, next) => {
  try { res.json(await scrapp('/webapp/health')); } catch (e) { next(e); }
});

// Start cutting: an existing capture, or an uploaded photo (saved as a capture first, like the app does)
const cutTokens = new Map(); // bridge token -> user id, so one user can't finish another user's cut
const ownCapture = async (req, captureId) => {
  const { mdb } = await mongo();
  const cap = await mdb.collection('captures').findOne({ _id: toObjectId(captureId), owner_id: meId(req) }, { projection: { _id: 1 } });
  if (!cap) throw httpError(404, 'Capture not found');
};
const rememberToken = (req, r) => { if (r?.token) { cutTokens.set(r.token, req.user.id); if (cutTokens.size > 2000) cutTokens.delete(cutTokens.keys().next().value); } return r; };
app.post('/api/cut/start', async (req, res, next) => {
  try {
    const { docId, image, name } = req.body || {};
    const { mdb } = await mongo();
    if (docId) {
      const cap = await mdb.collection('captures').findOne({ _id: toObjectId(docId), owner_id: meId(req) });
      if (!cap) throw httpError(404, 'Capture not found');
      return res.json({ captureId: String(cap._id), image: `/api/mongo/file/${cap.original_file_id}`, title: cap.place_name || cap.transcript || '' });
    }
    const m = typeof image === 'string' && image.match(DATA_URI_RE);
    if (!m) throw httpError(400, 'Send a JPEG, PNG or WebP image.');
    const r = await scrapp('/webapp/captures', { owner_id: req.user.id, image_b64: image, place_name: name || null });
    res.json({ captureId: r.capture_id, image: `/api/mongo/file/${r.original_file_id}`, title: name || '' });
  } catch (e) { next(e); }
});

app.post('/api/cut/segment', async (req, res, next) => {
  try {
    const { captureId, prompt } = req.body || {};
    await ownCapture(req, captureId);
    res.json(rememberToken(req, await scrapp('/webapp/segment', { capture_id: captureId, prompt: prompt || null, max_candidates: 10 })));
  } catch (e) { next(e); }
});

app.post('/api/cut/point', async (req, res, next) => {
  try {
    const { captureId, x, y, token } = req.body || {};
    await ownCapture(req, captureId);
    if (token && cutTokens.get(token) !== req.user.id) throw httpError(404, 'That cut expired. Start again.');
    res.json(rememberToken(req, await scrapp('/webapp/segment/point', { capture_id: captureId, x, y, token: token || null })));
  } catch (e) { next(e); }
});

app.post('/api/cut/stickers', async (req, res, next) => {
  try {
    const { token, indices, title } = req.body || {};
    if (cutTokens.get(token) !== req.user.id) throw httpError(404, 'That cut expired. Start again.');
    const r = await scrapp('/webapp/stickers', { token, indices, title: title || null });
    res.json({ stickers: r.stickers.map((s) => ({ ...s, image: `/api/mongo/file/${s.image_file_id}` })) });
  } catch (e) { next(e); }
});

// ----- MongoDB: save the 3D scene as a Scrapp collage -----
// Same document the Scrapp backend writes (routers/collages.py):
//   { owner_id, title, scene: { version, items[{ id, kind, ref_id, position, quaternion, scale }], zone, filters, camera },
//     thumbnail_file_id, created_at, updated_at }
app.post('/api/collages', async (req, res, next) => {
  try {
    const { title: rawTitle, scene, thumbnail, collageId } = req.body || {};
    if (!scene || !Array.isArray(scene.items)) throw httpError(422, 'scene.items missing');
    const title = String(rawTitle || 'Web scene').slice(0, 120);
    const { mdb, bucket } = await mongo();

    // Keep only items whose sticker / mesh still exists
    const kept = [], dropped = [];
    let firstOwner = null;
    for (const it of scene.items) {
      const coll = it?.kind === 'sticker' ? 'stickers' : it?.kind === 'mesh' ? 'meshes' : null;
      if (!coll || !ObjectId.isValid(it.ref_id)) { dropped.push(it?.title || it?.ref_id); continue; }
      const doc = await mdb.collection(coll).findOne({ _id: new ObjectId(it.ref_id) }, { projection: { owner_id: 1 } });
      const usable = doc && (String(doc.owner_id) === req.user.id
        || await mdb.collection('shares').findOne({ to_id: meId(req), kind: it.kind, item_id: doc._id }));
      if (!usable) { dropped.push(it.title || it.ref_id); continue; }
      firstOwner ||= doc.owner_id || null;
      const num = (a, n) => (Array.isArray(a) && a.length === n && a.every(Number.isFinite) ? a : null);
      kept.push({
        id: String(it.id || `w${kept.length + 1}`), kind: it.kind, ref_id: it.ref_id,
        ...(it.title ? { title: String(it.title).slice(0, 120) } : {}),
        position: num(it.position, 3) || [0, 0, 0],
        quaternion: num(it.quaternion, 4) || [0, 0, 0, 1],
        scale: Number.isFinite(it.scale) && it.scale > 0 ? it.scale : 1,
      });
    }
    if (!kept.length) throw httpError(422, 'None of the scene items exist in MongoDB.');
    const cleanScene = {
      version: 1, items: kept,
      zone: scene.zone || { center: [0, 0.6, 0], size: [1.2, 1.2, 1.2] },
      filters: scene.filters || { pixelate: 0, motionBlur: 0 },
      camera: scene.camera || { position: [2.4, 2.0, 3.2], target: [0, 0.6, 0] },
    };

    // Owner: always the signed-in user
    const ownerId = meId(req);

    let thumbId = null;
    const m = typeof thumbnail === 'string' && thumbnail.match(/^data:image\/png;base64,([A-Za-z0-9+/=]+)$/);
    if (m) thumbId = await putGridFile(bucket, Buffer.from(m[1], 'base64'), 'collage.png', 'image/png', ownerId, 'collage_render');

    const collages = mdb.collection('collages');
    const existing = collageId && ObjectId.isValid(collageId) ? await collages.findOne({ _id: new ObjectId(collageId), owner_id: ownerId }) : null;
    const now = new Date();
    if (existing) {
      const upd = { title, scene: cleanScene, updated_at: now, ...(thumbId ? { thumbnail_file_id: thumbId } : {}) };
      await collages.updateOne({ _id: existing._id }, { $set: upd });
      if (thumbId && existing.thumbnail_file_id) {
        try { await bucket.delete(existing.thumbnail_file_id); } catch { /* already gone */ }
      }
      return res.json({ id: String(existing._id), title, itemCount: kept.length, dropped, updated: true });
    }
    const doc = {
      owner_id: ownerId, title, scene: cleanScene, thumbnail_file_id: thumbId,
      created_at: now, updated_at: now, created_via: 'web-app',
    };
    const { insertedId } = await collages.insertOne(doc);
    res.status(201).json({ id: String(insertedId), title, itemCount: kept.length, dropped, updated: false });
  } catch (e) { next(e); }
});

// A file is readable by its owner, or when it belongs to a sticker / model / collage a friend shared with you
// (including the stickers and models inside a shared collage).
async function canReadFile(mdb, me, fileId, meta) {
  if (meta.metadata?.owner_id && String(meta.metadata.owner_id) === String(me)) return true;
  const shares = await mdb.collection('shares').find({ to_id: me, kind: { $in: ['sticker', 'mesh', 'collage'] } }, { projection: { kind: 1, item_id: 1 } }).toArray();
  if (!shares.length) return false;
  const ids = (k) => shares.filter((x) => x.kind === k).map((x) => x.item_id);
  const hit = (coll, fields) => mdb.collection(coll).findOne({ _id: { $in: ids(coll === 'stickers' ? 'sticker' : coll === 'meshes' ? 'mesh' : 'collage') }, $or: fields.map((f) => ({ [f]: fileId })) }, { projection: { _id: 1 } });
  if (await hit('stickers', ['image_file_id', 'mask_file_id'])) return true;
  if (await hit('meshes', ['glb_file_id', 'thumb_file_id'])) return true;
  if (await hit('collages', ['thumbnail_file_id'])) return true;
  const colls = await mdb.collection('collages').find({ _id: { $in: ids('collage') } }, { projection: { 'scene.items': 1 } }).toArray();
  const refs = colls.flatMap((c) => (c.scene?.items || []).filter((i) => ObjectId.isValid(i.ref_id)).map((i) => ({ kind: i.kind, id: new ObjectId(i.ref_id) })));
  const sticks = refs.filter((r) => r.kind === 'sticker').map((r) => r.id), meshes = refs.filter((r) => r.kind === 'mesh').map((r) => r.id);
  if (sticks.length && await mdb.collection('stickers').findOne({ _id: { $in: sticks }, image_file_id: fileId }, { projection: { _id: 1 } })) return true;
  if (meshes.length && await mdb.collection('meshes').findOne({ _id: { $in: meshes }, glb_file_id: fileId }, { projection: { _id: 1 } })) return true;
  return false;
}

// ----- MongoDB: stream a file out of GridFS (thumbnails, GLBs) -----
app.get('/api/mongo/file/:fileId', async (req, res, next) => {
  try {
    const { mdb, bucket } = await mongo();
    const fileId = toObjectId(req.params.fileId);
    const meta = await mdb.collection(`${MONGO_BUCKET}.files`).findOne({ _id: fileId });
    if (!meta || !(await canReadFile(mdb, meId(req), fileId, meta))) return res.status(404).json({ error: 'File not found' });
    res.set('Content-Type', meta.metadata?.content_type || meta.contentType || 'application/octet-stream');
    res.set('Cache-Control', 'private, max-age=86400');
    bucket.openDownloadStream(fileId).on('error', next).pipe(res);
  } catch (e) { next(e); }
});

// Create a new Image-to-3D task — from an uploaded data URI, or from a MongoDB image.
// options.dummy (or MESHY_DUMMY=1) returns a sample model without calling Meshy.
app.post('/api/generate', async (req, res, next) => {
  try {
    let { image, name, options = {}, mongo: mongoRef } = req.body || {};
    const dummy = DUMMY_FORCED || options.dummy === true;
    if (dummy && !existsSync(DUMMY_GLB)) throw httpError(500, 'assets/dummy.glb is missing.');
    let bytes, ext, mongoInfo = null;

    if (mongoRef) {
      const key = mongoKey(mongoRef.source, mongoRef.docId);
      // Real generations spend credits: never start one twice for the same image unless forced.
      if (!dummy && !mongoRef.force) {
        const existing = conversionsIndex(req.user.id).get(key);
        if (existing && !existing.dummy && !FAILED(existing.status)) {
          return res.status(409).json({ error: 'This image is already converted or in progress.', task: existing });
        }
        const scrapp = await findScrappMesh(mongoRef.source, mongoRef.docId);
        if (scrapp) return res.status(409).json({ error: 'This image already has a 3D model in Scrapp.' });
      }
      const img = await loadMongoImage(mongoRef.source, mongoRef.docId, req.user.id);
      bytes = img.bytes;
      ext = img.type;
      mongoInfo = img.ref;
      name = name || img.title || `${mongoRef.source} ${String(mongoRef.docId).slice(-6)}`;
      image = `data:image/${ext};base64,${bytes.toString('base64')}`;
    } else {
      const m = typeof image === 'string' && image.match(DATA_URI_RE);
      if (!m) return res.status(400).json({ error: 'Send a JPEG, PNG or WebP image as a base64 data URI.' });
      bytes = Buffer.from(m[2], 'base64');
      ext = m[1] === 'jpg' ? 'jpeg' : m[1];
    }
    name = name || 'Untitled';
    if (bytes.length > 20 * 1024 * 1024) return res.status(400).json({ error: 'Image must be 20 MB or less.' });

    if (!dummy && MESHY_DAILY_CAP > 0) {  // real generations spend Meshy credits: cap them per user per day
      const since = Date.now() - 24 * 3600 * 1000;
      const used = Object.values(db).filter((t) => t.owner === req.user.id && !t.dummy && t.createdAt > since).length;
      if (used >= MESHY_DAILY_CAP) return res.status(429).json({ error: `Daily limit reached (${MESHY_DAILY_CAP} real 3D models a day). Try again tomorrow, or use dummy mode.` });
    }
    const payload = { image_url: image, target_formats: ['glb'] };
    for (const k of OPTION_KEYS) if (options[k] !== undefined && options[k] !== '') payload[k] = options[k];
    if (payload.should_texture === false) { delete payload.enable_pbr; delete payload.texture_prompt; }

    const id = dummy
      ? `dummy-${randomUUID().slice(0, 8)}`
      : (await meshy('/openapi/v1/image-to-3d', { method: 'POST', body: JSON.stringify(payload) })).result;

    await fs.writeFile(path.join(INPUTS_DIR, `${id}.${ext}`), bytes);
    const { image_url, ...settings } = payload;
    // Replace older local records for this image that are failed or dummy (keeps the gallery tidy)
    if (mongoInfo) {
      for (const t of Object.values(db)) {
        if (t.owner === req.user.id && t.mongo && mongoKey(t.mongo.source, t.mongo.docId) === mongoKey(mongoInfo.source, mongoInfo.docId)
            && (FAILED(t.status) || t.dummy || mongoRef.force)) delete db[t.id];
      }
    }
    db[id] = {
      id, name: String(name).slice(0, 80), status: 'PENDING', progress: 0,
      input: `/inputs/${id}.${ext}`, glb: null, thumbnail: null, dummy,
      mongo: mongoInfo, settings, createdAt: Date.now(),
      owner: req.user.id,
    };
    await saveDb();
    res.status(201).json(db[id]);
  } catch (e) { next(e); }
});

// List local tasks (newest first)
const ownTask = (req, id) => (db[id]?.owner === req.user.id ? db[id] : null);
app.get('/api/tasks', (req, res) => {
  res.json(Object.values(db).filter((t) => t.owner === req.user.id).sort((a, b) => b.createdAt - a.createdAt));
});

// Get one task — refreshes status from Meshy (or the dummy timer) until it finishes
app.get('/api/tasks/:id', async (req, res, next) => {
  try {
    const record = ownTask(req, req.params.id);
    if (!record) return res.status(404).json({ error: 'Not found' });
    if (record.glb || FAILED(record.status)) return res.json(record);

    let task;
    if (record.dummy) {
      const elapsed = Date.now() - record.createdAt;
      task = elapsed >= DUMMY_DURATION_MS
        ? { status: 'SUCCEEDED', progress: 100 }
        : { status: elapsed < 1000 ? 'PENDING' : 'IN_PROGRESS', progress: Math.floor((elapsed / DUMMY_DURATION_MS) * 99) };
    } else {
      task = await meshy(`/openapi/v1/image-to-3d/${encodeURIComponent(record.id)}`);
    }
    record.status = task.status;
    record.progress = task.progress ?? record.progress;
    record.queue = task.preceding_tasks ?? null;
    if (task.status === 'FAILED') record.error = task.task_error?.message || 'Generation failed';
    if (task.status === 'SUCCEEDED') {
      record.status = 'DOWNLOADING';
      try { await finalize(record, task); }
      catch (err) { record.status = 'FAILED'; record.error = err.message; }
    }
    await saveDb();
    res.json(record);
  } catch (e) { next(e); }
});

// Retry saving a finished model to MongoDB (e.g. after fixing MONGO_URI)
app.post('/api/tasks/:id/save', async (req, res, next) => {
  try {
    const record = ownTask(req, req.params.id);
    if (!record) return res.status(404).json({ error: 'Not found' });
    if (!record.glb) return res.status(409).json({ error: 'Model is not finished yet.' });
    if (!record.mongoSave?.meshId) delete record.mongoSave;
    try { await saveMeshToMongo(record); }
    catch (e) { record.mongoSave = { error: e.message }; }
    await saveDb();
    res.status(record.mongoSave?.error ? 502 : 200).json(record);
  } catch (e) { next(e); }
});

// Remove a model from the local gallery (does not delete it on Meshy or in MongoDB)
app.delete('/api/tasks/:id', async (req, res) => {
  const record = ownTask(req, req.params.id);
  if (!record) return res.status(404).json({ error: 'Not found' });
  for (const f of [record.glb, record.thumbnail, record.input]) {
    if (f) await fs.rm(path.join(DATA_DIR, f.replace(/^\/+/, '')), { force: true });
  }
  delete db[req.params.id];
  await saveDb();
  res.status(204).end();
});

app.use((err, _req, res, _next) => {
  console.error(err);
  res.status(err.status && err.status < 600 ? err.status : 500).json({ error: err.message || 'Server error' });
});

app.listen(PORT, () => {
  console.log(`Meshy 3D Studio running at http://localhost:${PORT}`);
  if (DUMMY_FORCED) console.log('ℹ  MESHY_DUMMY=1 — every generation returns the sample model (no credits used)');
  else if (!API_KEY) console.warn('⚠  MESHY_API_KEY is not set — only the dummy model will work');
  if (MONGO_URI) console.log(`MongoDB: db "${MONGO_DB}", bucket "${MONGO_BUCKET}", saving meshes: ${MONGO_SAVE_MESHES}`);
});

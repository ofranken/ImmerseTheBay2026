// Meshy 3D Studio — tiny Express backend.
// Keeps your Meshy API key off the browser, proxies Image-to-3D tasks,
// and downloads finished GLBs locally (Meshy asset URLs expire and are cross-origin).

import express from 'express';
import { MongoClient, GridFSBucket, ObjectId } from 'mongodb';
import fs from 'node:fs/promises';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT) || 3000;
const API_KEY = process.env.MESHY_API_KEY;
const MESHY_BASE = (process.env.MESHY_BASE_URL || 'https://api.meshy.ai').replace(/\/$/, '');

const DATA_DIR = path.join(__dirname, 'data');
const MODELS_DIR = path.join(DATA_DIR, 'models');
const INPUTS_DIR = path.join(DATA_DIR, 'inputs');
const DB_FILE = path.join(DATA_DIR, 'tasks.json');
for (const d of [DATA_DIR, MODELS_DIR, INPUTS_DIR]) if (!existsSync(d)) mkdirSync(d, { recursive: true });

// ---------- tiny JSON "database" ----------
let db = existsSync(DB_FILE) ? JSON.parse(await fs.readFile(DB_FILE, 'utf8')) : {};
let saveChain = Promise.resolve();
const saveDb = () => (saveChain = saveChain.then(() => fs.writeFile(DB_FILE, JSON.stringify(db, null, 2))));

// ---------- Meshy helpers ----------
async function meshy(pathname, init = {}) {
  if (!API_KEY) {
    const err = new Error('MESHY_API_KEY is not set. Add it to .env and restart.');
    err.status = 500;
    throw err;
  }
  const res = await fetch(`${MESHY_BASE}${pathname}`, {
    ...init,
    headers: { Authorization: `Bearer ${API_KEY}`, 'Content-Type': 'application/json', ...(init.headers || {}) },
  });
  const text = await res.text();
  let body;
  try { body = text ? JSON.parse(text) : {}; } catch { body = { message: text }; }
  if (!res.ok) {
    const err = new Error(body.message || `Meshy API error (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return body;
}

async function download(url, dest) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Download failed (${res.status}) for ${dest}`);
  await fs.writeFile(dest, Buffer.from(await res.arrayBuffer()));
}

// Allowed options forwarded to Meshy (whitelist so the client can't send arbitrary fields).
const OPTION_KEYS = [
  'ai_model', 'model_type', 'geometry_resolution', 'should_texture', 'enable_pbr',
  'texture_resolution', 'texture_prompt', 'should_remesh', 'topology', 'target_polycount',
  'pose_mode', 'image_enhancement', 'remove_lighting', 'auto_size', 'origin_at',
];

const DATA_URI_RE = /^data:image\/(jpeg|jpg|png|webp);base64,([A-Za-z0-9+/=]+)$/;
const finalizing = new Map(); // taskId -> Promise (avoid double downloads)

async function finalize(record, task) {
  if (finalizing.has(record.id)) return finalizing.get(record.id);
  const job = (async () => {
    const glbUrl = task.model_urls?.glb;
    if (!glbUrl) throw new Error('Task succeeded but no GLB was returned.');
    await download(glbUrl, path.join(MODELS_DIR, `${record.id}.glb`));
    record.glb = `/models/${record.id}.glb`;
    if (task.thumbnail_url) {
      try {
        await download(task.thumbnail_url, path.join(MODELS_DIR, `${record.id}.png`));
        record.thumbnail = `/models/${record.id}.png`;
      } catch { /* thumbnail is optional */ }
    }
    record.status = 'SUCCEEDED';
    record.progress = 100;
    record.credits = task.consumed_credits ?? null;
    record.finishedAt = Date.now();
    await saveDb();
  })().finally(() => finalizing.delete(record.id));
  finalizing.set(record.id, job);
  return job;
}

// ---------- MongoDB image source (Scrapp schema by default) ----------
// Images live in a GridFS bucket; documents in a collection point at them via an ObjectId field.
const MONGO_URI = process.env.MONGO_URI;
const MONGO_DB = process.env.MONGO_DB || 'scrapp';
const MONGO_BUCKET = process.env.MONGO_BUCKET || 'media';

const DEFAULT_SOURCES = {
  captures: {
    label: 'Captures (original photos)',
    collection: 'captures',
    fileField: 'original_file_id',
    titleFields: ['place_name', 'transcript', 'prompt'],
    dateField: 'captured_at',
  },
  stickers: {
    label: 'Stickers (cut-out objects)',
    collection: 'stickers',
    fileField: 'image_file_id',
    titleFields: ['title', 'place_name'],
    dateField: 'created_at',
  },
};
let SOURCES = DEFAULT_SOURCES;
if (process.env.MONGO_SOURCES_JSON) {
  try { SOURCES = JSON.parse(process.env.MONGO_SOURCES_JSON); }
  catch (e) { console.error('Invalid MONGO_SOURCES_JSON, using defaults:', e.message); }
}

let mongoPromise = null;
function mongo() {
  if (!MONGO_URI) {
    const err = new Error('MONGO_URI is not set. Add it to .env and restart.');
    err.status = 503;
    throw err;
  }
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
  if (!src) { const e = new Error(`Unknown source "${name}"`); e.status = 400; throw e; }
  return src;
}

function toObjectId(id) {
  if (!ObjectId.isValid(id)) { const e = new Error('Invalid id'); e.status = 400; throw e; }
  return new ObjectId(id);
}

async function readGridFile(bucket, fileId) {
  const chunks = [];
  for await (const c of bucket.openDownloadStream(fileId)) chunks.push(c);
  return Buffer.concat(chunks);
}

// Meshy accepts JPEG / PNG / WebP — detect from the bytes, not the stored metadata.
function sniffImageType(buf) {
  if (buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'jpeg';
  if (buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return 'png';
  if (buf.toString('ascii', 0, 4) === 'RIFF' && buf.toString('ascii', 8, 12) === 'WEBP') return 'webp';
  return null;
}

const mongoKey = (source, docId) => `${source}:${docId}`;
function conversionsIndex() {
  const map = new Map();
  for (const t of Object.values(db)) if (t.mongo) map.set(mongoKey(t.mongo.source, t.mongo.docId), t);
  return map;
}

// Loads a Mongo image doc and returns { bytes, type, title, ref }
async function loadMongoImage(sourceName, docId) {
  const src = getSource(sourceName);
  const { mdb, bucket } = await mongo();
  const doc = await mdb.collection(src.collection).findOne({ _id: toObjectId(docId) });
  if (!doc) { const e = new Error('Image document not found in MongoDB'); e.status = 404; throw e; }
  const fileId = doc[src.fileField];
  if (!fileId) { const e = new Error(`Document has no "${src.fileField}"`); e.status = 422; throw e; }
  const bytes = await readGridFile(bucket, fileId);
  const type = sniffImageType(bytes);
  if (!type) { const e = new Error('Stored file is not a JPEG, PNG or WebP image'); e.status = 422; throw e; }
  const title = src.titleFields.map((f) => doc[f]).find((v) => typeof v === 'string' && v.trim());
  return { bytes, type, title, ref: { source: sourceName, docId: String(doc._id), fileId: String(fileId) } };
}

// ---------- app ----------
const app = express();
app.use(express.json({ limit: '30mb' }));
app.use(express.static(path.join(__dirname, 'public')));
app.use('/models', express.static(MODELS_DIR));
app.use('/inputs', express.static(INPUTS_DIR));
app.use('/vendor/three', express.static(path.join(__dirname, 'node_modules', 'three')));

app.get('/api/config', (_req, res) => res.json({
  hasKey: Boolean(API_KEY),
  mongo: {
    configured: Boolean(MONGO_URI),
    db: MONGO_DB,
    sources: Object.entries(SOURCES).map(([id, s]) => ({ id, label: s.label || id })),
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
    const [total, docs] = await Promise.all([
      coll.countDocuments(filter),
      coll.find(filter, { projection: { [src.fileField]: 1, [src.dateField]: 1, ...Object.fromEntries(src.titleFields.map((f) => [f, 1])) } })
        .sort({ [src.dateField]: -1, _id: -1 }).skip((page - 1) * limit).limit(limit).toArray(),
    ]);
    const conversions = conversionsIndex();
    res.json({
      source: sourceName, page, limit, total,
      items: docs.map((d) => {
        const t = conversions.get(mongoKey(sourceName, String(d._id)));
        return {
          docId: String(d._id),
          fileId: String(d[src.fileField]),
          title: src.titleFields.map((f) => d[f]).find((v) => typeof v === 'string' && v.trim()) || null,
          date: d[src.dateField] || d._id.getTimestamp(),
          image: `/api/mongo/file/${d[src.fileField]}`,
          task: t ? { id: t.id, status: t.glb ? 'READY' : t.status } : null,
        };
      }),
    });
  } catch (e) { next(e); }
});

// ----- MongoDB: stream an image out of GridFS (thumbnails / previews) -----
app.get('/api/mongo/file/:fileId', async (req, res, next) => {
  try {
    const { mdb, bucket } = await mongo();
    const fileId = toObjectId(req.params.fileId);
    const meta = await mdb.collection(`${MONGO_BUCKET}.files`).findOne({ _id: fileId });
    if (!meta) return res.status(404).json({ error: 'File not found' });
    res.set('Content-Type', meta.metadata?.content_type || meta.contentType || 'application/octet-stream');
    res.set('Cache-Control', 'private, max-age=86400');
    bucket.openDownloadStream(fileId).on('error', next).pipe(res);
  } catch (e) { next(e); }
});

// Create a new Image-to-3D task — from an uploaded data URI, or from a MongoDB image
app.post('/api/generate', async (req, res, next) => {
  try {
    let { image, name, options = {}, mongo: mongoRef } = req.body || {};
    let bytes, ext, mongoInfo = null;

    if (mongoRef) {
      const key = mongoKey(mongoRef.source, mongoRef.docId);
      const existing = conversionsIndex().get(key);
      if (existing && !['FAILED', 'CANCELED'].includes(existing.status) && !mongoRef.force) {
        return res.status(409).json({ error: 'This image is already converted or in progress.', task: existing });
      }
      const img = await loadMongoImage(mongoRef.source, mongoRef.docId);
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

    const payload = { image_url: image, target_formats: ['glb'] };
    for (const k of OPTION_KEYS) if (options[k] !== undefined && options[k] !== '') payload[k] = options[k];
    if (payload.should_texture === false) { delete payload.enable_pbr; delete payload.texture_prompt; }

    const { result: id } = await meshy('/openapi/v1/image-to-3d', { method: 'POST', body: JSON.stringify(payload) });

    await fs.writeFile(path.join(INPUTS_DIR, `${id}.${ext}`), bytes);
    const { image_url, ...settings } = payload;
    // A retry of a failed Mongo image replaces the old local record
    if (mongoInfo) {
      const old = conversionsIndex().get(mongoKey(mongoInfo.source, mongoInfo.docId));
      if (old) delete db[old.id];
    }
    db[id] = {
      id, name: String(name).slice(0, 80), status: 'PENDING', progress: 0,
      input: `/inputs/${id}.${ext}`, glb: null, thumbnail: null,
      mongo: mongoInfo, settings, createdAt: Date.now(),
    };
    await saveDb();
    res.status(201).json(db[id]);
  } catch (e) { next(e); }
});

// List local tasks (newest first)
app.get('/api/tasks', (_req, res) => {
  res.json(Object.values(db).sort((a, b) => b.createdAt - a.createdAt));
});

// Get one task — refreshes status from Meshy until it finishes
app.get('/api/tasks/:id', async (req, res, next) => {
  try {
    const record = db[req.params.id];
    if (!record) return res.status(404).json({ error: 'Not found' });
    if (record.glb || ['FAILED', 'CANCELED'].includes(record.status)) return res.json(record);

    const task = await meshy(`/openapi/v1/image-to-3d/${encodeURIComponent(record.id)}`);
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

// Remove a model from the local gallery (does not delete it on Meshy)
app.delete('/api/tasks/:id', async (req, res) => {
  const record = db[req.params.id];
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
  if (!API_KEY) console.warn('⚠  MESHY_API_KEY is not set — generation will fail until you add it to .env');
});

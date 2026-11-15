# Meshy 3D Studio

Drop in a JPEG → Meshy AI turns it into a textured 3D model → view it in an interactive three.js viewer → download a GLB that drops straight into any three.js project.

## Signing in

The studio uses **Scrapp accounts**: the same username/email and password as the phone app (sign up in the app). Login is proxied
to the Scrapp API (`SCRAPP_API_URL`, default `http://localhost:8000`) and the resulting JWT is kept in an HttpOnly cookie
(`scrapp_studio`, 14 days). There is no shared password.

- Everything is per user: captures, stickers, 3D models, collages, tasks and the files behind them. The server derives the user from the
  session and ignores any `owner`, `me` or `actingAs` the browser sends. Stickers, models and collages friends **shared with you** are
  readable too.
- Real Meshy generations (they spend credits) are capped per user per day (`STUDIO_MESHY_DAILY_CAP`, default 10); dummy mode is free.
- Sign-in attempts are throttled per IP; signing out revokes the cookie on the server.
- Behind the Cloudflare tunnel the studio's paths must be routed to port 3000: see `deploy/cloudflared/ingress.example.yml`.
- Test: `BASE=https://scrapp.nmagic.dev node --test test/auth.e2e.mjs` (needs the API, the studio and the `11111111` / `22222222` accounts).

## Setup

Requires Node 20.6+.

```bash
npm install
cp .env.example .env        # then paste your Meshy API key into .env
npm start                   # http://localhost:3000
```

Get an API key at https://www.meshy.ai/settings/api (API access needs a paid Meshy plan; each generation costs credits).


## Layout (matches the Scrapp app)

The web app uses the Scrapp app's design language: cream paper, raised cards, teal pill buttons, Anton headers and the Yellowtail wordmark. It has the same bottom tabs, except **Hunts**, which the web app leaves out.

| Tab | What's there |
|---|---|
| **Scrap** | Make it 3D (drop a photo, Dummy model toggle), In progress, Recent captures (Mine / Everyone) |
| **Book** | Sticker book: Mine / From friends, Starred / All. Hover a sticker for **2D** (add to the scene) or **+3D**. Click stickers to select them, then **Make 3D** |
| **Studio** | Collages: New collage, Save scene as collage, and your saved collages (click one to open it in the 3D view). 3D: models made here, plus models in MongoDB (Mine / Everyone) |
| **Friends** | Add by username, Inbox (stickers, models and collages friends sent you), Requests (Accept), Your friends |

**Acting as:** the web app has no login, so the user picker at the top chooses whose captures, stickers, collages and friends you see. That user also owns anything you save: models made from uploads, and collages. "Everyone" shows all users' items.

**Settings (⚙ / tune icon):** Meshy generation options (AI model, polycount, topology, textures).

Fonts (Anton, Yellowtail, Nunito) are bundled from npm (`@fontsource/*`), so nothing loads from Google Fonts.

## How it works

```
Browser ──(base64 JPEG)──► Express /api/generate ──► Meshy POST /openapi/v1/image-to-3d
   ▲                              │
   │ polls /api/tasks/:id         └─► Meshy GET /openapi/v1/image-to-3d/:id
   │                                    (on SUCCEEDED: GLB + thumbnail saved to data/models/)
   └── three.js GLTFLoader loads /models/<id>.glb (same origin, no CORS issues)
```

- **The API key stays on the server.** The browser never sees it.
- **Models are saved locally.** Meshy's download links expire, so the server copies each finished GLB into `data/models/`.
- **Only GLB is requested** (`target_formats: ["glb"]`). GLB is the format three.js loads best.
- Large photos are downscaled in the browser to 2048 px on the longest side before upload.

## Converting images from MongoDB

Set `MONGO_URI` (plus `MONGO_DB` / `MONGO_BUCKET` if they differ) in `.env`, restart, and open the **MongoDB** tab.

The defaults match the Scrapp backend:

| Source | Collection | Image reference | Title from | Sorted by |
|---|---|---|---|---|
| Captures (original photos) | `captures` | `original_file_id` → GridFS `media` | `place_name`, `transcript`, `prompt` | `captured_at` |
| Stickers (cut-out objects) | `stickers` | `image_file_id` → GridFS `media` | `title`, `place_name` | `created_at` |

- Thumbnails stream straight from GridFS (`/api/mongo/file/:fileId`).
- Click images to select them, or use **Select unconverted**, then **Convert N images**. The generation options apply to the whole batch.
- Converted images show a **3D ✓** badge. Click one to open its model. Images still in progress show a % badge.
- An image is never converted twice by accident: the server returns 409 if it's already done or in progress. Failed ones can be retried.
- Files are checked by their bytes. Anything that isn't JPEG, PNG or WebP (e.g. HEIC) is marked **Unsupported**.
- **Stickers often give cleaner models:** they're already isolated objects on a transparent background.
- Images are only read. Finished models are also written to the `meshes` collection (see below).

For other schemas, define your own sources with `MONGO_SOURCES_JSON` (see `.env.example`).

## Dummy model (no credits)

Tick **Dummy model** above the Generate button (on by default) to prototype without calling Meshy. Each "generation" takes ~8 seconds and returns a bundled sample model (`assets/dummy.glb`, a coffee mug), so the whole flow (progress, gallery, viewer, MongoDB) behaves like a real run. Set `MESHY_DUMMY=1` to force it on for everything.

Dummy results stay selectable in the MongoDB tab, so you can run the real conversion later (double-click a dummy to view it).

## Saving models to MongoDB

When a real model finishes, the server writes it into the Scrapp database **the same way the Scrapp backend does**, so it shows up in the app:

- GLB → GridFS bucket `media`, `filename: "model.glb"`, `metadata: { content_type: "model/gltf-binary", owner_id, kind: "mesh" }`
- Thumbnail → same bucket, `kind: "mesh_thumb"`
- A `meshes` document:

```js
{ owner_id, source: "sticker" | "capture" | "upload", sticker_id | capture_id, prompt: <name>,
  meshy_task_id, stage: "image", status: "SUCCEEDED", progress: 100,
  glb_file_id, thumb_file_id, created_at, created_via: "web-app" }
```

- `owner_id` is copied from the source sticker/capture. Uploads use `MONGO_OWNER_ID` (otherwise `null`, and the Scrapp app won't list them).
- The gallery shows **saved to DB**. If saving fails, a ↻ button retries it (`POST /api/tasks/:id/save`).
- **Dummy models are not saved** unless `MONGO_SAVE_DUMMIES=1` (then they're flagged `dummy: true`).
- Models already in `meshes` (made here or by the Scrapp app) show a **3D ✓ DB** badge in the MongoDB tab. Click one to view it. The server won't spend credits regenerating an image that already has one.

## Scenes: several models at once

The viewer is a scene that can hold any number of models.

- **Click** a model (in Your models, or in the MongoDB tab) to show it **on its own**.
- **+** next to a model **adds** it to the current scene, placed to the right of what's there. Toolbar **+ Mug** adds the sample mug, and **Clear** empties the scene.
- **Click a model in the viewer** to select it. Then use the bar at the bottom: **Move** (W), **Rotate** (E), **Scale** (R), **Floor** (drop it onto the ground), **Copy** (duplicate), **✕** (remove, or press Delete). Esc deselects.
- **⬇ GLB** downloads a single untouched model as its original file. Otherwise it exports the **whole scene as one `scene.glb`**, which loads in three.js like any other GLB.
- The scene layout is remembered in the browser and restored on the next visit. Every model is normalised to 1 unit (its largest side) when added.
- Head-tracked view works on the whole scene and fits it inside the window.

### Cut stickers (SAM 3)

Cut objects out of a photo into stickers with **the same SAM 3 model and die-cut as the Scrapp app**. The web app doesn't run the model itself. It asks the Scrapp backend, which already has SAM 3 loaded on its GPU, through a small key-protected bridge (`backend/app/routers/webapp.py`). That bridge reuses `get_segmenter()`, `rank_candidates`, `make_sticker` and `_store_sticker`, so stickers made here are identical to the app's: white-outlined PNG, mask, `bbox`/`crop_box`, the same fields in `stickers`, and `source: "web"`.

- **Where:** hover a photo in **Scrap › Recent captures** and click ✂. Or drop a photo in **Make it 3D** and click **Cut stickers**: the photo is saved as a capture first, owned by the "acting as" user, like the app does.
- **In the cutter:** SAM 3 finds objects automatically, ranked like the app's auto-stickers with the best one pre-picked. Type a word ("cup") and click **Find** to use SAM 3's text prompt. **Tap anywhere** to cut the object under your tap (the app's tap-to-cut). Tap an outline to pick or unpick it, then click **Make stickers**. New stickers land in the Sticker Book, and **2D** drops one into the scene.
- **Setup:** pick a random key and set it in both places, then restart both servers:
  - `backend/.env`: `WEBAPP_KEY=<key>` (the backend must be running SAM 3: `SEGMENTER=sam3`)
  - `web-app/.env`: `SCRAPP_WEBAPP_KEY=<key>` and `SCRAPP_API_URL=http://<backend-host>:8000`
- The first cut after the backend starts loads SAM 3, which can take a minute.

### 2D stickers

Hover any image in the MongoDB tab (Stickers or Captures) and click **2D** to drop the image itself into the scene as a flat cut-out card. Transparent areas are cut away, and shadows follow the sticker's shape. Stickers move, rotate, scale, copy and export like models. **◉ Face me** in the selection bar makes a sticker always turn toward the viewer, which works nicely with the head-tracked view. In the exported GLB, stickers are textured planes with an alpha mask.

### Saving a scene to Scrapp collages

**💾 Collage** in the toolbar saves the current scene to the `collages` collection, in the same format the Scrapp app's editor uses, so it opens there.

- Items become `{ kind: "sticker" | "mesh", ref_id, position, quaternion, scale }` entries. Sizes are converted to Scrapp's conventions: meshes 0.5 units, stickers 0.45 units tall, one uniform scale.
- Only things that exist in MongoDB can be referenced: **2D stickers from the Stickers source** and **models in `meshes`**. These come from the 3D models (meshes) list, from **3D ✓ DB** badges, or from finished models saved to the DB. The sample mug, dummies and captures are left out, and the dialog lists anything skipped.
- A PNG of the current view is stored as the collage thumbnail (GridFS, `kind: "collage_render"`).
- The save zone wraps the saved items. The camera is the current orbit view.
- After the first save, the dialog offers to **update that collage** instead of creating a new one.
- `owner_id` comes from `MONGO_OWNER_ID` if set, otherwise from the owner of the first sticker or model in the scene.

### Existing models from MongoDB

In the MongoDB tab, choose **3D models (meshes)** to browse every finished model in the `meshes` collection, whether made by the Scrapp app or this web app. Models are newest first, named by their prompt or sticker title. Click one to view it, or **+** to add it to the scene. Dummy models are hidden (`/api/mongo/meshes?dummies=1` includes them).

## Head-tracked view (off-axis projection)

Click **👤 Head** in the viewer toolbar. The canvas becomes a window into a 3D room. The webcam finds your eyes (MediaPipe face detection, in the browser), and the camera uses an **asymmetric (off-axis) frustum** from your eye position through the canvas rectangle. Move your head and the model shifts like a real object behind glass.

- **How distance works:** eyes are ~6.3 cm apart, so the pixel gap between them gives your distance from the camera. No depth camera is needed.
- **Calibration** (in the panel, saved per browser): set **Screen width** to your display's physical width (14" MacBook Pro ≈ 30.4 cm, 16" ≈ 34.5 cm). **Webcam FOV** ≈ 60° for most laptops. **Strength** exaggerates the motion. **Pop-out** moves the model toward or through the glass.
- **Mouse mode** simulates your head with the pointer (scroll = distance). It's used automatically if there's no webcam.
- Drag to spin the model. **Rotate** auto-spins it.
- Close one eye for the strongest effect. The browser window should be roughly where it is on screen: the window's position is used to work out where the canvas physically sits.
- The face model (~230 KB) is downloaded from Google once, then cached in `assets/`.

## Viewer

Orbit (drag), zoom (scroll), pan (right-drag), plus auto-rotate, wireframe, background toggle, camera reset, GLB download, and a ready-to-paste three.js snippet (`{ } Code`). If a model has animations, the first one plays automatically.

## Generation options (sidebar → "Generation options")

| Option | Default | Notes |
|---|---|---|
| AI model | `latest` | `meshy-6-lite` is cheaper |
| Target polycount | 30,000 | Lower it (5–15k) for web/mobile scenes |
| Topology | triangle | Triangles are what the GPU renders anyway |
| Remesh | on | Needed for polycount/topology to apply |
| Textures / PBR | on / on | PBR adds metal/roughness/normal maps |
| Texture prompt | — | e.g. "matte black plastic" |

## API (local server)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/generate` | `{ image: dataURI, name, options }` → creates a Meshy task |
| POST | `/api/generate` | `{ mongo: { source, docId }, options }` → converts a MongoDB image |
| GET | `/api/mongo/images?source=&page=&limit=` | List images in a MongoDB source |
| POST | `/api/cut/start` · `/api/cut/segment` · `/api/cut/point` · `/api/cut/stickers` | Sticker cutter (proxied to the backend's SAM 3 `/webapp` bridge) |
| POST | `/api/collages` | `{ title, scene, thumbnail, collageId? }` → saves / updates a Scrapp collage |
| GET | `/api/mongo/meshes?page=&limit=` | List finished 3D models in the `meshes` collection |
| GET | `/api/mongo/file/:fileId` | Stream a file (image or GLB) from GridFS |
| GET | `/api/users` | Scrapp users (for "acting as") |
| GET | `/api/collages?owner=` / `/api/collages/:id` | List collages / a collage with sticker & model URLs |
| GET | `/api/friends?me=` · POST `/api/friends/request` · POST `/api/friends/:id/accept` | Friends (same rules as the backend) |
| GET | `/api/inbox?me=` | Stickers, models and collages shared with you (hunts excluded) |
| GET | `/api/tasks` | List saved tasks |
| GET | `/api/tasks/:id` | Refresh status (downloads the GLB when done) |
| DELETE | `/api/tasks/:id` | Remove from the local gallery |

## Tips for good results

- One object, centered, plain background, good even lighting.
- A 3/4 view shows more of the shape than a straight-on photo.
- Avoid transparent or very reflective objects.

## Files

```
server.js          Express backend + Meshy proxy
public/index.html  UI
public/app.js      three.js viewer, upload, polling, off-axis projection
public/headtrack.js webcam face tracking → eye position in cm
assets/dummy.glb   sample model for dummy mode
public/style.css   Styles
data/              Created at runtime: tasks.json, inputs/, models/
```

# Meshy 3D Studio

Drop in a JPEG → Meshy AI turns it into a textured 3D model → view it in an interactive three.js viewer → download a GLB that drops straight into any three.js project.

## Setup

Requires Node 20.6+.

```bash
npm install
cp .env.example .env        # then paste your Meshy API key into .env
npm start                   # http://localhost:3000
```

Get an API key at https://www.meshy.ai/settings/api (API access needs a paid Meshy plan; each generation costs credits).

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
- The app only **reads** from MongoDB. Results are saved locally in `data/`.

For other schemas, define your own sources with `MONGO_SOURCES_JSON` (see `.env.example`).

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
| GET | `/api/mongo/file/:fileId` | Stream an image from GridFS |
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
public/app.js      three.js viewer, upload, polling
public/style.css   Styles
data/              Created at runtime: tasks.json, inputs/, models/
```

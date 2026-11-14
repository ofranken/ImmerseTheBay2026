# Scrapp

An AR scrapbook for Meta AI glasses. Say **"scrapbook that"** (or press the capture button) and Scrapp photographs what you're looking at, keeps the original and its location, and cuts the most central objects into die-cut stickers with SAM. Collage stickers and AI-generated 3D models in space, send stickers that stick to real things ("hold up an apple"), and turn your favourite places into scavenger hunts your friends play with their own glasses.

| Folder | What's inside |
|---|---|
| `app/` | Flutter app (Dart): screens, state, uploads, paper + fuzzy UI |
| `app/android/.../glasses/` | Kotlin: Meta Wearables DAT 1.0.1 session, voice, capture button, outbox, foreground service |
| `app/android/.../ar/` | Kotlin: ARCore/SceneView AR view, MediaPipe "hold up an apple" detection |
| `app/assets/web/` | three.js 3D collage editor; the same page is the public web viewer |
| `backend/` | FastAPI + MongoDB/GridFS + SAM 2.1 segmentation, hunt matching, Meshy proxy |
| `docs/ARCHITECTURE.md` | How every piece works and why: glasses data, voice, segmentation, anchoring, Android vs iOS |
| `docs/SETUP.md` | Setup from zero, first run, troubleshooting |
| `tools/make_textures.py` | Regenerates the paper-grain and fuzzy-grass textures |

## Quick start

```bash
# backend
cd backend && cp .env.example .env && pip install -r requirements.txt
SEGMENTER=grabcut uvicorn app.main:app --host 0.0.0.0 --port 8000   # GPU box: install SAM per docs/SETUP.md

# app (Android phone plugged in)
cd app && bash tool/bootstrap.sh
flutter run --dart-define=API_BASE=http://<your-LAN-IP>:8000
```

## Design

**Palette** (two references combined):

| Colour | Hex | Use |
|---|---|---|
| Chocolate | `#5C3A26` | Ink: all text |
| Vintage brown | `#694A47` | Secondary text |
| Warm cream | `#F1E7D3` | Page background |
| Vintage cream | `#FFF0DE` | Cards |
| Dusty teal | `#96C1C5` | Actions, AR, sharing |
| Soft sage | `#A3B18A` | 3D/mesh, success |

**Look:**

- Paper-grain texture with soft neumorphic cards.
- Anton for big section titles, Nunito for body text, Yellowtail for the wordmark.
- Everything tied to 3D generation (Meshy) uses a plush **fuzzy grass** texture with fuzzy strand edges.

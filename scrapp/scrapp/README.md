# Scrapp

An AR scrapbook for Meta AI glasses. Say **"scrap that"** (or press the capture button) and Scrapp photographs what you're looking at, keeps the original and its location, and cuts the most central objects into die-cut stickers with SAM. Collage stickers and AI-generated 3D models in space, send stickers that stick to real things ("hold up an apple"), and turn your favourite places into scavenger hunts your friends play with their own glasses.

| Folder | What's inside |
|---|---|
| `app/` | Flutter app (Dart): screens, state, uploads, paper + fuzzy UI |
| `app/android/.../glasses/` | Kotlin: Meta Wearables DAT 1.0.1 session, voice, capture button, outbox, foreground service |
| `app/android/.../ar/` | Kotlin: ARCore/SceneView AR view, MediaPipe "hold up an apple" detection |
| `app/assets/web/` | three.js 3D collage editor; the same page is the public web viewer |
| `backend/` | FastAPI + MongoDB/GridFS + SAM 3 segmentation, hunt matching, Meshy proxy |
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

## Credits

Segmentation is powered by **SAM 3 (Segment Anything Model 3)** from Meta.

- Code: https://github.com/facebookresearch/sam3
- Official weights: https://huggingface.co/facebook/sam3 (gated; request access with a Hugging Face account)
- Licensed under the [SAM License](https://github.com/facebookresearch/sam3/blob/main/LICENSE). Its terms apply to everyone who uses the weights.

Scrapp does not redistribute the weights; `backend/checkpoints/` is gitignored.

> **Temporary:** until our access to `facebook/sam3` is approved, development uses an unofficial community
> re-upload of the same `sam3.pt` (https://huggingface.co/1038lab/sam3), downloaded locally. It is not Meta's
> release and its contents are unverified against Meta's. Switch to the official weights before shipping by
> clearing `SAM3_CHECKPOINT` in `backend/.env` (the server then downloads `facebook/sam3` automatically),
> and delete `backend/checkpoints/sam3.pt`.

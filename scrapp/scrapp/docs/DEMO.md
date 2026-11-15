# Immerse The Bay: demo script

Two demo accounts on the shared server (`https://scrapp.nmagic.dev`), already friends with each other:

| Account | Username / email / password | Role in the demo |
|---|---|---|
| Demo 1 | `11111111` / `11111111@gmail.com` / `11111111` | The presenter. Owns the **Poster Hunt (demo)**, a 3D teddy bear and a published collage |
| Demo 2 | `22222222` / `22222222@gmail.com` / `22222222` | The friend. Receives the hunt; plays it with the glasses |

New sign-ups need the invite code from `backend/.env` (`INVITE_CODE`). The demo accounts already exist.

## Before you go on stage (10 minutes)

1. Laptop awake, plugged in, **Mullvad off** (it blocks the tunnel). Check `https://scrapp.nmagic.dev/health` returns `{"ok":true}`.
   The API, tunnel and studio start at boot; `journalctl --user -u scrapp-health` shows what the health check did.
2. Phone: install the APK (`app/build/app/outputs/flutter-apk/app-debug.apk`), sign in as `11111111`, allow camera, location and microphone.
3. Glasses: pair in Meta AI, then in Scrapp tap **Link glasses** and **Start scrapbooking**.
4. **Print the three posters** in `docs/demo_assets/` (`poster-bay-bridge.png`, `poster-golden-hour.png`, `poster-fog-city.png`), A4 or larger,
   matte paper, and tape them at eye height with good light. They are the targets of the hunt, so they must be these exact images.
5. Sign in on a second phone as `22222222` if you want to show the receiving side (the hunt is already in its inbox).
6. Re-run `backend/.venv/bin/python backend/scripts/seed_demo.py` if anything looks empty. It never deletes anything and skips what exists.

## The script (about 6 minutes)

1. **Capture (1 min).** Wearing the glasses, look at an object and say **"scrapbook that"**. The glasses say "Scrapbooking"; seconds later the
   cut-out sticker appears under *Recent captures* and in the **Book**. Say **"scrapbook that lamp"** to name it.
2. **The Book (30 s).** Open **Book**: it shows starred stickers; flip **Starred / All**, star one, delete one. Tap a sticker, then
   **See it in AR** to drop it on a table.
3. **3D (1 min).** Open the **teddy bear** sticker, **View the 3D model** (already built; making a new one takes about 45 seconds and 15 Meshy credits).
   Orbit it. In **Studio, 3D**, grow something new from text if you want a live wait; a "ready in 3D" message appears when it finishes.
4. **Collage (1 min).** **Studio, Collages, Demo collage**: stickers and the 3D bear in one scene. Change the **Background**, save, then open its
   public link on a laptop (a link is shown on the Share action; also `backend/scripts/seed_demo.py` prints them).
5. **Friends (30 s).** On the second phone (`22222222`) open **Friends**: the hunt and a shared item are in the inbox. Send the bear model to
   the other account from the 3D preview's send button.
6. **Scavenger hunt (2 min).** As `22222222` open **Hunts, Poster Hunt (demo)** and tap **Hunt with my glasses**. Walk to a printed poster, point
   the glasses at it and say **"found it"**: the glasses say "Checking", then "Found Bay Bridge. 1 of 3." Find all three for "Hunt complete".
   Back on `11111111`, open the hunt: the owner sees the friend's progress under *Players*.

## If something goes wrong

| Symptom | Fix |
|---|---|
| App says it can't reach Scrapp | Tunnel down or Mullvad on: `systemctl --user status scrapp-tunnel`, turn Mullvad off. The app retries by itself and the Book shows a banner |
| Stickers take long | The first photo after a restart loads SAM 3 (about 10 s); after that a photo takes about 15 s. `scrapp-api` logs: `journalctl --user -u scrapp-api -f` |
| A poster doesn't match | More light, fill the frame, hold still; matching needs the poster, not a photo of the screen. The "Find with phone camera" button on the hunt is the backup (ARCore) |
| "found it" is not heard | Say "scrapbook that" instead (it checks the hunt too), or press the capture button on the glasses |
| Glasses won't connect | Use **Photo** on the Scrap tab (phone camera/gallery): it runs the same pipeline and checks the active hunt |
| Hunt says too far away | The seeded hunt allows 30 km around Stanford; if you are elsewhere, re-seed with a different `LAT, LNG` or use "Find with phone camera" |

## What the seed script made

`backend/scripts/seed_demo.py` (idempotent) creates, through the real API and SAM pipeline:

- Four real-object stickers per account (starred) from CC BY photos, titled `Demo <thing>`.
- Three flat, textured posters (generated art with large text, which SIFT matches well) and a sticker for each, owned by `11111111`.
- One finished 3D model for `11111111` (a teddy bear, Meshy image-to-3D). `22222222` keeps the 3D model it already had.
- A published `Demo collage` for each account with a rendered thumbnail.
- `Poster Hunt (demo)`, owned by `11111111`, shared with `22222222`, 30 km radius.
- A proof run: each poster is re-photographed at an angle, with different lighting and blur, as `22222222` against a throwaway copy of the
  hunt, and must match. The real hunt stays at 0 of 3.

## Photo credits (CC BY, from COCO 2017 via Flickr)

Banana [flickr](http://farm5.staticflickr.com/4049/4208826429_3432119060_z.jpg), clock [flickr](http://farm9.staticflickr.com/8442/7997145503_9c5e040b00_z.jpg),
teddy bear [flickr](http://farm3.staticflickr.com/2457/3790889558_3d54eae6fb_z.jpg), cake [flickr](http://farm6.staticflickr.com/5327/8834178988_33ecf210db_z.jpg),
suitcase [flickr](http://farm1.staticflickr.com/38/81948760_02d1403c1f_z.jpg), toaster [flickr](http://farm7.staticflickr.com/6012/5926562644_dbbbe9fc2a_z.jpg),
bowl [flickr](http://farm4.staticflickr.com/3753/9165139551_307fa8f59d_z.jpg), umbrella [flickr](http://farm9.staticflickr.com/8454/7897786544_4e902801e3_z.jpg).
Licensed CC BY 2.0 by their Flickr authors (see `backend/tests/data/manifest.json`); the posters are generated by the seed script.

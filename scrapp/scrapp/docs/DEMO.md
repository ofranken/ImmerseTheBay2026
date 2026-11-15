# Immerse The Bay: demo script

Two demo accounts on the shared server (`https://scrapp.nmagic.dev`), already friends with each other:

| Account | Username / email / password | Role in the demo |
|---|---|---|
| Demo 1 | `11111111` / `11111111@gmail.com` / `11111111` | The presenter. Owns the **Screen Hunt (demo)**, a 3D teddy bear and a published collage |
| Demo 2 | `22222222` / `22222222@gmail.com` / `22222222` | The friend. Receives the hunt; plays it with the glasses |

New sign-ups need the invite code from `backend/.env` (`INVITE_CODE`). The demo accounts already exist.

## Before you go on stage (10 minutes)

1. Laptop awake, plugged in, **Mullvad off** (it blocks the tunnel). Check `https://scrapp.nmagic.dev/health` returns `{"ok":true}`.
   The API, tunnel and studio start at boot; `journalctl --user -u scrapp-health` shows what the health check did.
2. Phone: install the APK (`app/build/app/outputs/flutter-apk/app-debug.apk`), sign in as `11111111`, allow camera, location and microphone.
3. Glasses: pair in Meta AI, then in Scrapp tap **Link glasses** and **Start scrapbooking**.
4. **Open the hunt targets on a screen (no printing).** On a laptop, tablet or second phone open `docs/demo_assets/hunt-targets.html` in a browser,
   press **F** for full-screen, and click or press Space to cycle the three pictures (Bay Bridge, Golden Hour, Fog City). They must be these
   exact images: they are what the hunt looks for. Turn the screen brightness to maximum, keep lamps and windows from reflecting on the glass, and
   do not use night-mode or colour filters. A laptop on a table at about arm's length works best.
5. Sign in on a second phone as `22222222` if you want to show the receiving side (the hunt is already in its inbox).
6. Re-run `backend/.venv/bin/python backend/scripts/seed_demo.py` if anything looks empty. It skips what exists and only ever removes its own earlier hunt
   (the old "Poster Hunt (demo)", replaced by "Screen Hunt (demo)").

## The script (about 6 minutes)

1. **Capture (1 min).** Wearing the glasses, look at an object and say **"scrapbook that"**. The glasses say "Scrapbooking"; seconds later the
   cut-out sticker appears under *Recent captures* and in the **Book**. Say **"scrapbook that lamp"** to name it.
2. **The Book (30 s).** Open **Book**: it shows starred stickers; flip **Starred / All**, star one, delete one. Tap a sticker, then
   **See it in AR** to drop it on a table.
3. **3D (1 min).** Open the **teddy bear** sticker, **View the 3D model** (already built; making a new one takes about 45 seconds and 15 Meshy credits).
   Orbit it. In **Studio, 3D**, grow something new from text if you want a live wait; a "ready in 3D" message appears when it finishes.
4. **Collage (1 min).** **Studio, Collages, Demo collage** (tap **3D** on its card for the cinematic 3D view, drag or tilt the phone; **Link** shows a QR code that opens the same view in a browser, with **View in AR** on Android): stickers and the 3D bear in one scene. Change the **Background**, save, then open its
   public link on a laptop (a link is shown on the Share action; also `backend/scripts/seed_demo.py` prints them).
5. **Friends (30 s).** On the second phone (`22222222`) open **Friends**: the hunt and a shared item are in the inbox. Send the bear model to
   the other account from the 3D preview's send button.
6. **Scavenger hunt (2 min).** As `22222222` open **Hunts, Screen Hunt (demo)** and tap **Hunt with my glasses**. Point the glasses at the laptop
   screen showing a picture (fill the view with it) and say **"found it"**: the glasses say "Checking", then "Found Bay Bridge. 1 of 3." Press Space on
   the laptop for the next picture; find all three for "Hunt complete".
   Back on `11111111`, open the hunt: the owner sees the friend's progress under *Players*.

## If something goes wrong

| Symptom | Fix |
|---|---|
| App says it can't reach Scrapp | Tunnel down or Mullvad on: `systemctl --user status scrapp-tunnel`, turn Mullvad off. The app retries by itself and the Book shows a banner |
| Stickers take long | The first photo after a restart loads SAM 3 (about 10 s); after that a photo takes about 15 s. `scrapp-api` logs: `journalctl --user -u scrapp-api -f` |
| A picture doesn't match | Fill most of the view with the screen, hold still for a second, raise the screen brightness, remove reflections (angle the laptop away from lamps or windows). A little tilt is fine. The "Find with phone camera" button on the hunt is the backup (ARCore) |
| Stripey bands (moire) on the screen | Move a little closer or further away, or tilt the screen a few degrees; it is normal and matching tolerates it |
| "found it" is not heard | Say "scrapbook that" instead (it checks the hunt too), or press the capture button on the glasses |
| Glasses won't connect | Use **Photo** on the Scrap tab (phone camera/gallery): it runs the same pipeline and checks the active hunt |
| Hunt says too far away | The seeded hunt allows 30 km around Stanford; if you are elsewhere, re-seed with a different `LAT, LNG` or use "Find with phone camera" |

## Sticker maker page (for the demo video)

`https://scrapp.nmagic.dev/supersecret`: drop a photo, click the thing you want (right-click or Shift-click removes a bit) or switch to
"Or describe it" and type e.g. "red mug", pick the best cut, press Download PNG. The PNG is exactly the app's sticker (same white die-cut edge, see-through
background). It needs the laptop on, the tunnel up and Mullvad off, like everything else. The page is not linked anywhere and not indexed; the URL is the only gate.

## What the seed script made

`backend/scripts/seed_demo.py` (idempotent) creates, through the real API and SAM pipeline:

- Four real-object stickers per account (starred) from CC BY photos, titled `Demo <thing>`.
- Three flat, textured pictures (generated art with large text, which SIFT matches well) and a sticker for each, owned by `11111111`. They are shown
  full-screen from `docs/demo_assets/hunt-targets.html`; the PNGs are there too.
- One finished 3D model for `11111111` (a teddy bear, Meshy image-to-3D). `22222222` keeps the 3D model it already had.
- A published `Demo collage` for each account with a rendered thumbnail.
- `Screen Hunt (demo)`, owned by `11111111`, shared with `22222222`, 30 km radius.
- A proof run: each picture is photographed on a *simulated* laptop screen (RGB sub-pixel structure, glare, moire from sampling, dim light with noise,
  distance, tilt) as `22222222` against throwaway copies of the hunt. All 15 attempts (3 pictures x 5 conditions) matched with SIFT, 187 to 478
  inliers against a threshold of 25. The real hunt stays at 0 of 3. This is a simulation, not a real camera: do one real run-through with the
  glasses and the actual screen before the event.

## Hunting without a screen: real flat things at the venue

If you want to hunt real objects (a book cover, a laptop sticker, a sign, a poster on a wall), make the hunt in the app: scrapbook the thing
("scrapbook that"), open **Hunts, Create a hunt**, tick the stickers and send it. Matching works best on **flat, high-contrast, textured** things
(covers, stickers with logos or text, signage, posters). Plain or shiny 3D objects (a mug, a plant) match poorly with SIFT; the optional DINOv2
fallback helps a little but its thresholds are untuned on real photos.

## Photo credits (CC BY, from COCO 2017 via Flickr)

Banana [flickr](http://farm5.staticflickr.com/4049/4208826429_3432119060_z.jpg), clock [flickr](http://farm9.staticflickr.com/8442/7997145503_9c5e040b00_z.jpg),
teddy bear [flickr](http://farm3.staticflickr.com/2457/3790889558_3d54eae6fb_z.jpg), cake [flickr](http://farm6.staticflickr.com/5327/8834178988_33ecf210db_z.jpg),
suitcase [flickr](http://farm1.staticflickr.com/38/81948760_02d1403c1f_z.jpg), toaster [flickr](http://farm7.staticflickr.com/6012/5926562644_dbbbe9fc2a_z.jpg),
bowl [flickr](http://farm4.staticflickr.com/3753/9165139551_307fa8f59d_z.jpg), umbrella [flickr](http://farm9.staticflickr.com/8454/7897786544_4e902801e3_z.jpg).
Licensed CC BY 2.0 by their Flickr authors (see `backend/tests/data/manifest.json`); the posters are generated by the seed script.

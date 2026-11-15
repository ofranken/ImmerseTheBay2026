# Scrapp to-do list

Newest priorities first. Move a line to "Done" when it ships.

## Top priority
- [x] **Sticker to 3D** (Meshy image-to-3D). Verified on real Meshy: sticker -> GLB in ~45 s, 15 credits, ~15k
  triangles / 1.5 MB, thumbnail and model stored on our server, double-tap does not bill twice.
  - [x] On-phone flow checked: sticker screen -> "View the 3D model" -> turntable preview -> added to a collage.
  - [x] 3D preview: model enlarged to fill the pedestal, four-way lighting so black objects read (checked in a headless render, not yet on the phone).
  - [ ] Warn or block when a sticker is not a coherent object (floor, window and wall fragments make bad models).
  - [ ] Optional "better quality" button that re-runs a hero sticker with `MESHY_AI_MODEL=latest` (~2x credits).
  - [x] Model-finished notice: a floating message with a "View" button and a buzz, on whatever screen is open. In-app only: polling stops when the app is in the background, so a system notification would need server push (FCM).

## Next
- [ ] Try "View in AR" on a real Android phone (Scene Viewer launch, size, orientation) and the tilt feel on a real phone; iOS Quick Look would need USDZ export.
- [ ] **Friends sharing: check on a device.** Backend (8 HTTP tests) and app state logic (7 Dart tests) are covered. Still to try by hand on two phones/accounts: the Friends tab, the sticker share sheet, sending a 3D model (new button on the 3D preview) and opening it from the inbox.
- [ ] **Background job system** (reading (b) of the old "Background system" item): a server-side queue/worker so captures,
  sticker cutting and 3D jobs keep running and retry on their own, and the app is told when they finish.
  (Collage backdrops, reading (a), shipped: see Done.)
- [ ] Confirm Meta's Developer Center approval for the "scrap that" / "found it" voice commands on real glasses.
- [ ] **Tap-to-cut: make the whole-object fix fast.** Measured on the COCO eval set (`python -m tests.tapcut_study --concepts`), preferring a whole-object concept mask over the tapped part lifts the hit rate from 59% to 76% (dev) and 82% (holdout). It is built (`choose_whole_object`, `TAP_WHOLE_OBJECT=1`) but OFF by default because it adds ~8 s per tap (70-noun vocabulary). Using only the first 36 nouns plus centre points costs ~5 s with the same gain; centre points alone cost ~0.7 s and are unmeasured. Next: measure centre-point-only and tap-centred points, then enable.
- [ ] App: retry the first library load if the network was down at startup (empty Sticker Book until restart).

## Scavenger hunt (built; hardened, see Done)
- [ ] Verify hunt matching on real glasses and ARCore. SIFT handles flat, textured targets (posters, paintings, signs). A DINOv2
  appearance fallback now covers non-flat objects (`services/embedding_match.py`), but its thresholds were calibrated on pasted-object
  tests only (7/17 true, 0/17 false); tune them with real glasses photos.
- [ ] Tune the DINOv2 hunt matcher (`EMBED_*` in `config.py`) on real glasses photos; thresholds were calibrated on synthetic composites only (strict on purpose: a wrong tick-off is worse than a miss).
- [ ] Hunt map view, per-item radius/title editing, leaderboard.

## Security and housekeeping
- [ ] Rotate the Atlas password (it was pasted into chat). The Meshy key was rotated and verified.
- [ ] Re-run the SAM 3 evaluation with the official `facebook/sam3` weights once access is approved (currently a
  community mirror).
- [ ] Evaluate on real glasses photos (the test set is COCO).

## Done
- [x] **Web studio (Sid's web-app) signs in with Scrapp accounts** (same JWT as the phone app; no shared password), everything per user, sign-in throttled, logout revokes the cookie. Static files are `no-store` with content-hashed URLs: Cloudflare was rewriting their cache header to 4 h, which kept an old studio's CSS/JS alive in browsers (unstyled page). Tunnel routing example in `deploy/cloudflared/ingress.example.yml`. Cut stickers is switched on (`WEBAPP_KEY` / `SCRAPP_WEBAPP_KEY`). Tests: `web-app/test/auth.e2e.mjs`.
- [x] **Collages in 3D** (public link and in the app): the viewer opens in **Drift** (slow eased orbit and dolly), switches to **Free** the moment you drag, and **Tilt**
  gives window parallax from phone motion (iOS asks permission via a "Tilt to look around" button) or the mouse; stickers get soft depth shadows and the camera
  fits narrow phone screens. In the app: **View in 3D** on each Studio collage card and in the editor toolbar (`CollageViewScreen`).
- [x] **One-tap share link**: "Link" on a Studio card, in the editor toolbar and in the 3D view opens a sheet with the link, a QR code (`/c/<token>/qr.png`), Copy and Share.
  The public page has Open Graph tags (title and picture) so link previews look right. Browser **View in AR** (Android, Scene Viewer via `model-viewer`): saving a collage in the
  app now also exports the whole scene as one GLB (about 0.8 m wide) and uploads it as `scene_glb`; the button shows only when that exists and the device can do AR.
  GLB validated with the Khronos validator (0 errors, 0 warnings). Not yet tried on a real phone: launching Scene Viewer. Existing collages get the AR button the next time
  they are saved from the app (the two Demo collages already have it). iPhones get drift/tilt but no AR button (Quick Look needs a USDZ file).
- [x] **Sticker maker page at `/supersecret`** (for the demo video): upload or drop a photo, click the object (right-click or Shift to remove a bit) or describe it ("red mug"), pick among the cuts, add more objects, download a PNG. No login: the URL is the gate, so it is rate limited per IP (uploads 10 per 5 min, cuts 60 per min, downloads 40 per min), capped at 12 MB / 50 MP per photo, keeps at most 6 photos in memory for an hour, and runs one GPU job at a time on the app's already-loaded SAM 3 (no second model). The exported PNG is made by the same `make_sticker` call as the app's stickers and is byte-identical to the app's sticker for the same photo and cut (verified through the public URL). Code: `backend/app/routers/supersecret.py`, `backend/app/static/supersecret.html`, tests in `backend/tests/test_supersecret.py`.
- [x] Demo content seeded (`backend/scripts/seed_demo.py`, idempotent) and the demo script written (`docs/DEMO.md`): both accounts have starred real-object stickers, a published collage with a rendered thumbnail and a finished 3D model; `Screen Hunt (demo)` (3 flat textured pictures shown full-screen from `docs/demo_assets/hunt-targets.html`, no printing) is shared 11111111 -> 22222222 and matched on all 15 simulated screen photos (glare, moire, dim, far; 187-478 SIFT inliers). Still to do: one real run-through with the glasses and a real screen.
- [x] Hunts: optional DINOv2-small appearance matcher as a fallback when SIFT misses; collage backgrounds (colour, paper, gradient, photo) in the editor, exports and the public viewer.
- [x] Glasses capture recovery: a timed-out photo (Meta AI link stall, `DAT:HeartbeatMonitor: Heartbeat timeout`) now resets the camera stream and retries once, instead of reusing the dead stream until the app restarts.
- [x] Collage backgrounds: colour, paper, gradient presets (sky, sunset, mint, night, dawn) or one of your photos, chosen from a Background
  button in the collage editor, saved in `scene.background`, shown in the editor, in saved PNGs and in the public web viewer.
  Tests: `backend/tests/test_collage_background.py`, `app/test/collage_background_test.dart`.
- [x] Friends sharing review: sending a 3D model now works end to end (share button on the preview, opens from the inbox); a repeat
  share updates the friend's existing inbox entry instead of duplicating it; asking an existing friend says "accepted", not
  "Request sent"; unfinished 3D models can't be shared; Accept/open failures now show a message instead of failing silently; a hunt
  opens straight from the inbox card. Tests: `backend/tests/test_social.py`, `app/test/social_test.dart`.
- [x] Health check: `scrapp-health.timer` runs `backend/scripts/healthcheck.sh` every minute and restarts the API, studio or
  tunnel after two failed checks in a row (catches hangs that `Restart=always` can't). Verified by freezing the studio
  process. Unit files are in `deploy/systemd/` (copy to `~/.config/systemd/user/`, then `systemctl --user enable --now
  scrapp-health.timer`). Log: `journalctl --user -u scrapp-health`. It warns when Mullvad is connected.
- [x] Sign-ups need an invite code (`INVITE_CODE` in `backend/.env`; empty = open). The sign-up form has an Invite code field.
- [x] Book shows starred stickers by default with an All toggle; star, unstar and delete from the grid; logout on the home header.
- [x] Database moved to Olivia's MongoDB Atlas; demo accounts 11111111 and 22222222 created there.
- [x] Meshy key rotated; the old key returns 401 and the new one authenticates.
- [x] "Found it" voice command: during a hunt it takes a photo and checks it against the remaining finds (speaks "Checking",
  then the result). Outside a hunt it does nothing, so ordinary chatter never triggers a photo. "got it" was dropped from the
  phrases for that reason. Unit-tested in `VoiceCommandMatcherTest`; not yet tried on real glasses.
- [x] Server no longer freezes while cutting stickers: SAM 3 loads in a worker thread at startup and all image work runs
  off the event loop, one capture at a time (a photo to 4 stickers in about 15 s while `/health` stays instant).
- [x] API, Cloudflare tunnel and web studio run as systemd user services (`scrapp-api`, `scrapp-tunnel`,
  `scrapp-studio`; linger is on), so they start at boot and restart if they crash. Mullvad must stay off: it blocks the tunnel.
- [x] Web studio needs `STUDIO_PASSWORD` (HTTP Basic); without it requests from the internet are refused. The Meshy key
  was removed from `web-app/.env.example` (it had been committed).
- [x] Scavenger hunt hardening: completion exposed and stamped once, geofenced phone check-off, owner progress view, full hunt data
  in the share inbox, survives deleted stickers, batch lookups, play screen loads/retries, completion banner, owner delete,
  active hunt persisted across restarts, HTTP tests in `backend/tests/test_hunts.py`.
- [x] SAM 3 server-side segmentation with an object vocabulary and tap-to-cut.
- [x] Public access over Cloudflare at https://scrapp.nmagic.dev (tunnel runs on the laptop).
- [x] Meshy integration hardened: current API, spending caps, atomic refine, stored results, delete, clear errors.

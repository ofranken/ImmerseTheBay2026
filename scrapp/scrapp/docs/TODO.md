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
- [ ] **Friends sharing, app side.** The backend is verified on Atlas (request, accept, share, inbox, hunts). Still to check on a device: the Friends tab, share sheets, and sharing 3D models.
- [ ] **Background system** (scope to confirm, two readings):
  - (a) Backgrounds for collages: pick a backdrop or environment behind the 3D collage (colour, paper, photo, sky),
    saved with the collage and used in exports and the web viewer.
  - (b) A background job system: a server-side queue/worker so captures, sticker cutting and 3D jobs keep running
    and retry on their own, and the app is told when they finish.
- [ ] Confirm Meta's Developer Center approval for the "scrapbook that" / "found it" voice commands on real glasses.
- [ ] Tap-to-cut often picks a sub-part (59% hit rate in our test); prefer the whole object.
- [ ] App: retry the first library load if the network was down at startup (empty Sticker Book until restart).

## Scavenger hunt (built; hardened, see Done)
- [ ] Verify on real glasses and ARCore: SIFT matching only suits flat, textured targets (paintings, signs, posters).
  Generic objects (a cup, a plant) need an embedding vote (CLIP/DINO) before they match reliably.
- [ ] Hunt map view, per-item radius/title editing, leaderboard.

## Security and housekeeping
- [ ] Rotate the Atlas password (it was pasted into chat). The Meshy key was rotated and verified.
- [ ] Re-run the SAM 3 evaluation with the official `facebook/sam3` weights once access is approved (currently a
  community mirror).
- [ ] Evaluate on real glasses photos (the test set is COCO).

## Done
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

# Scrapp to-do list

Newest priorities first. Move a line to "Done" when it ships.

## Top priority
- [x] **Sticker to 3D** (Meshy image-to-3D). Verified on real Meshy: sticker -> GLB in ~45 s, 15 credits, ~15k
  triangles / 1.5 MB, thumbnail and model stored on our server, double-tap does not bill twice.
  - [x] On-phone flow checked: sticker screen -> "View the 3D model" -> turntable preview -> added to a collage.
  - [ ] 3D preview looks small and dark for black objects: enlarge the model on the pedestal and brighten the lights.
  - [ ] Warn or block when a sticker is not a coherent object (floor, window and wall fragments make bad models).
  - [ ] Optional "better quality" button that re-runs a hero sticker with `MESHY_AI_MODEL=latest` (~2x credits).
  - [ ] Tell the user when a model finishes (notification) so they don't have to watch the progress bar.

## Next
- [ ] **Background system** (scope to confirm, two readings):
  - (a) Backgrounds for collages: pick a backdrop or environment behind the 3D collage (colour, paper, photo, sky),
    saved with the collage and used in exports and the web viewer.
  - (b) A background job system: a server-side queue/worker so captures, sticker cutting and 3D jobs keep running
    and retry on their own, and the app is told when they finish.
- [ ] Move the database to Olivia's MongoDB Atlas (blocked: Atlas Network Access must allow this machine; then set
  `MONGO_URI` in `backend/.env` and recreate the DaGoat account).
- [ ] Start the server and tunnel automatically (systemd user service) so a reboot doesn't take Scrapp down.
- [ ] Voice command ("scrapbook that"): glasses mic access is granted; confirm Meta's Developer Center approval.
- [ ] Tap-to-cut often picks a sub-part (59% hit rate in our test); prefer the whole object.
- [ ] App: retry the first library load if the network was down at startup (empty Sticker Book until restart).

## Security and housekeeping
- [ ] Rotate secrets that have been pasted into chat or screenshots: the Atlas password and the Meshy key.
- [ ] Sign-ups are open on a public URL and every 3D job spends credits: add a Cloudflare Access policy or an invite
  code before sharing the link widely (per-user 3D caps are already in).
- [ ] Re-run the SAM 3 evaluation with the official `facebook/sam3` weights once access is approved (currently a
  community mirror).
- [ ] Evaluate on real glasses photos (the test set is COCO).

## Done
- [x] SAM 3 server-side segmentation with an object vocabulary and tap-to-cut.
- [x] Public access over Cloudflare at https://scrapp.nmagic.dev (tunnel runs on the laptop).
- [x] Meshy integration hardened: current API, spending caps, atomic refine, stored results, delete, clear errors.

# Setting up Scrapp from zero

Rough time: 1 to 2 hours the first time, most of it installing toolchains and downloading SAM.

## 0. What you need

| Thing | Notes |
|---|---|
| Android phone, Android 12+ | ARCore-supported (check Google's "ARCore supported devices" list) |
| Ray-Ban Meta (or Oakley Meta) glasses | Paired in the **Meta AI** app. Optional at first: you can start with Mock glasses |
| A computer for development | Windows, macOS or Linux |
| A machine with an NVIDIA GPU for SAM | 8 GB+ VRAM for SAM 2.1 Large. Without one, use `SEGMENTER=grabcut` to develop |
| MongoDB | Local Docker, or a free MongoDB Atlas cluster |
| Meshy API key | meshy.ai → API. Only needed for 3D generation |
| Google Cloud key with **ARCore API** enabled | Optional. Only for outdoor geo anchors |

## 1. Backend (FastAPI + MongoDB + SAM)

```bash
cd backend
cp .env.example .env          # then edit it (see below)

# MongoDB, if you don't use Atlas
docker run -d --name scrapp-mongo -p 27017:27017 mongo:7

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**SAM 2.1 on the GPU machine:**

```bash
# 1. PyTorch matching your CUDA version (see pytorch.org), e.g.
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
# 2. SAM 2
pip install -r requirements-gpu.txt
# 3. Checkpoint (~900 MB)
bash scripts/download_sam2.sh
```

**Edit `.env`:**

- `JWT_SECRET`: any long random string
- `PUBLIC_BASE_URL`: the address your **phone** uses to reach this server, e.g. `http://192.168.1.50:8000` (your computer's LAN IP, same Wi-Fi). Signed image links are built from it, so `localhost` won't work on the phone.
- `SEGMENTER=sam2` on the GPU box, or `SEGMENTER=grabcut` on a laptop
- `MESHY_API_KEY=...`

**Run it:**

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://<LAN-IP>:8000/docs` from your phone's browser. If the API docs load, the phone can reach the server.

**Run the tests:**

```bash
pytest -q        # segmentation ranking, sticker die-cut, hunt matching
```

**Or Docker with GPU** (needs the NVIDIA Container Toolkit): `docker compose up --build` in `backend/`.

**Hosting notes**

- A campus HPC batch queue isn't a good fit for an always-on API. Use a lab workstation with a GPU, or a GPU cloud (RunPod, Modal, Lambda).
- For testing outside your Wi-Fi, put a tunnel in front (`cloudflared tunnel --url http://localhost:8000`) and set `PUBLIC_BASE_URL` to the https URL it prints.

## 2. Meta glasses developer setup

1. Install **Meta AI** on the phone and pair your glasses.
2. Turn on **Developer Mode**: Meta AI app → Settings → App Info → tap **App version** five times → turn on Developer Mode.
3. Create a free account at the **Wearables Developer Center** (wearables.developer.meta.com) and create an organization and a project for Scrapp.
4. In the project:
   - Android package: `com.scrapp.app`
   - The SHA-256 of your debug signing key: `cd app/android && ./gradlew signingReport` (after step 3.2 below)
   - URL scheme: `scrapp` (letters only)
   - **Permissions** tab: request Camera, Microphone and Voice Invocation, each with a one-line reason
   - Enable the experimental capabilities Scrapp uses: **Speech**, **Inputs** and **Voice Invocations**
5. Copy the **Application ID** and **Client Token** into `app/android/local.properties`:

```properties
mwdat_application_id=1234567890
mwdat_client_token=abcdef...
arcore_api_key=AIza...          # optional, outdoor geo anchors
```

| Mode | What works |
|---|---|
| Developer Mode, IDs left at `0` | Camera capture via the in-app button. Fastest way to see photos flowing |
| Registered project in a **development/beta** release channel | Voice "scrapbook that", capture button, "Hey Meta, start Scrapp". Meta requires the Developer Center approvals for these experimental features |

**For "Hey Meta, start Scrapp":**

1. Publish a build to the project's **Beta** channel.
2. In Meta AI, open device Settings → Release Channel and pick Beta.
3. Turn Developer Mode off.
4. Keep the glasses connected for about 15 minutes so the app shows up.

## 3. Flutter app

1. Install **Flutter 3.35+** and **Android Studio** (JDK 21 is bundled). Run `flutter doctor` until Android is green.
2. Generate the platform scaffolding and fetch the object-detection model:

   ```bash
   cd app
   bash tool/bootstrap.sh           # Windows: powershell -ExecutionPolicy Bypass -File tool\bootstrap.ps1
   ```

   This runs `flutter create` for the missing platform files (Scrapp's Android files are kept), removes the default MainActivity, downloads `efficientdet_lite0.tflite` into `android/app/src/main/assets/`, and runs `flutter pub get`.
3. Plug in the phone with USB debugging on, then:

   ```bash
   flutter run --dart-define=API_BASE=http://192.168.1.50:8000
   ```

   You can also change the server later in the app (server icon on the sign-in screen, or Settings).
4. Kotlin unit test (voice phrase matcher): `cd android && ./gradlew :app:testDebugUnitTest`

## 4. First run

1. **Create an account.**
2. **Scrap tab → Link glasses in Meta AI.** The Meta AI app opens; approve, and it returns to Scrapp.
3. **Settings → Camera access** and **Mic access** (both granted in Meta AI).
4. **Start scrapbooking.** A notification ("Scrapp is listening") shows the service is up. Pills show Linked, Connected, Listening and Button active.
5. Look at something and say **"scrapbook that"** (or press the capture button). You'll hear "Scrapbooking", then "Scrapbooked. N stickers." The Book tab fills in, grouped by place.
6. Collage: **Studio → New collage**. Add stickers, then grow a 3D thing in Studio → 3D and add it. Size the save box and **Save to collection**.
7. Social: add a friend by username (second account on another phone). On a sticker: **Send to a friend** → "On a kind of object" → apple. They open it from their inbox and hold up an apple.
8. Hunt: make a few located captures somewhere, then **Hunts → Create a hunt** and send it. Your friend taps **Hunt with my glasses** on site and says "scrapbook that" at each find.

**Without glasses:** Settings → Developer → **Mock glasses** (Meta's MockDeviceKit pairs simulated Ray-Ban Meta glasses and uses the phone camera as their camera), then "Simulate 'scrapbook that'". Or use **Photo** on the Scrap tab to send any phone photo through the same pipeline.

## 5. If something fails

| Symptom | Fix |
|---|---|
| Linking fails, "Internal error" or HTTP 401 | Developer Mode is off in Meta AI, or the IDs in `local.properties` don't match the project |
| Pills say Not connected | Glasses asleep, folded or not worn. Open them, wear them, and check Meta AI shows them connected |
| "Voice unavailable" | Grant Mic access in Settings, and make sure Speech is enabled for the project in the Developer Center |
| Button pill stays "unavailable" | Inputs not enabled for the project in the Developer Center |
| Uploads fail on the phone | `API_BASE` / `PUBLIC_BASE_URL` must be the LAN IP, not localhost. Phone and computer on the same Wi-Fi; firewall allows port 8000 |
| Stickers never appear | Check the server log. `SEGMENTER=sam2` without a GPU fails, so switch to `grabcut` to confirm the rest works |
| Gradle: Kotlin/AGP version errors | Keep AGP 8.13.x, Kotlin 2.3.x, JDK 21 and Gradle 8.14.x as set in `android/`. SceneView 4.18 and DAT 1.0.1 need them |

// Head tracking for off-axis ("window") projection.
//
// Uses the webcam + MediaPipe's BlazeFace detector to estimate where the viewer's eyes are,
// in centimetres, relative to the CENTRE OF THE SCREEN:
//   x → right, y → up, z → out of the screen toward the viewer.
// Distance comes from the pixel gap between the eyes (people's eyes are ~6.3 cm apart),
// so no depth camera is needed.

const WASM_PATH = '/vendor/mediapipe/wasm';
const MODEL_URLS = [
  '/models-ml/blaze_face_short_range.tflite', // served (and cached) by our own server
  'https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite',
];

export const DEFAULT_CALIB = {
  screenWidthCm: 30.4, // physical width of the display (14" MacBook Pro ≈ 30.4, 16" ≈ 34.5, 24" monitor ≈ 53)
  cameraFovDeg: 60,    // webcam horizontal field of view
  cameraAboveCm: 1.0,  // webcam distance above the top edge of the display
  ipdCm: 6.3,          // distance between the viewer's pupils
  smoothing: 0.5,      // 0 = raw, 0.9 = very smooth (more lag)
};

export class HeadTracker {
  constructor(calib = DEFAULT_CALIB) {
    this.calib = { ...DEFAULT_CALIB, ...calib };
    this.eye = { x: 0, y: 0, z: 60 }; // smoothed, cm, screen-centred
    this.raw = null;                  // last raw detection (normalised keypoints) for the preview overlay
    this.tracking = false;            // face visible right now
    this.lastSeen = 0;
    this.running = false;
    this.video = null;
    this.detector = null;
    this._lastVideoTime = -1;
  }

  async start(video) {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('This browser has no camera access (use http://localhost or https).');
    this.video = video;
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false,
    });
    video.srcObject = this.stream;
    video.muted = true;
    video.playsInline = true;
    await video.play();

    if (!this.detector) {
      const { FaceDetector, FilesetResolver } = await import('/vendor/mediapipe/vision_bundle.mjs');
      const fileset = await FilesetResolver.forVisionTasks(WASM_PATH);
      let lastErr;
      for (const url of MODEL_URLS) {
        try {
          this.detector = await FaceDetector.createFromOptions(fileset, {
            baseOptions: { modelAssetPath: url, delegate: 'GPU' },
            runningMode: 'VIDEO',
            minDetectionConfidence: 0.5,
          });
          break;
        } catch (e) { lastErr = e; }
      }
      if (!this.detector) throw new Error(`Couldn't load the face model: ${lastErr?.message || 'unknown error'}`);
    }
    this.running = true;
    this._loop();
  }

  stop() {
    this.running = false;
    this.tracking = false;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    if (this.video) this.video.srcObject = null;
  }

  _loop() {
    if (!this.running) return;
    const v = this.video;
    if (v.readyState >= 2 && v.currentTime !== this._lastVideoTime) {
      this._lastVideoTime = v.currentTime;
      try {
        const res = this.detector.detectForVideo(v, performance.now());
        this._onDetections(res.detections || []);
      } catch (e) { console.warn('face detection error', e); }
    }
    // Lost the face for a while → drift gently back to a neutral, centred viewpoint
    if (!this.tracking && performance.now() - this.lastSeen > 1500) {
      this._smoothTo({ x: 0, y: 0, z: 60 }, 0.97);
    }
    requestAnimationFrame(() => this._loop());
  }

  _onDetections(dets) {
    if (!dets.length) { this.tracking = false; this.raw = null; return; }
    // Largest face = nearest person
    const d = dets.reduce((a, b) => (b.boundingBox.width > a.boundingBox.width ? b : a));
    const [rEye, lEye] = d.keypoints; // BlazeFace: 0 = right eye, 1 = left eye (normalised 0–1)
    if (!rEye || !lEye) return;
    const W = this.video.videoWidth, H = this.video.videoHeight;
    const c = this.calib;

    const f = (W / 2) / Math.tan((c.cameraFovDeg * Math.PI) / 360); // focal length in px
    const eyePx = Math.hypot((lEye.x - rEye.x) * W, (lEye.y - rEye.y) * H);
    if (eyePx < 4) return;
    const z = (c.ipdCm * f) / eyePx;                       // distance from camera, cm
    const u = ((rEye.x + lEye.x) / 2) * W - W / 2;         // eye midpoint offset from image centre, px
    const v = ((rEye.y + lEye.y) / 2) * H - H / 2;

    const screenHeightCm = c.screenWidthCm * (screen.height / screen.width);
    const camY = screenHeightCm / 2 + c.cameraAboveCm;     // webcam sits above the screen centre
    const target = {
      x: -(u * z) / f,       // the camera faces you, so image-left is your right
      y: camY - (v * z) / f, // image y grows downward
      z: Math.max(z, 15),
    };
    this.raw = { rEye, lEye, box: d.boundingBox, W, H };
    this.tracking = true;
    this.lastSeen = performance.now();
    this._smoothTo(target, c.smoothing);
  }

  _smoothTo(t, k) {
    this.eye.x = this.eye.x * k + t.x * (1 - k);
    this.eye.y = this.eye.y * k + t.y * (1 - k);
    this.eye.z = this.eye.z * k + t.z * (1 - k);
  }
}

// Where the canvas sits on the physical screen, in cm relative to the screen centre (y up).
export function canvasPhysicalRect(canvas, screenWidthCm) {
  const r = canvas.getBoundingClientRect();
  const cmPerPx = screenWidthCm / screen.width;
  // Approximate browser chrome: side borders split evenly, toolbars on top.
  const chromeX = Math.max(0, (window.outerWidth - window.innerWidth) / 2);
  const chromeY = Math.max(0, window.outerHeight - window.innerHeight - chromeX);
  const left = (window.screenX - (screen.availLeft || 0)) + chromeX + r.left;
  const top = (window.screenY - (screen.availTop || 0)) + chromeY + r.top;
  const cx = left + r.width / 2, cy = top + r.height / 2;
  return {
    cx: (cx - screen.width / 2) * cmPerPx,
    cy: -(cy - screen.height / 2) * cmPerPx,
    width: r.width * cmPerPx,
    height: r.height * cmPerPx,
  };
}

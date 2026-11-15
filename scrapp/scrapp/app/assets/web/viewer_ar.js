// "View in AR" for the public viewer (Android: Google Scene Viewer, WebXR where the browser has it).
// The button only appears when (1) the owner has saved the collage from the app, which uploads collage.glb, and (2) this device can
// actually start AR (model-viewer's canActivateAR). Everything else (old collages, desktops, iPhones) simply has no button.
//
// iOS Quick Look needs a USDZ file; we do not make one, so iPhones get no AR button (they still get drift/tilt).
export const AR_BUTTON_ENABLED = true;            // flip to false to hide the button everywhere without touching anything else
const MODEL_VIEWER = 'https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js';

let loading = null;
function loadModelViewer() {
  if (customElements.get('model-viewer')) return Promise.resolve();
  if (!loading) loading = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.type = 'module'; s.src = MODEL_VIEWER; s.onload = resolve; s.onerror = () => reject(new Error('model-viewer failed to load'));
    document.head.appendChild(s);
  });
  return loading;
}

export async function setupAr({ glbUrl, onState }) {
  if (!AR_BUTTON_ENABLED) return null;
  try {
    await loadModelViewer();
    await customElements.whenDefined('model-viewer');
  } catch (e) { onState?.('unavailable', e); return null; }
  const mv = document.createElement('model-viewer');
  mv.setAttribute('src', glbUrl);
  mv.setAttribute('ar', '');
  mv.setAttribute('ar-modes', 'scene-viewer webxr');
  mv.setAttribute('ar-scale', 'auto');                // the user can pinch to resize; the file itself is about 0.8 m wide
  mv.setAttribute('ar-placement', 'floor');
  mv.setAttribute('loading', 'eager');
  mv.setAttribute('reveal', 'manual');
  mv.setAttribute('alt', 'The collage in 3D');
  mv.style.cssText = 'position:fixed;left:-9999px;top:0;width:320px;height:320px;pointer-events:none';  // not shown: our own pill opens AR
  document.body.appendChild(mv);

  const btn = document.createElement('button');
  btn.id = 'ar-btn'; btn.textContent = 'View in AR'; btn.style.display = 'none';
  Object.assign(btn.style, {
    position: 'fixed', right: '14px', bottom: '48px', zIndex: 6, border: 0, borderRadius: '999px', padding: '11px 20px', cursor: 'pointer',
    font: '400 18px/1 Anton, Impact, sans-serif', letterSpacing: '.6px', color: '#5C3A26', background: '#A3B18A',
    boxShadow: '0 4px 0 rgba(105,74,71,.28)',
  });
  btn.addEventListener('click', () => { try { mv.activateAR(); } catch (e) { onState?.('error', e); } });
  document.body.appendChild(btn);

  const decide = () => { const ok = !!mv.canActivateAR; btn.style.display = ok ? 'block' : 'none'; onState?.(ok ? 'ready' : 'no-ar'); };
  mv.addEventListener('load', decide);
  mv.addEventListener('ar-status', (e) => { if (e.detail.status === 'failed') onState?.('failed'); });
  mv.addEventListener('error', (e) => onState?.('error', e.detail));
  return { mv, btn };
}

"""Generates Scrapp's tileable UI textures (paper grain overlay + fuzzy grass) into app/assets/textures."""
import sys
from pathlib import Path

import cv2
import numpy as np

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "app/assets/web/textures")
OUT.mkdir(parents=True, exist_ok=True)
N = 512
rng = np.random.default_rng(7)


def wrap_blur(img, sigma):
    # Tileable blur: pad periodically, blur, crop back.
    pad = int(sigma * 4) + 1
    widths = ((pad, pad), (pad, pad)) + ((0, 0),) * (img.ndim - 2)
    big = np.pad(img, widths, mode="wrap")
    out = cv2.GaussianBlur(big, (0, 0), sigma)
    if out.ndim < img.ndim:
        out = out[..., None]
    return out[pad:-pad, pad:-pad]


def draw_wrapped(canvas, draw):
    # Draw on a 3x3 tiled canvas and fold back so strokes cross edges seamlessly.
    big = np.zeros((N * 3, N * 3) + canvas.shape[2:], canvas.dtype)
    draw(big)
    folded = np.zeros_like(canvas, dtype=np.float32)
    for i in range(3):
        for j in range(3):
            folded += big[i * N:(i + 1) * N, j * N:(j + 1) * N]
    return folded


# ---------------------------------------------------------------- paper grain overlay (RGBA)
mottle = wrap_blur(rng.normal(0, 1, (N, N)).astype(np.float32), 18)
mottle = mottle / (np.abs(mottle).max() + 1e-6)
grain = wrap_blur(rng.normal(0, 1, (N, N)).astype(np.float32), 0.6)
grain = grain / (np.abs(grain).max() + 1e-6)


def fibers(big):
    for _ in range(260):
        x, y = rng.uniform(N, 2 * N, 2)
        ang = rng.uniform(0, np.pi)
        length = rng.uniform(6, 26)
        pts = []
        for t in np.linspace(0, 1, 8):
            bend = np.sin(t * np.pi) * rng.uniform(-3, 3)
            pts.append([x + np.cos(ang) * length * t - np.sin(ang) * bend,
                        y + np.sin(ang) * length * t + np.cos(ang) * bend])
        cv2.polylines(big, [np.int32(pts)], False, float(rng.uniform(0.4, 1.0)), 1, cv2.LINE_AA)


fib = draw_wrapped(np.zeros((N, N), np.float32), fibers)
dark = np.clip(0.7 * np.maximum(-grain, 0) + 0.12 * np.maximum(mottle, 0), 0, 1)
light = np.clip(0.45 * np.maximum(grain, 0) + 0.9 * fib, 0, 1)
alpha = np.clip(dark * 0.22 + light * 0.30, 0, 1)
lum = np.where(light > dark, 255, 92)  # light flecks are white, dark flecks are brown ink
rgb = np.stack([lum, lum * 0.93, lum * 0.86], -1)
rgb[light <= dark] = (92, 58, 38)  # #5C3A26
paper = np.dstack([rgb, alpha * 255]).astype(np.uint8)
cv2.imwrite(str(OUT / "paper_grain.png"), cv2.cvtColor(paper, cv2.COLOR_RGBA2BGRA))

# ---------------------------------------------------------------- fuzzy grass / plush (RGB)
base = np.array([163, 177, 138], np.float32)  # soft sage #A3B18A
under = wrap_blur(rng.normal(0, 1, (N, N, 1)).astype(np.float32), 6)
under = under / (np.abs(under).max() + 1e-6)
clump = wrap_blur(rng.normal(0, 1, (N, N)).astype(np.float32), 10)
clump = clump / (np.abs(clump).max() + 1e-6)
fur = np.ones((N, N, 3), np.float32) * base * (0.55 + 0.10 * under)


def strands(big):
    for _ in range(26000):
        x, y = rng.uniform(N, 2 * N, 2)
        c = clump[int(y) % N, int(x) % N]
        ang = -np.pi / 2 + 0.6 * c + rng.normal(0, 0.35)  # blades lean together in clumps
        length = rng.gamma(3.0, 2.6)
        curl = rng.normal(0, 0.2)
        shade = rng.uniform(0.8, 1.25) + 0.18 * c
        col = np.clip(base * shade + rng.normal(0, 6, 3), 0, 255)
        pts = []
        for t in np.linspace(0, 1, 6):
            a = ang + curl * t
            pts.append([x + np.cos(a) * length * t, y + np.sin(a) * length * t])
        cv2.polylines(big, [np.int32(pts)], False, col.tolist(), 1, cv2.LINE_AA)
        # bright tip
        tip = tuple(int(v) for v in pts[-1])
        cv2.circle(big, tip, 0, np.clip(col * 1.12, 0, 255).tolist(), -1, cv2.LINE_AA)


layer = np.zeros((N * 3, N * 3, 3), np.float32)
strands(layer)
mask = np.zeros((N * 3, N * 3), np.float32)
mask[layer.sum(-1) > 0] = 1
folded = np.zeros((N, N, 3), np.float32)
fmask = np.zeros((N, N), np.float32)
for i in range(3):
    for j in range(3):
        folded += layer[i * N:(i + 1) * N, j * N:(j + 1) * N]
        fmask += mask[i * N:(i + 1) * N, j * N:(j + 1) * N]
cover = np.clip(fmask, 0, 1)[..., None]
avg = folded / np.maximum(fmask, 1)[..., None]
fur = fur * (1 - cover * 0.85) + avg * cover * 0.85
fur = np.clip(fur, 0, 255).astype(np.uint8)
cv2.imwrite(str(OUT / "fuzz_grass.jpg"), cv2.cvtColor(fur, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
print("wrote", OUT / "paper_grain.png", OUT / "fuzz_grass.jpg")

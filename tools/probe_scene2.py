"""Probe 3: edge density per cell, faint large marks, rock/building shapes."""

from __future__ import annotations

import sys

import cv2
import numpy as np

sys.path.insert(0, r"D:\PROJECTS\VI3ION")
from vi3ion.colors import nearest_named  # noqa: E402

PATH = r"C:\Users\ADMIN\Pictures\Screenshots\Screenshot 2026-10-31 212904.png"
bgr = cv2.imread(PATH)
h, w = bgr.shape[:2]
gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

print("== edge density per 4x3 cell (%) ==")
edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 40, 110)
for r in range(3):
    row = []
    for c in range(4):
        cell = edges[int(r * h / 3):int((r + 1) * h / 3), int(c * w / 4):int((c + 1) * w / 4)]
        row.append(f"{(cell > 0).mean() * 100:5.2f}")
    print("   ", "  ".join(row))

print("\n== faint grey marks (V 20..70, S<50), comps >=0.4% ==")
mask = ((hsv[:, :, 2] > 20) & (hsv[:, :, 2] < 75) & (hsv[:, :, 1] < 60)).astype(np.uint8)
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
total = float(h * w)
rows = []
for label in range(1, n):
    x, y, bw, bh, area = stats[label]
    if area / total < 0.004:
        continue
    rows.append((area, x, y, bw, bh))
rows.sort(reverse=True)
for area, x, y, bw, bh in rows[:10]:
    mean = bgr[y:y + bh, x:x + bw].mean(axis=(0, 1))
    print(f"    area={area:6d} ({area / total:5.2%}) bbox=({x},{y},{x + bw},{y + bh}) "
          f"fill={area / (bw * bh):.2f} mean={nearest_named(tuple(mean[:3]))} "
          f"meanV={hsv[y:y + bh, x:x + bw, 2].mean():.0f}")

print("\n== bottom-right quadrant (rocks) ==")
x0, y0 = int(0.72 * w), int(0.78 * h)
patch = bgr[y0:h, x0:w]
print(f"    crop=({x0},{y0},{w},{h}) mean={nearest_named(tuple(patch.mean(axis=(0, 1))[:3]))}")
sub = hsv[y0:h, x0:w]
print(f"    meanS={sub[:, :, 1].mean():.0f} meanV={sub[:, :, 2].mean():.0f} "
      f"edge density={(cv2.Canny(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), 40, 110) > 0).mean() * 100:.1f}%")

print("\n== left-centre warm cluster / right blue building ==")
for name, (x0, y0, x1, y1) in {
    "right building": (1420, 250, 1660, 500),
    "left building": (520, 330, 760, 640),
    "sky top centre": (800, 80, 1200, 200),
}.items():
    patch = bgr[y0:y1, x0:x1]
    mean = patch.mean(axis=(0, 1))[:3]
    sub = hsv[y0:y1, x0:x1]
    print(f"    {name:14s} mean={nearest_named(tuple(mean)):12s} "
          f"S={sub[:, :, 1].mean():.0f} V={sub[:, :, 2].mean():.0f} "
          f"hue={sub[:, :, 0].mean():.0f}")

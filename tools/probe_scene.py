"""Probe the screenshot for structure the brief does not yet describe."""

from __future__ import annotations

import sys

import cv2
import numpy as np

sys.path.insert(0, r"D:\PROJECTS\VI3ION")
from vi3ion.colors import nearest_named  # noqa: E402

PATH = r"C:\Users\ADMIN\Pictures\Screenshots\Screenshot 2026-10-31 212904.png"
bgr = cv2.imread(PATH)
h, w = bgr.shape[:2]
print(f"image {w}x{h}")

hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

print("\n== saturated colour components (share>0.5%) ==")
small = cv2.resize(bgr, None, fx=320 / w, fy=320 / w, interpolation=cv2.INTER_AREA)
sh = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
total = float(small.shape[0] * small.shape[1])
scale = w / 320.0
found = []
for lo in range(0, 180, 22):
    mask = ((sh[:, :, 0] >= lo) & (sh[:, :, 0] < lo + 22)
            & (sh[:, :, 1] > 70) & (sh[:, :, 2] > 45)).astype(np.uint8)
    if not mask.any():
        continue
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for label in range(1, n):
        x, y, bw, bh, area = stats[label]
        share = area / total
        if share < 0.005:
            continue
        mean = small[labels == label].mean(axis=0)[:3]
        found.append((share, (x * scale, y * scale, (x + bw) * scale, (y + bh) * scale),
                      nearest_named(mean), int(lo)))
found.sort(reverse=True)
for share, bbox, name, hue in found[:18]:
    print(f"  {share:5.2%} hue{int(hue):3d}-{int(hue) + 22:3d} {name:12s} "
          f"bbox=({bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f})")

print("\n== bright blobs (V>170, S any) ==")
mask = ((V > 170)).astype(np.uint8)
n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
areas = stats[1:, 4]
print(f"  total bright components: {n - 1}")
bins = [(1, 20), (20, 100), (100, 400), (400, 2000), (2000, 20000), (20000, 10**9)]
for lo, hi in bins:
    print(f"    {lo:>6}-{hi:<6} px: {int(((areas >= lo) & (areas < hi)).sum())}")
big = sorted(range(1, n), key=lambda i: -stats[i, 4])[:10]
for label in big:
    x, y, bw, bh, area = stats[label]
    mean = bgr[y:y + bh, x:x + bw][labels[y:y + bh, x:x + bw] == label].mean(axis=0)[:3]
    print(f"    area={area:6d} bbox=({x},{y},{x + bw},{y + bh}) fill={area / (bw * bh):.2f} "
          f"colour={nearest_named(mean)}")

print("\n== warm lit blocks (amber windows/lanterns) ==")
warm = ((H >= 8) & (H <= 35) & (S > 90) & (V > 150)).astype(np.uint8)
warm = cv2.morphologyEx(warm, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
n, labels, stats, _ = cv2.connectedComponentsWithStats(warm, 8)
warm_blocks = [i for i in range(1, n) if stats[i, 4] >= 120]
print(f"  warm blocks >=120px: {len(warm_blocks)}")
for label in sorted(warm_blocks, key=lambda i: -stats[i, 4])[:12]:
    x, y, bw, bh, area = stats[label]
    print(f"    area={area:5d} bbox=({x},{y},{x + bw},{y + bh}) aspect={bw / bh:.1f}")

print("\n== red mask shape (sun + path) ==")
red = (((H < 12) | (H > 168)) & (S > 110) & (V > 70)).astype(np.uint8)
red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
n, labels, stats, _ = cv2.connectedComponentsWithStats(red, 8)
for label in sorted(range(1, n), key=lambda i: -stats[i, 4])[:8]:
    x, y, bw, bh, area = stats[label]
    if area < 500:
        continue
    rows = np.where((labels == label).any(axis=1))[0]
    widths = [(labels[y0] == label).sum() for y0 in rows[:: max(1, len(rows) // 5)]]
    print(f"    area={area:6d} bbox=({x},{y},{x + bw},{y + bh}) "
          f"widths top->bottom={widths}")

print("\n== low-contrast large marks (watermarks) ==")
gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
blur = cv2.GaussianBlur(gray, (5, 5), 0)
edges = cv2.Canny(blur, 6, 18)
edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)
contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
    x, y, bw, bh = cv2.boundingRect(contour)
    area = cv2.contourArea(contour)
    if bw * bh < 20000:
        continue
    print(f"    bbox=({x},{y},{x + bw},{y + bh}) area={area:.0f} fill={area / (bw * bh):.2f}")

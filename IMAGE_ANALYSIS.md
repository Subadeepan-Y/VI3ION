# Image analysis — "Screenshot 2026-10-31 212904.png"

Hand-written observation of the image (1919 × 949 px). This is the reference a
blind reader must be able to reconstruct from a Vi3ion brief alone, so every
statement below is something visible in the image, not an inference from the
project code.

Source file: `C:\Users\ADMIN\Pictures\Screenshots\Screenshot 2026-10-31 212904.png`

---

## 1. One-paragraph summary

A full-bleed, dark, illustrated **Kyoto night scene** used as the landing page of
a portfolio. Two tall off-white cylindrical pillars divide the frame near the
28% and 72% width lines. Behind them: a red sun disc in the upper centre-right,
a one-point-perspective red walkway running from the bottom centre toward the
middle distance, tiered temple/pagoda silhouettes, glowing amber paper windows
and lanterns, a dark navy building on the right, brown rocks in the bottom-right
corner, and autumn maple foliage entering at the top-left. Snow-like white
specks and drifting red leaf flecks fall across the whole frame. A large
off-white headline sits over the left pillar, a numbered project index runs down
the right edge, and a small mono-font footer carries coordinates, keyboard
hints and a credit line. Large translucent kanji watermarks sit behind the art.

---

## 2. Colour palette

| Role | Approximate colour | Where |
|---|---|---|
| Background / negative space | near-black `#080808` | sky, shadows, outer thirds |
| Dominant measured colour | `#080808`, 32% of pixels (measured) | whole frame |
| Deep red / crimson | `#8e1f1a`–`#c0392b` | sun disc, walkway, torii roofs, red dots |
| Warm amber / gold | `#d9a441`–`#f0c96a` | lit paper windows, lanterns, reflections |
| Off-white / cream | `#eeece6` | pillars, display headline, nav labels |
| Muted grey | `#8a8a8a` | small labels, footer text, stone |
| Dark navy / blue-grey | `#22303f`–`#2b3a4a` | right-hand building mass |
| Brown / stone | `#6b4a35`–`#8a6a52` | rocks bottom-right, roofs |
| Red-brown foliage | `#7a1f14`–`#a52a1a` | maple leaves, upper left |

4 × 3 colour map as measured by the current pipeline:

```
row 1: black/dark  black/dark  black/dark  black/dark
row 2: grey/mid    grey/mid    black/dark  black/dark
row 3: black/dark  brown/dark  brown/mid   brown/mid
```

Note the map under-reports the right-hand building (row 2, col 4 reads
`black/dark` although a dark navy mass is visible there) and the top-left
foliage (row 1, col 1 reads `black/dark`).

---

## 3. Layout map

| Zone | What is there | Approximate box (px) |
|---|---|---|
| Top-left brand | red seal + wordmark + sub-line | x 55–300, y 30–80 |
| Top navigation | HERO · ABOUT · WORK · PROCESS · CONTACT | x 800–1280, y 35–70 |
| Top-right control | circular audio button | x 1795–1845, y 35–80 |
| Left meta line | red dot + `00 // PORTFOLIO // 2026` | x 110–370, y 160–185 |
| Hero headline | 4 display lines | x 115–880, y 225–650 |
| Hero paragraph | two-line body copy | x 115–745, y 670–732 |
| Scroll cue | `SCROLL TO ENTER` + rule | x 120–310, y 775–800 |
| Right index | 10 numbered project rows | x 1690–1880, y 300–660 |
| Bottom-left footer | `00` + project name + coordinates | x 55–350, y 895–945 |
| Bottom-centre footer | `1611 ✕ 00 ✕ 2026` | x 860–1045, y 925–942 |
| Bottom-right footer | key hints + credit line | x 1440–1850, y 890–945 |

Vertical structure: brand/nav ≈ y 0–110; hero block y 150–800; footer y 890–949.

---

## 4. Text inventory (verbatim)

### Top bar

```
SUBADEEPAN
KYOTO SANCTUARY // 2026
HERO          (active: red dot before it)
ABOUT
WORK
PROCESS
CONTACT
```

### Left column

```
00 // PORTFOLIO // 2026

BUILT TO
SOLVE.            (red dot after)
SHIPPED TO
WORK.             (red dot after)

AI tutors. Animation engines. Game compilers. Leveraging modern stacks to
build what's missing.

SCROLL TO ENTER
```

### Right column — numbered index

```
00  THE HIDDEN GATE   門跡
01  THE MAKER         学宮
02  GRADEIFY          学宮
03  MANIM-TS          三重塔
04  DUEL DECK         両慈殿
05  DESKTOP BUDDY     茶室
06  GREATE ENGINE     天守閣
07  PERSONAL CLOUD    宝藏
08  THE RITUAL        作法
09  SANCTUM           内殿
```

The index digits are small red numerals; project names are cream small caps;
the Japanese labels are dimmer and smaller. At this resolution the kanji are
near the limit of legibility — treat the exact characters as low confidence,
but the pattern (two-character Japanese subtitles beside every row) is certain.

### Bottom bar

```
00   THE HIDDEN GATE
− 35°00'N 135°46'E // KYOTO VOID

1611 ✕ 00 ✕ 2026

[0-9] JUMP     [M] AUDIO     [SPACE] DOSSIER     [?] ALL

EST. 2026 // STILLNESS IN CRAFT
```

Also present, dim and vertical, along the extreme left edge near the bottom:
a short column of Japanese text.

---

## 5. Scene elements

Ordered roughly back to front.

1. **Sky / atmosphere** — near-black, with a subtle red haze above the sun and
   around the walkway. Hundreds of small pale dots (snow or ash) fall across
   the whole frame; the upper half is denser than the lower half.
2. **Red sun disc** — upper centre-right, roughly circular, diameter ≈ 200 px,
   deep coral red with a slightly darker rim, partially occluded by the pagoda
   roof in front of it.
3. **Tall pale pillars** — two off-white cylinders, slightly glowing, running
   almost the full image height. Left pillar ≈ x 500–585; right pillar ≈
   x 1335–1425. They read as paper lanterns or shrine columns. The headline
   renders in front of the left pillar.
4. **Tiered tower / pagoda** — centre-right, dark red-brown roofs with upturned
   eaves, several tiers, small pale green/cyan windows, a finial spire. Sits in
   front of the sun disc.
5. **Temple buildings** — left of centre and centre, dark tiled roofs with
   upturned corners; walls of pale amber paper windows (shoji) in a regular
   grid. A large building mass sits behind the headline on the left.
6. **Red walkway** — a broad path entering at the bottom centre and narrowing
   toward a vanishing point near the frame centre. Horizontal slat lines,
   glossy red surface, warm reflections; the red area widens toward the bottom
   edge and spills to the right.
7. **Torii gates and lantern posts** — repeated dark red gate frames along the
   walkway; black posts topped with small warm-lit lantern boxes at intervals.
8. **Right-hand building** — a dark navy/blue-grey block on the right, with
   three amber lit windows stacked vertically. Reads as a separate structure
   from the temple cluster.
9. **Rocks** — bottom-right corner, three or four large angular boulders,
   grey-brown, faceted, lit warmly from the upper left. The densest fine
   detail in the frame sits here.
10. **Maple foliage** — red-brown leaf clusters entering from the top-left
    corner and spilling along the top edge; individual leaves also drift
    through the scene as red flecks.
11. **Kanji watermarks** — very large, very faint translucent characters behind
    the art: 影 in the upper right, 匠 near the centre. Low contrast; they read
    as texture more than text.
12. **Vignette / frame** — edges are darker than the centre; no hard border
    line, but the composition pulls the eye to the centre walkway.

---

## 6. UI and interaction cues

- `HERO` is the active nav item (red dot marker).
- `SCROLL TO ENTER` implies the page is an entry screen; scrolling begins the
  experience.
- Audio button (speaker + equalizer) top right implies ambient sound control.
- Keyboard hints imply full keyboard navigation:
  - `[0-9] JUMP` — jump to a numbered project
  - `[M] AUDIO` — mute/unmute
  - `[SPACE] DOSSIER` — open the selected project dossier
  - `[?] ALL` — show all shortcuts
- The right index is a list of ten projects, currently with 00 selected.
- Footer coordinates (`35°00'N 135°46'E`) and `KYOTO VOID` set the fictional
  location; `EST. 2026 // STILLNESS IN CRAFT` is the studio credit.

---

## 7. Typography

- **Display**: very heavy geometric grotesque, tight tracking, off-white.
  Four lines, left-aligned, with red full stops after `SOLVE` and `WORK`.
- **Small caps / labels**: letterspaced uppercase, cream, ~10–12 px, used for
  nav, meta lines, footer hints.
- **Index list**: each row is `NN` (red) + name (cream caps) + Japanese
  subtitle (dim grey), all on one baseline, right-aligned to the margin.
- **Mono**: footer coordinates and counters (`1611 ✕ 00 ✕ 2026`) use a
  monospaced face with generous letterspacing.

---

## 8. Composition facts worth measuring

- Two pale vertical bands at ≈ 28% and ≈ 72% of the width, each ≈ 4–5% of the
  width and ≥ 90% of the height.
- Red area in the lower half occupies ≈ 17% of the frame and widens toward the
  bottom edge (width at 80% height ≈ 1.8–2× width at 20% height).
- One-point perspective: walkway edges converge toward a vanishing point near
  the horizontal centre, slightly above the vertical centre.
- Edge density by 4 × 3 cell (measured):

```
top     4.45  2.26  2.54  1.55
middle  4.02  3.78  2.57  3.53
bottom  6.78  4.38  3.34  9.38
```

Busiest cell: bottom-right (9.38% — rocks and foreground detail). Emptiest:
top-right (1.55% — dark sky). Text mass sits in the left third and the right
third; the middle third is mostly image.

- Bright small components (measured): 582 components above V = 170, of which
  432 are 1–20 px and 101 are 20–100 px — the falling specks.
- Warm lit rectangles (measured): 12 blocks ≥ 120 px in the amber hue band,
  clustered left of centre (temple windows) and on the right (navy building
  windows, lantern boxes).

---

## 9. Acceptance checklist for the brief

A blind reader given only the brief should be able to state, without guessing:

- [ ] The image is a dark, illustrated Kyoto-themed page, not a photograph.
- [ ] Two tall pale pillars divide the frame at roughly 28% and 72% width.
- [ ] There is a red circular sun-like shape in the upper centre-right.
- [ ] A broad red area occupies the bottom centre and widens toward the viewer.
- [ ] There are lit amber rectangles (windows/lanterns) on the left and right.
- [ ] The frame is covered in hundreds of small bright specks.
- [ ] There is red foliage entering at the top-left.
- [ ] The bottom-right corner is the busiest, with brown/grey angular detail.
- [ ] A dark navy mass sits on the right, distinct from the red/brown temple
      cluster.
- [ ] The headline is four lines and starts in the left column, including
      `SHIPPED TO` (not filed under "centre").
- [ ] The right index runs 00–09 in order, with the digits flagged rather than
      silently corrected when OCR is unsure.
- [ ] Footer contains coordinates, key hints (`[M] AUDIO`, `[SPACE] DOSSIER`,
      `[?] ALL`) and a credit line.
- [ ] Uncertain readings stay marked; nothing is silently invented.

Items 1–8 are scene evidence; 9–13 are text-layer facts. This document is the
ground truth for grading both.

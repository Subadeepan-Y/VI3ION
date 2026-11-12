# Human review — Screenshot 2026-10-31 212904.png

Reviewer name/label: ______________  Date: ______________

Open the crops in `tests/fixtures/crops/`. Grid lines every 50 original px
(100 px on screen). Axis labels give original coordinates. A bbox is
`[x0, y0, x1, y1]` in original pixels.

## A. Text — read the exact string you see, in order

| # | Where to look (crop) | Expected / candidate | Exact text you see | Legible? (Y/N) | Uncertain? | Notes |
|---|---|---|---|---|---|---|
| 1 | top_bar.png | SUBADEEPAN | | | | |
| 2 | top_bar.png | KYOTO / SANCTUARY / 2026 split & separators | | | | |
| 3 | top_bar.png | HERO / ABOUT / WORK / PROCESS / CONTACT | | | | |
| 4 | left_column.png | 00 // PORTFOLIO // 2026 | | | | |
| 5 | left_column.png | BUILT TO (or BUILTTO) | | | | |
| 6 | left_column.png | SOLVE. | | | | |
| 7 | left_column.png | SHIPPED TO (or SHIPPEDTO) | | | | |
| 8 | left_column.png | WORK. | | | | |
| 9 | left_column.png | full tagline (AI tutors… what's missing) | | | | |
| 10 | left_column.png | SCROLL TO ENTER | | | | |
| 11 | right_column.png | each number + label pair (00–09) | | | | |
| 12 | right_column.png | each of the nine Japanese labels | | | | |
| 13 | bottom_bar.png | 00 at left edge | | | | |
| 14 | bottom_bar.png | KYOTO VOID block (35°00'N 135°46'E // …) | | | | |
| 15 | bottom_bar.png | [0-9] JUMP / [M] AUDIO / [SPACE] DOSSIER / [?] ALL | | | | |
| 16 | bottom_bar.png | 1611 ∞ 00 ∞ 2026 | | | | |
| 17 | bottom_bar.png | EST. 2026 // STILLNESS IN CRAFT | | | | |
| 18 | bottom_left.png | complete bottom-left block (copy exactly) | | | | |

## B. Objects — read approximate boxes from the grid

| # | Object | Look in crop | Your bbox [x0,y0,x1,y1] | Uncertain? | Notes |
|---|---|---|---|---|---|
| 20 | torii gate (each visible element) | centre_scene.png | | | |
| 21 | stone pillar LEFT (top y and bottom y) | centre_scene.png | | | |
| 22 | stone pillar RIGHT (top y and bottom y) | centre_scene.png | | | |
| 23 | red sun | centre_scene.png | | | |
| 24 | pagoda | centre_scene.png | | | |
| 25 | paper lantern 1 | centre_scene.png / right_column.png | | | |
| 26 | paper lantern 2 | centre_scene.png / right_column.png | | | |
| 27 | red walkway | centre_scene.png | | | |
| 28 | rocks | centre_scene.png / bottom_left.png | | | |
| 29 | centre-right building | centre_scene.png | | | |
| 30 | anything else you can name | any | | | |

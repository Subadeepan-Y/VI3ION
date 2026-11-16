# What changed, in plain words

Newest first. Each entry is also a commit, so you can see exactly what moved.

## v0.1.4 / plugin v0.1.6 — the eyes get sharper

- **Recipes for recreation.** `vi3ion blueprint image.png` now returns a
  measured recipe — canvas size, background colour, and every shape's position
  and colour as percentages. A text-only model can hand this to an image
  generator and ask it to redraw a simple picture (three circles, a diagram,
  a UI layout) without ever seeing it. Fine detail is described, not promised.
- **Honest scoring.** Ground-truth guesses marked *uncertain* no longer count
  against the engine. Keyboard shortcuts like `[M]` no longer count as text.
  Hedges the brief itself flags are kept for recall but not charged against
  precision. A standalone annotation is no longer read as a quoted value.
- **Fidelity went from 88.7% to 95.2%** on the bundled fixtures. The drop came
  from an OCR contrast experiment; it is now opt-in
  (`VI3ION_OCR_CLAHE=1`) instead of default.
- **Docs got readable.** The README leads with the problem VI3ION solves and
  shows before/after charts. No jargon wall.

## v0.1.3 / plugin v0.1.5 — screenshots and pasted images

- New `screenshot` tool: captures the current screen, measures it locally, and
  fails cleanly on headless machines. Also `vi3ion screenshot` in the CLI.
- Fixed the "I can't read pasted clipboard images" failure. If an image is
  attached but no measurement reaches the model, the model is now told to call
  `inspect_image(path="clipboard")` instead of giving up.
- Text-only models are trusted more: when OpenCode says a model accepts only
  text, a model name containing "gpt" or "deepseek" no longer tricks the plugin
  into treating it as vision-capable.

## v0.1.2 / plugin v0.1.4 — OCR and update awareness

- Word splitting, contrast handling and row grouping for OCR.
- `vi3ion version`, update checks cached for a day, opt-in auto-updates,
  `/vi3ionversion`, `/vi3ionauto`, and an agent-run update tool behind
  OpenCode's permission prompt.

## Ongoing — stress testing

- `python scripts/stress_images.py "<folder>"` samples real screenshot folders,
  measures each image, and reports failures, slow analyses and pictures with
  no detected text. `docs/stress-report.json` holds the last run.

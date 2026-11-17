# Security policy

## Scope

**Local by default; remote processing is opt-in.** Vi3ion reads images that you
(or your agent) point it at, measures them on your machine, and returns text.

## What Vi3ion does with your data

- Images are copied into `~/.vi3ion/images/` and analysed locally. Use
  `vi3ion analyze <image> --no-store` to delete the copy and its evidence after
  the command, or `VI3ION_STORE_IMAGES=0` to disable keeping copies.
- `vi3ion purge --days 7 --confirm` deletes stored images older than seven days
  (`--days 0` deletes all). Without `--confirm` nothing is deleted.
- OCR and geometry run locally through ONNX models; no network call is made
  for analysis. A visible warning is printed when a remote provider is enabled.
- The optional `semantic` extra (object detection / captioning) can use a
  remote OpenAI-compatible endpoint — **only if you explicitly configure
  `VI3ION_SEMANTIC_PROVIDER=remote` and provide a base URL**. The default
  (`none`) is fully offline.
- `vi3ion local` probes local runtimes on `127.0.0.1` only.

## Reporting a problem

Please open an issue with the version (`vi3ion --version` / `vi3ion doctor`),
your OS, and a minimal reproduction. Do not attach private screenshots — a
redacted sample is enough.

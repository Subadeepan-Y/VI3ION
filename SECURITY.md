# Security policy

## Scope

Vi3ion reads images that you (or your agent) point it at, measures them locally,
and returns text. It never uploads anything.

## What Vi3ion does with your data

- Images are copied into `~/.vi3ion/images/` and analysed on your machine.
- OCR and geometry run locally through ONNX models; no network call is made
  for analysis.
- The optional `semantic` extra (object detection / captioning) can use a
  remote OpenAI-compatible endpoint — **only if you explicitly configure
  `VI3ION_SEMANTIC_PROVIDER=remote` and provide a base URL**. The default
  (`none`) is fully offline.
- `vi3ion local` probes local runtimes on `127.0.0.1` only.

## Reporting a problem

Please open an issue with the version (`vi3ion --version` / `vi3ion doctor`),
your OS, and a minimal reproduction. Do not attach private screenshots — a
redacted sample is enough.

# Vi3ion — TODO / release checklist

Last updated: 2026-11-12 (during release polish).

## Short-term (before v0.1.0 release)

- [x] Move MCP server into the package: `vi3ion/mcp_server.py`
- [x] Compat shim `agent_interface/mcp_server.py` → forwards to `vi3ion.mcp_server`
      (old launchers keep working instead of crashing with ModuleNotFoundError)
- [x] `pyproject.toml`: entry points point at `vi3ion.mcp_server:main`; package-data
      ships `core/ocr/models/*.onnx` + `skill/*.md`; slim core deps; extras
      `[ocr]`, `[semantic]`, `[dashboard]`, `[dev]`
- [x] `MANIFEST.in`: prune `dashboard/ .opencode/ data/ testing screenshots/` (the
      sdist would otherwise be ~200 MB of junk)
- [x] Defaults are machine-independent: `data_dir` → `~/.vi3ion`;
      `allowed_roots` → cwd + data dir; no hardcoded `D:\PROJECTS\VI3ION`
- [x] `vi3ion doctor` has an `mcp_entry_point` check that catches the stale-
      launcher failure mode
- [x] MIT LICENSE + README install section
- [ ] `gh repo create sub858/VI3ION --public` and push
- [ ] CI (`.github/workflows/ci.yml`): py3.11/3.12 × ubuntu/macos/windows →
      pytest → `vi3ion score --all` floor ≥ 91.5% → doctor → `python -m build`
- [ ] Release: `python -m build` → `twine check dist/*` → `gh release create
      v0.1.0 dist/*.whl dist/*.tar.gz` → clean-venv install proof:
      `pip install https://github.com/sub858/VI3ION/releases/download/v0.1.0/vi3ion-0.1.0-py3-none-any.whl`
- [ ] `plugins/opencode/` → npm package `@vi3ion/opencode` (verify with `npm pack`
      + install tarball in a scratch dir), or document the copy-into-plugins path
- [ ] Skill: add `vi3ion/skill/SKILL.md` to `package-data` (done) and register it
      via the OpenCode plugin (`ctx.skill.add`, autoinvoke) + `vi3ion skill` CLI
      that prints the skill text for `AGENTS.md`/`CLAUDE.md`/`.claude/skills/`
- [ ] `adapters/*.md` per harness (claude-code, cursor, windsurf, continue, zed,
      antigravity, quoder, pi, generic MCP) with verified config keys

## Later

- [ ] PyPI publish when ready (name free as of 2026-11-12); prefer trusted
      publishing (OIDC). Rehearse on TestPyPI first.
- [ ] npm publish `@vi3ion/opencode` (requires 2FA; unpublish only within 72h)
- [ ] Ship a `vi3ion-mcp` self-check subcommand (`mcp-selfcheck`) that performs a
      full stdio handshake (already covered by tests/test_mcp_handshake.py)
- [ ] Version the MCP contract (`VI3ION_MCP_CONTRACT`) so harnesses pin the tools
- [ ] Optional: bundle the rapidocr ONNX models officially (today they come from
      the `rapidocr-onnxruntime` pip dependency)
- [ ] Public docs site (or at least a proper rendered README with a screenshot)

## Known / accepted limits (not bugs)

- OCR is English/CJK-focused; Japanese margin recovery uses the bundled 3.4 MB
  `japan_rec_crnn.onnx` (skipped in low-resource mode)
- `score --all` fidelity is 91.9% on the bundled fixtures (see PERFORMANCE.md)
- `agent_interface` is a legacy shim; prefer `vi3ion.mcp_server` in new code

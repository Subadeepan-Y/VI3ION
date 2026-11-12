# VI3ION — TODO / release checklist

Last updated: 2026-11-12 (after the 0.1.0 release).

## Shipped in 0.1.0

- [x] MCP server moved into the package: `vi3ion/mcp_server.py`
- [x] Compat shim `agent_interface/mcp_server.py` → forwards to `vi3ion.mcp_server`
      (old launchers keep working instead of crashing with ModuleNotFoundError)
- [x] `pyproject.toml`: entry points point at `vi3ion.mcp_server:main`; package-data
      ships `core/ocr/models/*.onnx` + `skill/SKILL.md`; core deps slimmed;
      extras `[semantic]`, `[dashboard]`, `[dev]`
- [x] `MANIFEST.in`: prune `dashboard/ .opencode/ data/ testing screenshots/`
      (the sdist would otherwise be ~200 MB of junk)
- [x] Defaults are machine-independent: `data_dir` → `~/.vi3ion`;
      `allowed_roots` → cwd + data dir; no hardcoded `D:\PROJECTS\VI3ION`
- [x] A plain `pip install vi3ion` no longer breaks the MCP server: `httpx` was
      imported at module level, so the server died on startup for anyone
      without the dev extra. Now imported lazily.
- [x] OCR is a **core dependency** (a perception product that cannot read text
      is not finished). ~60 MB of ONNX runtime, one time.
- [x] `vi3ion mcp-check` — a real MCP handshake; the answer to "my editor says
      MCP failed"
- [x] `vi3ion doctor` flags the `env` vs `environment` trap and accepts the
      server under any spelling (`vi3ion` / `VI3ION`)
- [x] Plugin: every hook body is wrapped in try/catch — a plugin bug can no
      longer kill the session; a dead MCP server is detected and restarted
- [x] One data dir everywhere: `~/.vi3ion`. The plugin resolves it from the
      env, then from the editor's MCP config, then the default.
- [x] Apache-2.0 LICENSE + NOTICE; `project.urls` → `Subadeepan-Y/VI3ION`
- [x] Public repo `Subadeepan-Y/VI3ION`, branch `main`, 10 commits
- [x] CI (`.github/workflows/ci.yml`): 7 jobs green — ubuntu py3.11/3.12/3.13,
      windows py3.12, macos py3.13, the clean-install check (wheel → empty venv →
      MCP handshake), the plugin smoke suite, the 91.5% fidelity floor
- [x] Release `v0.1.0` published with the wheel + sdist attached
- [x] `plugins/opencode/` packaged as `@vi3ion/opencode` (packed, installed into
      a scratch project, smoke suite green against the *installed* package)
- [x] Skill: `vi3ion/skill/SKILL.md` ships in the wheel and the npm tarball, and
      the plugin registers it with the editor (auto-invoke)
- [x] `adapters/opencode/README.md` with the verified OpenCode config
- [x] The MCP server name may be `vi3ion` or `VI3ION` — the key is the display
      name and becomes the tool namespace; both work.

## Still to do

- [ ] npm publish of `@vi3ion/opencode` (the publish workflow is ready, uses the
      `NPM_TOKEN` secret, and signs with provenance; waiting on an automation
      token so CI can publish unattended)
- [ ] PyPI (`pip install vi3ion`) — rehearse on TestPyPI first; prefer trusted
      publishing (OIDC) over a long-lived token
- [ ] `adapters/*.md` for the other harnesses (claude-code, cursor, windsurf,
      continue, zed, antigravity, quoder, pi, generic MCP) with verified keys
- [ ] `vi3ion skill` CLI that prints the skill text for `AGENTS.md`/`CLAUDE.md`
- [ ] Version the MCP contract (`VI3ION_MCP_CONTRACT`) so harnesses can pin it
- [ ] Ship a `vi3ion-mcp selfcheck` subcommand (the same handshake as
      `vi3ion mcp-check`, for harnesses that prefer it)
- [ ] Public docs site (or a rendered README with a screenshot)

## Known / accepted limits (not bugs)

- OCR is English/CJK-focused; Japanese margin recovery uses the bundled 3.4 MB
  `japan_rec_crnn.onnx` (skipped in low-resource mode)
- `score --all` fidelity is 91.9% on the bundled fixtures (see PERFORMANCE.md)
- `agent_interface` is a legacy shim; prefer `vi3ion.mcp_server` in new code
- The npm package ships the **plugin only** — the engine comes from PyPI or the
  GitHub Release, so the install is two steps

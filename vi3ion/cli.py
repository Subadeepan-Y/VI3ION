"""Vi3ion command-line interface.

Subcommands:
  serve    Run the local HTTP server (dashboard + API) on 127.0.0.1.
  analyze  Analyse an image or a stored image id and print a JSON summary.
  brief    Print the text-only brief a vision-less model would read.
  score    Score a brief against hand-transcribed ground truth.
  health   Print configuration and environment status.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Sequence

from vi3ion.config import get_settings


def _engine() -> object:
    from vi3ion.core.engine import Vi3ionEngine

    return Vi3ionEngine(get_settings())


def cmd_serve(args: argparse.Namespace) -> int:
    from vi3ion.server.app import app

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    log_level = args.log_level or settings.log_level

    import uvicorn

    print(f"vi3ion: serving on http://{host}:{port} (data_dir={settings.data_dir})")
    uvicorn.run(app, host=host, port=port, log_level=log_level)
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    settings = get_settings()
    raw = args.path
    if not raw:
        print("error: a path or image id is required", file=sys.stderr)
        return 2
    path = Path(raw).expanduser()
    if not settings.is_path_allowed(path):
        print(
            f"error: path {path} is outside allowed roots "
            f"{[str(r) for r in settings.allowed_roots]}",
            file=sys.stderr,
        )
        return 2
    try:
        engine = _engine()
        if raw.startswith("vi3ion://"):
            image_id = raw.removeprefix("vi3ion://")
            response = engine.inspect_image(
                image_id=image_id, detail=args.detail, context=getattr(args, "context", None)
            )
        else:
            response = engine.inspect_image(
                path=str(path), detail=args.detail, context=getattr(args, "context", None)
            )
        label = getattr(args, "label", None)
        if label:
            engine.remember_image(image_id=response.image_id, label=label)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(response.to_json(args.detail))
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    from vi3ion.brief import make_brief

    path = Path(args.path).expanduser()
    if not path.exists():
        print(f"error: image not found: {path}", file=sys.stderr)
        return 2
    budget = int(getattr(args, "budget", 0) or 0)
    result = make_brief(path, budget_tokens=budget)
    if args.json:
        print(json.dumps({
            "text": result.text,
            "tokens": result.tokens,
            "omitted": result.omitted,
            "shapes": result.shape_count,
            "duration_ms": round(result.duration_ms),
            "layout": result.layout,
            "budget_tokens": result.budget_tokens,
            "truncated": result.truncated,
        }, indent=2))
        return 0
    print(result.text)
    if result.layout and not args.plain:
        print()
        print("SPATIAL LAYOUT (relative positions):")
        print(result.layout)
        print()
    print()
    print(
        f"[tokens={result.tokens}, omitted={result.omitted}, "
        f"shapes={result.shape_count}, duration_ms={result.duration_ms:.0f}]"
    )
    return 0


def _locate_image(name: str) -> Path | None:
    """Find an image by file name in the usual storage roots."""
    roots = [
        Path.cwd(),
        Path(__file__).resolve().parent.parent,
        Path.home() / "Pictures" / "Screenshots",
    ]
    for root in roots:
        for candidate in root.rglob(name):
            if candidate.is_file():
                return candidate
    return None


def cmd_score(args: argparse.Namespace) -> int:
    from vi3ion.brief import make_brief
    from vi3ion.evaluate import find_expected, load_expected, review

    if getattr(args, "all", False):
        fixtures = sorted(Path("tests/fixtures").glob("*.expected.json"))
        if not fixtures:
            print("error: no fixtures in tests/fixtures", file=sys.stderr)
            return 2
        print(f"{'image':<44} {'fidelity':>8} {'recall':>7} {'precision':>9} {'regions':>7}")
        total_overall = []
        for expected_path in fixtures:
            meta = load_expected(expected_path).get("_meta", {})
            image_path = _locate_image(str(meta.get("image", "")))
            if image_path is None:
                print(f"{meta.get('image','?'):<44} {'n/a':>8} (image not found)")
                continue
            report = review(make_brief(image_path).text, load_expected(expected_path))
            total_overall.append(report.overall)
            print(
                f"{image_path.name:<44} {report.overall:7.1%} "
                f"{report.recall:6.1%} {report.precision:8.1%} {report.regions:6.1%}"
            )
        if total_overall:
            avg = sum(total_overall) / len(total_overall)
            print(f"\naverage fidelity across {len(total_overall)} images: {avg:.1%}")
        return 0

    path = Path(args.path).expanduser()
    if not path.exists():
        print(f"error: image not found: {path}", file=sys.stderr)
        return 2
    expected_path = Path(args.expected).expanduser() if args.expected else find_expected(path)
    if expected_path is None or not expected_path.exists():
        print(
            "error: no ground-truth file found; pass --expected <file>.expected.json",
            file=sys.stderr,
        )
        return 2
    report = review(make_brief(path).text, load_expected(expected_path))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0

    print(f"ground truth: {expected_path}")
    rows = [
        ("brief fidelity", report.overall, 0.40 + 0.25 + 0.20 + 0.15),
        ("  text recall", report.recall, 0.40),
        ("  text precision", report.precision, 0.25),
        ("  region accuracy", report.regions, 0.20),
        ("  structure", report.structure, 0.15),
    ]
    for label, value, _weight in rows:
        print(f"{label:<18} {value:5.1%}  {'#' * int(value * 40)}")
    print()
    print(f"matched {report.matched_units}/{report.expected_units} ground-truth text units")
    for name, ok in report.structure_checks.items():
        print(f"  [{'x' if ok else ' '}] {name}")
    if report.missing:
        print("missing:")
        for value in report.missing[:8]:
            print(f"  - {value}")
    if report.spurious:
        print("in brief but not in ground truth:")
        for value in report.spurious[:8]:
            print(f"  - {value}")
    return 0


def cmd_code_search(args: argparse.Namespace) -> int:
    from vi3ion.code_verify import find_code_matches, get_code_index
    from vi3ion.config import get_settings

    settings = get_settings()
    roots = [Path(r) for r in (args.roots or settings.code_roots)]
    if not roots:
        print("error: no code roots (set VI3ION_CODE_ROOTS or pass --roots)", file=sys.stderr)
        return 2
    index = get_code_index(roots)
    matches = find_code_matches(args.query, index, limit=args.limit)
    if not matches:
        print("no matches")
        return 0
    for m in matches:
        print(f"{m.file}:{m.line}  ({m.score:.2f})  {m.snippet[:120]}")
    return 0


def detect_tier(settings) -> dict:
    """Classify this machine into a tier (T1 entry / T2 mid / T3 high).

    Uses total RAM (ctypes on Windows) and CPU core count. GPU acceleration
    is probed from the ONNX runtime providers when available.
    """
    total_gb = 0.0
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        total_gb = status.ullTotalPhys / (1024 ** 3)
    except Exception:
        pass

    cores = os.cpu_count() or 1

    gpu = False
    try:
        import onnxruntime as ort
        gpu = "CUDAExecutionProvider" in ort.get_available_providers()
    except Exception:
        pass

    if total_gb < 8.0 or cores <= 4:
        tier = "T1"
    elif total_gb <= 24.0 or cores <= 16:
        tier = "T2"
    else:
        tier = "T3"

    return {
        "tier": tier,
        "ram_gb": round(total_gb, 1),
        "cpu_cores": cores,
        "gpu": gpu,
        "low_resource": bool(settings.low_resource),
    }


def cmd_prune(args: argparse.Namespace) -> int:
    """Remove remembered images whose stored file no longer exists."""
    engine = _engine()
    pruned = engine.prune_missing(limit=args.limit)
    payload = {"ok": True, "pruned": pruned, "count": len(pruned)}
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    if not pruned:
        print("nothing to prune: every remembered image still has its file")
        return 0
    for image_id in pruned:
        print(f"pruned {image_id}")
    print(f"\n{len(pruned)} stale image(s) removed")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Analyse every image in a folder and register it in the image memory."""
    settings = get_settings()
    root = Path(args.path).expanduser()
    if not root.exists():
        print(f"error: path not found: {root}", file=sys.stderr)
        return 2
    if not settings.is_path_allowed(root):
        print(
            f"error: path {root} is outside allowed roots "
            f"{[str(r) for r in settings.allowed_roots]}",
            file=sys.stderr,
        )
        return 2

    patterns = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.bmp")
    files: list[Path] = []
    if root.is_file():
        files = [root]
    else:
        for pattern in patterns:
            files.extend(root.rglob(pattern) if args.recursive else root.glob(pattern))
    files = sorted({f.resolve() for f in files if f.is_file()})

    if not files:
        print(f"no images found in {root}")
        return 0

    engine = _engine()
    entries: list[dict[str, Any]] = []
    for file in files[: args.limit]:
        try:
            record, _ = engine.ingest_path(str(file))
            image_id = record["image_id"]
            engine.inspect_image(image_id=image_id, detail="compact", agent="cli")
            label = None
            if args.label:
                label = f"{args.label} {file.stem}".strip()
                engine.remember_image(image_id=image_id, label=label)
            entries.append(
                {
                    "image_id": image_id,
                    "file": str(file),
                    "label": label or "",
                    "text_count": (engine.db.get_image_registry(image_id) or {}).get("text_count", 0),
                }
            )
        except Exception as exc:  # noqa: BLE001
            entries.append({"file": str(file), "error": f"{type(exc).__name__}: {exc}"})

    payload = {
        "ok": True,
        "root": str(root),
        "count": len(entries),
        "images": entries,
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"{'image_id':<24} {'text':>5}  file")
    for entry in entries:
        if "error" in entry:
            print(f"{'ERROR':<24} {'':>5}  {entry['file']} — {entry['error']}")
            continue
        label = f"  [{entry['label']}]" if entry.get("label") else ""
        print(
            f"{entry['image_id']:<24} {entry['text_count']:>5}  "
            f"{Path(entry['file']).name}{label}"
        )
    print(f"\n{len(entries)} image(s) registered. Use vi3ion images to list them.")
    return 0


def cmd_mcp_check(args: argparse.Namespace) -> int:
    """Perform a real MCP handshake with the installed server.

    This is the command a user runs when their editor says "MCP failed": it
    spawns the server exactly like the editor does and reports what happened.
    """
    import subprocess
    import sys as _sys

    commands = [
        [sys.executable, "-m", "vi3ion.mcp_server"],
        ["vi3ion-mcp"],
    ]
    payload = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "vi3ion-selfcheck", "version": "1"},
                },
            }
        )
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
    )

    results: list[dict[str, Any]] = []
    for command in commands:
        entry: dict[str, Any] = {"command": " ".join(command)}
        try:
            proc = subprocess.run(
                command,
                input=payload,
                capture_output=True,
                text=True,
                timeout=45,
            )
            entry["exit_code"] = proc.returncode
            tools = 0
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if message.get("id") == 1 and "result" in message:
                    entry["initialize"] = "ok"
            if entry.get("initialize") == "ok":
                listing = (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/list",
                            "params": {},
                        }
                    )
                    + "\n"
                )
                proc2 = subprocess.run(
                    command,
                    input=payload + listing,
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                for line in proc2.stdout.splitlines():
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if message.get("id") == 2:
                        tools = len((message.get("result") or {}).get("tools") or [])
                entry["tools"] = tools
                entry["ok"] = tools > 0
            else:
                entry["ok"] = False
                entry["stderr"] = (proc.stderr or "").strip()[-400:]
        except FileNotFoundError:
            entry["ok"] = False
            entry["error"] = "command not found"
        except subprocess.TimeoutExpired:
            entry["ok"] = False
            entry["error"] = "timed out"
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = f"{type(exc).__name__}: {exc}"
        results.append(entry)
        if entry.get("ok"):
            break

    ok = any(entry.get("ok") for entry in results)
    payload_out = {
        "ok": ok,
        "attempts": results,
        "hint": (
            "The MCP server works. If your editor still reports a failure, restart it."
            if ok
            else "The MCP server could not start. Reinstall with: pip install -U vi3ion"
        ),
    }
    if args.json:
        print(json.dumps(payload_out, indent=2, ensure_ascii=False))
        return 0 if ok else 1

    print("Vi3ion MCP self-check")
    for entry in results:
        mark = "OK  " if entry.get("ok") else "FAIL"
        print(f"  [{mark}] {entry['command']}")
        for key in ("exit_code", "tools", "error", "stderr"):
            if entry.get(key) not in (None, ""):
                print(f"        {key}: {entry[key]}")
    print(f"\n{payload_out['hint']}")
    return 0 if ok else 1


def _strip_jsonc(raw: str) -> str:
    """Remove comments and trailing commas so a JSONC config can be parsed."""
    without_block = re.sub(r"/\*[\s\S]*?\*/", "", raw)
    without_line = re.sub(r'(^|[^:"\'\\])//[^\n]*', r"\1", without_block)
    return re.sub(r",(\s*[}\]])", r"\1", without_line)


def cmd_skill(args: argparse.Namespace) -> int:
    """Print the agent skill text (for AGENTS.md / CLAUDE.md / .claude/skills)."""
    from pathlib import Path

    import vi3ion

    skill_path = Path(vi3ion.__file__).resolve().parent / "skill" / "SKILL.md"
    if not skill_path.exists():
        print(
            f"error: the skill file is missing from this installation ({skill_path})",
            file=sys.stderr,
        )
        return 1
    text = skill_path.read_text(encoding="utf-8")
    if getattr(args, "out", None):
        target = Path(args.out).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"skill written to {target}")
        return 0
    print(text)
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    """Compare installed versions with the latest on PyPI (engine) and npm (plugin)."""
    from vi3ion.updates import auto_update_enabled, check, table_text

    settings = get_settings()
    settings.ensure_dirs()
    result = check(settings, force=args.force, timeout=args.timeout)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print(f"Vi3ion {_version()} — update check")
    print(table_text(result))
    state = "on" if auto_update_enabled(settings) else "off"
    print(f"auto-updates: {state} (off is the safe default; enable with 'vi3ion updates auto on')")
    return 0


def cmd_updates(args: argparse.Namespace) -> int:
    """Show or change the auto-update consent flag."""
    from vi3ion.updates import auto_update_enabled, read_cache, set_auto_update, table_text

    settings = get_settings()
    settings.ensure_dirs()

    if args.updates_action == "auto":
        if args.value in ("on", "off"):
            prefs = set_auto_update(settings, args.value == "on")
            if args.json:
                print(json.dumps({"updates_auto": prefs["updates_auto"]}, indent=2))
            else:
                print(f"auto-updates: {'on' if prefs['updates_auto'] else 'off'}")
            return 0
        if args.json:
            print(json.dumps({"updates_auto": auto_update_enabled(settings)}, indent=2))
        else:
            print(f"auto-updates: {'on' if auto_update_enabled(settings) else 'off'}")
        return 0

    cached = read_cache(settings)
    if not cached:
        print("no update check yet — run 'vi3ion version' to check online")
        return 0
    print(table_text(cached))
    print(f"auto-updates: {'on' if auto_update_enabled(settings) else 'off'}")
    return 0


def _maybe_ask_auto_updates(settings) -> str | None:
    """One-time interactive consent on first command run.

    Interactive terminals get a yes/no question. Non-interactive (agent- or
    pipe-routed) invocations leave the flag unset and return a hint the agent
    can relay to the user.
    """
    try:
        from vi3ion.updates import read_prefs, set_auto_update
    except Exception:  # noqa: BLE001
        return None
    try:
        prefs = read_prefs(settings)
    except Exception:  # noqa: BLE001
        return None
    if "updates_auto" in prefs:
        return None
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            answer = input("Enable auto-updates for Vi3ion? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer in ("y", "yes"):
            set_auto_update(settings, True)
            return "auto-updates enabled (change anytime with 'vi3ion updates auto off')."
        set_auto_update(settings, False)
        return "auto-updates left OFF (safe default); enable anytime with 'vi3ion updates auto on'."
    return (
        "auto-updates are OFF by default. To enable: 'vi3ion updates auto on' "
        "(or ask your agent to run it)."
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    """One-shot setup check: OCR, resources, registry, local runtimes, editor wiring."""
    settings = get_settings()
    settings.ensure_dirs()

    checks: list[dict[str, Any]] = []

    # 1. OCR availability
    ocr_ok = False
    ocr_detail = "unknown"
    try:
        from vi3ion.core.ocr.providers import get_ocr_provider

        provider = get_ocr_provider()
        ocr_ok = bool(provider.available)
        ocr_detail = provider.name if ocr_ok else "not available"
    except Exception as exc:  # noqa: BLE001
        ocr_detail = f"error: {exc}"
    checks.append({"check": "ocr", "ok": ocr_ok, "detail": ocr_detail})

    # 2. Machine tier
    tier = detect_tier(settings)
    checks.append(
        {
            "check": "resources",
            "ok": True,
            "detail": (
                f"tier {tier['tier']}, {tier['ram_gb']} GB RAM, "
                f"{tier['cpu_cores']} cores, gpu={tier['gpu']}, "
                f"low_resource={tier['low_resource']}"
            ),
        }
    )

    # 3. Registry / database
    try:
        engine = _engine()
        known = engine.list_known_images(limit=1000)
        checks.append(
            {
                "check": "registry",
                "ok": True,
                "detail": f"{len(known)} image(s) remembered in {settings.db_path}",
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append({"check": "registry", "ok": False, "detail": f"error: {exc}"})

    # 4. Local LLM runtimes
    local: dict[str, Any] = {"runtimes": [], "vision_models": [], "recommendation": ""}
    try:
        from vi3ion.local_stack import local_stack_report

        local = local_stack_report(timeout=1.0)
        running = ", ".join(r["name"] for r in local.get("runtimes", [])) or "none"
        checks.append(
            {
                "check": "local_runtimes",
                "ok": True,
                "blocking": False,
                "detail": f"serving: {running}; {local.get('recommendation', '')}",
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append({"check": "local_runtimes", "ok": False, "detail": f"error: {exc}"})

    # 5. Editor wiring (OpenCode plugin + MCP registration)
    config_paths = [
        Path.home() / ".config" / "opencode" / "opencode.jsonc",
        Path.home() / ".config" / "opencode" / "opencode.json",
        Path.home() / "opencode.json",
    ]
    plugin_found = False
    mcp_found = False
    mcp_env_key_ok = None
    for config_path in config_paths:
        if not config_path.exists():
            continue
        raw = config_path.read_text(encoding="utf-8", errors="replace")
        plugin_found = plugin_found or "vi3ion-attach" in raw
        if "vi3ion" not in raw.lower():
            continue
        try:
            parsed = json.loads(_strip_jsonc(raw))
            servers = (parsed.get("mcp") or {}).get("servers") or (parsed.get("mcp") or {})
            if not isinstance(servers, dict):
                continue
            # The key may be "vi3ion" or "VI3ION" (display name is the user's
            # choice); the tool namespace follows it exactly.
            key = next(
                (name for name in servers if name.strip().lower() == "vi3ion"),
                None,
            )
            if key is None:
                continue
            mcp_found = True
            entry = servers.get(key)
            if isinstance(entry, dict) and ("env" in entry or "environment" in entry):
                mcp_env_key_ok = "environment" in entry
        except Exception:  # noqa: BLE001
            pass
    checks.append(
        {
            "check": "editor_wiring",
            "ok": plugin_found and mcp_found,
            "blocking": False,
            "detail": f"plugin={'yes' if plugin_found else 'no'}, mcp={'yes' if mcp_found else 'no'}",
        }
    )
    if mcp_env_key_ok is False:
        checks.append(
            {
                "check": "mcp_env_key",
                "ok": False,
                "detail": (
                    "the vi3ion MCP server uses 'env' but OpenCode expects "
                    "'environment' - those variables are being ignored"
                ),
            }
        )

    # 6. Updates (cached; network only with --check-updates)
    try:
        from vi3ion.updates import auto_update_enabled, check, read_cache

        if args.check_updates:
            report = check(settings, force=True, timeout=4.0)
        else:
            report = read_cache(settings)
        if report:
            parts = []
            for key in ("engine", "plugin"):
                entry = report.get(key) or {}
                if entry.get("update_available"):
                    parts.append(
                        f"{key} {entry.get('installed')} -> {entry.get('latest')}"
                    )
            detail = "; ".join(parts) or "all current"
            if report.get("offline"):
                detail += " (offline, last known state)"
            if parts:
                checks.append(
                    {
                        "check": "updates",
                        "ok": True,
                        "blocking": False,
                        "detail": detail,
                    }
                )
            else:
                checks.append(
                    {
                        "check": "updates",
                        "ok": True,
                        "blocking": False,
                        "detail": f"{detail}; auto-updates={'on' if auto_update_enabled(settings) else 'off'}",
                    }
                )
        else:
            checks.append(
                {
                    "check": "updates",
                    "ok": True,
                    "blocking": False,
                    "detail": "not checked yet — run 'vi3ion version' (or doctor --check-updates)",
                }
            )
    except Exception:  # noqa: BLE001
        pass

    # 7. MCP server entry point: the module must import and the console script
    # must resolve. This catches the "No module named 'agent_interface'"
    # failure mode from stale launchers.
    mcp_entry_ok = False
    mcp_entry_detail = "not checked"
    try:
        from vi3ion.mcp_server import main  # noqa: F401

        mcp_entry_ok = True
        mcp_entry_detail = "vi3ion.mcp_server imports cleanly"
    except Exception as exc:  # noqa: BLE001
        mcp_entry_detail = f"error: {exc}"
        try:
            from agent_interface.mcp_server import main  # noqa: F401

            mcp_entry_ok = True
            mcp_entry_detail = "compat shim agent_interface.mcp_server resolves"
        except Exception as exc2:  # noqa: BLE001
            mcp_entry_detail = f"error: {exc} / {exc2}"
    checks.append(
        {
            "check": "mcp_entry_point",
            "ok": mcp_entry_ok,
            "detail": mcp_entry_detail,
        }
    )

    # First-run auto-update consent (interactive TTY, or a hint for agents).
    consent_note = _maybe_ask_auto_updates(settings)
    if consent_note:
        payload_actions = _doctor_actions(checks, local)
        payload_actions.append(consent_note)
    else:
        payload_actions = _doctor_actions(checks, local)

    payload = {
        "ok": all(c["ok"] for c in checks if c.get("blocking", True)),
        "version": _version(),
        "data_dir": str(settings.data_dir),
        "allowed_roots": [str(r) for r in settings.allowed_roots],
        "checks": checks,
        "local": local,
        "next_actions": payload_actions,
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"Vi3ion {_version()} — doctor")
    for check in checks:
        mark = "OK  " if check["ok"] else "WARN"
        print(f"  [{mark}] {check['check']}: {check['detail']}")
    print()
    for action in payload["next_actions"]:
        print(f"  -> {action}")
    return 0


def _version() -> str:
    try:
        from vi3ion import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


def _doctor_actions(checks: list[dict[str, Any]], local: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    by_name = {c["check"]: c for c in checks}
    if not by_name.get("ocr", {}).get("ok"):
        actions.append(
            "OCR is not ready: install it with 'pip install rapidocr-onnxruntime' "
            "(or reinstall vi3ion) - without it Vi3ion measures colour and geometry "
            "but reads no text."
        )
    if not by_name.get("editor_wiring", {}).get("ok"):
        actions.append(
            "Editor wiring incomplete: register the plugin and the vi3ion MCP server "
            "in ~/.config/opencode/opencode.jsonc."
        )
    if by_name.get("resources", {}).get("ok"):
        detail = by_name["resources"]["detail"]
        if "low_resource=True" in detail:
            actions.append("Low-resource mode is on: set VI3ION_LOW_RESOURCE=0 for richer evidence.")
    if local.get("vision_models"):
        actions.append(
            "A local vision model is serving: keep Vi3ion as an assistant, not the eyes."
        )
    elif not local.get("runtimes"):
        actions.append(
            "No local LLM runtime is serving: Vi3ion is the eyes for any text-only model."
        )
    return actions


def cmd_local(args: argparse.Namespace) -> int:
    """Report reachable local LLM runtimes and the recommended Vi3ion role."""
    from vi3ion.local_stack import local_stack_report

    report = local_stack_report(host=args.host, timeout=args.timeout)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    runtimes = report["runtimes"]
    if not runtimes:
        print("no local LLM runtime is currently serving on this host")
        stopped = report.get("stopped_runtimes", [])
        if stopped:
            for item in stopped:
                print(f"installed but not running: {item['name']} (port {item['port']})")
        print(f"not installed: {', '.join(report['offline_runtimes'])}")
        print(report["recommendation"])
        return 0

    for runtime in runtimes:
        print(f"{runtime['name']:<22} {runtime['host']}:{runtime['port']}  reachable")
        if runtime["base_url"]:
            print(f"{'':<22} openai-compatible: {runtime['base_url']}")
        for model in runtime["models"]:
            marker = "vision" if model in runtime["vision_models"] else "text"
            print(f"{'':<24} - {model} ({marker})")
        if runtime["error"]:
            print(f"{'':<24} note: {runtime['error']}")
    print()
    print(report["recommendation"])
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_dirs()

    ocr_status = "disabled"
    try:
        from vi3ion.core.ocr.providers import get_ocr_provider

        provider = get_ocr_provider()
        ocr_status = f"ready ({provider.name})" if provider.available else "not available"
    except Exception as exc:  # noqa: BLE001
        ocr_status = f"error: {exc}"

    payload = {
        "ok": True,
        "version": None,
        "host": settings.host,
        "port": settings.port,
        "data_dir": str(settings.data_dir),
        "db": str(settings.db_path),
        "allowed_roots": [str(r) for r in settings.allowed_roots],
        "ocr": ocr_status,
        "semantic_provider": settings.semantic_provider,
        "japan_model": settings.use_japan_model,
        "low_resource": bool(settings.low_resource),
        "analysis_max_dim": settings.analysis_max_dim,
        "image_similarity_threshold": settings.image_similarity_threshold,
    }
    if getattr(args, "tier", False):
        payload["tier"] = detect_tier(settings)
    try:
        from vi3ion import __version__

        payload["version"] = __version__
    except Exception:  # noqa: BLE001
        pass
    print(json.dumps(payload, indent=2))
    return 0


def _resolve_image_id(engine, raw: str) -> str:
    """Turn a path, vi3ion:// id, or bare image id into an image id."""
    if raw.startswith("vi3ion://"):
        return raw.removeprefix("vi3ion://")
    path = Path(raw).expanduser()
    if path.exists():
        settings = get_settings()
        if not settings.is_path_allowed(path):
            raise ValueError(
                f"path {path} is outside allowed roots "
                f"{[str(r) for r in settings.allowed_roots]}"
            )
        record, _ = engine.ingest_path(str(path))
        engine.inspect_image(image_id=record["image_id"], detail="compact")
        return record["image_id"]
    return raw


def cmd_images(args: argparse.Namespace) -> int:
    engine = _engine()
    known = engine.list_known_images(limit=args.limit)
    if args.json:
        print(json.dumps({"ok": True, "images": known}, ensure_ascii=False, indent=2))
        return 0
    if not known:
        print("no images remembered yet")
        return 0
    print(f"{'image_id':<24} {'label':<24} {'text':>5} {'size':>12}  path")
    for item in known:
        label = (item.get("label") or "-")[:24]
        size = f"{item.get('width') or '?'}x{item.get('height') or '?'}"
        print(
            f"{item['image_id']:<24} {label:<24} {item.get('text_count', 0):>5} "
            f"{size:>12}  {item.get('path') or '-'}"
        )
    return 0


def cmd_label(args: argparse.Namespace) -> int:
    engine = _engine()
    try:
        image_id = _resolve_image_id(engine, args.image)
        response = engine.remember_image(image_id=image_id, label=args.name)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(response.to_json("standard"))
    else:
        print(response.summary)
        print(f"image_id: {image_id}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    engine = _engine()
    try:
        older_id = _resolve_image_id(engine, args.older)
        newer_id = _resolve_image_id(engine, args.newer)
        response = engine.diff_images(older_id=older_id, newer_id=newer_id)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(response.to_json("standard"))
        return 0

    data = response.data
    diff = data["diff"]
    older, newer = data["older"], data["newer"]
    print(f"older: {older['image_id']}  {older.get('label') or '-'}  {older.get('path') or ''}")
    print(f"newer: {newer['image_id']}  {newer.get('label') or '-'}  {newer.get('path') or ''}")
    print(response.summary)
    if not diff.get("same_size"):
        print(
            f"note: image size changed "
            f"({older.get('width')}x{older.get('height')} -> "
            f"{newer.get('width')}x{newer.get('height')})"
        )
    changes = diff.get("changes") or []
    if args.text_only:
        changes = [c for c in changes if c["kind"] != "moved"]
    if not changes:
        print("no text/layout changes observed")
    for change in changes:
        kind = change["kind"].upper()
        region = change.get("region") or "?"
        if kind == "ADDED":
            print(f'  [{kind:<7}] {region}: "{change["new"]}"')
        elif kind == "REMOVED":
            print(f'  [{kind:<7}] {region}: "{change["old"]}"')
        else:
            print(
                f'  [{kind:<7}] {region}: "{change["old"]}" -> "{change["new"]}"'
                + (f'  ({change["detail"]})' if change.get("detail") else "")
            )
    visual = data.get("visual") or {}
    if visual.get("available"):
        print()
        print(f"pixels: {visual['changed_percent']}% differ")
        for region in visual.get("changed_regions", [])[:8]:
            bbox = region["bbox"]
            print(
                f'  [PIXELS ] {region["position"]}: '
                f"({bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]})"
            )
        if not changes and visual["changed_percent"] > 0.05:
            print("  note: pixels changed without text changes (colour/size/position)")
    print()
    for action in response.next_actions:
        print(f"next: {action}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vi3ion",
        description="Visual intelligence for AI agents: structured visual perception.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the local HTTP server (dashboard + API)")
    serve.add_argument("--host", default=None, help="bind address (default: settings.host)")
    serve.add_argument("--port", type=int, default=None, help="port (default: settings.port)")
    serve.add_argument("--log-level", default=None, help="uvicorn log level")
    serve.set_defaults(func=cmd_serve)

    analyze = sub.add_parser("analyze", help="analyse an image, print JSON summary")
    analyze.add_argument("path", nargs="?", help="path to an image, or vi3ion://<image_id>")
    analyze.add_argument(
        "--detail",
        default="standard",
        choices=["compact", "standard", "full"],
        help="evidence verbosity (default: standard)",
    )
    analyze.add_argument(
        "--context",
        default=None,
        help="user message that accompanied the image (cross-checked against code roots)",
    )
    analyze.add_argument(
        "--label",
        default=None,
        help="label to attach to the image in the image memory (e.g. 'dashboard v1')",
    )
    analyze.set_defaults(func=cmd_analyze)

    brief = sub.add_parser("brief", help="print the text-only brief for an image")
    brief.add_argument("path", help="path to an image")
    brief.add_argument("--json", action="store_true", help="emit JSON")
    brief.add_argument("--plain", action="store_true", help="omit the spatial layout table")
    brief.add_argument(
        "--budget",
        type=int,
        default=0,
        help="max tokens for the brief (0 = unlimited); use for small local models",
    )
    brief.set_defaults(func=cmd_brief)

    score = sub.add_parser("score", help="score a brief against ground truth")
    score.add_argument("path", nargs="?", default=None, help="path to an image")
    score.add_argument("--expected", default=None, help="ground-truth .expected.json")
    score.add_argument("--json", action="store_true", help="emit JSON")
    score.add_argument("--all", action="store_true", help="score every fixture in tests/fixtures")
    score.set_defaults(func=cmd_score)

    code_search = sub.add_parser("code-search", help="search source string literals to verify an OCR reading")
    code_search.add_argument("query", help="text to look for in the codebase")
    code_search.add_argument("--roots", nargs="*", default=None, help="directories to scan (default: VI3ION_CODE_ROOTS)")
    code_search.add_argument("--limit", type=int, default=5)
    code_search.set_defaults(func=cmd_code_search)

    health = sub.add_parser("health", help="print configuration and environment status")
    health.add_argument("--tier", action="store_true", help="include machine tier classification (T1/T2/T3)")
    health.set_defaults(func=cmd_health)

    local = sub.add_parser(
        "local",
        help="detect local LLM runtimes (Ollama, llama.cpp, LM Studio, vLLM, ...) and Vi3ion's role",
    )
    local.add_argument("--host", default="127.0.0.1", help="host to probe (default 127.0.0.1)")
    local.add_argument("--timeout", type=float, default=1.5, help="probe timeout in seconds")
    local.add_argument("--json", action="store_true", help="emit JSON")
    local.set_defaults(func=cmd_local)

    skill = sub.add_parser(
        "skill",
        help="print the agent skill text (paste into AGENTS.md / CLAUDE.md / .claude/skills/)",
    )
    skill.add_argument("--out", default=None, help="write the skill to this file instead")
    skill.set_defaults(func=cmd_skill)

    doctor = sub.add_parser(
        "doctor",
        help="one-shot setup check: OCR, resources, registry, local runtimes, editor wiring",
    )
    doctor.add_argument("--json", action="store_true", help="emit JSON")
    doctor.add_argument(
        "--check-updates",
        action="store_true",
        help="also hit PyPI/npm for a live update check (bypasses the 24h cache)",
    )
    doctor.set_defaults(func=cmd_doctor)

    version = sub.add_parser(
        "version",
        help="compare installed versions with the latest on PyPI (engine) and npm (plugin)",
    )
    version.add_argument("--force", action="store_true", help="bypass the 24h cache")
    version.add_argument("--timeout", type=float, default=4.0, help="network timeout in seconds")
    version.add_argument("--json", action="store_true", help="emit JSON")
    version.set_defaults(func=cmd_version)

    updates = sub.add_parser(
        "updates",
        help="show the last update check, or change the auto-update consent",
    )
    updates.add_argument("--json", action="store_true", help="emit JSON")
    updates_sub = updates.add_subparsers(dest="updates_action")
    auto = updates_sub.add_parser(
        "auto",
        help="get or set auto-update consent (on|off); omit the value to print the current state",
    )
    auto.add_argument("value", nargs="?", choices=["on", "off"], help="on or off")
    auto.add_argument("--json", action="store_true", help="emit JSON")
    auto.set_defaults(func=cmd_updates)
    updates.set_defaults(func=cmd_updates)

    mcp_check = sub.add_parser(
        "mcp-check",
        help="run a real MCP handshake against the installed server (use when an editor reports an MCP failure)",
    )
    mcp_check.add_argument("--json", action="store_true", help="emit JSON")
    mcp_check.set_defaults(func=cmd_mcp_check)

    ingest = sub.add_parser(
        "ingest",
        help="analyse every image in a folder and register it in the image memory",
    )
    ingest.add_argument("path", help="folder (or single file) to ingest")
    ingest.add_argument("--recursive", action="store_true", help="walk sub-folders")
    ingest.add_argument("--label", default=None, help="label prefix for the ingested images")
    ingest.add_argument("--limit", type=int, default=200, help="maximum images to ingest")
    ingest.add_argument("--json", action="store_true", help="emit JSON")
    ingest.set_defaults(func=cmd_ingest)

    prune = sub.add_parser(
        "prune",
        help="remove remembered images whose stored file no longer exists",
    )
    prune.add_argument("--limit", type=int, default=1000, help="maximum images to check")
    prune.add_argument("--json", action="store_true", help="emit JSON")
    prune.set_defaults(func=cmd_prune)

    images = sub.add_parser("images", help="list images Vi3ion remembers (labels + identity)")
    images.add_argument("--limit", type=int, default=100)
    images.add_argument("--json", action="store_true", help="emit JSON")
    images.set_defaults(func=cmd_images)

    label = sub.add_parser("label", help="attach a name/label to a remembered image")
    label.add_argument("image", help="image path, image id, or vi3ion://<id>")
    label.add_argument("name", help="label, e.g. 'dashboard v1'")
    label.add_argument("--json", action="store_true", help="emit JSON")
    label.set_defaults(func=cmd_label)

    diff = sub.add_parser("diff", help="compare two versions of the same screen")
    diff.add_argument("older", help="older image path, image id, or vi3ion://<id>")
    diff.add_argument("newer", help="newer image path, image id, or vi3ion://<id>")
    diff.add_argument("--json", action="store_true", help="emit structured JSON")
    diff.add_argument("--text-only", action="store_true", help="hide position-only moves")
    diff.set_defaults(func=cmd_diff)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Windows consoles often use a legacy code page (cp1252): reconfigure so
    # printing a non-ASCII character never crashes the command.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - older streams have no reconfigure
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

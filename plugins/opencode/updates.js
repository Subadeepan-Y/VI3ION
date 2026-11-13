// Update awareness for the Vi3ion OpenCode plugin: report, never surprise-install.
//
// All network reads are small, strict-timeout, and fail soft. Nothing here ever
// installs anything on its own. The only installation that happens is the engine
// upgrade, and it is always gated by the OpenCode permission prompt (the tool
// calls ctx.permission.assert first, which renders an allow/deny dialog).
//
// Consent lives in two places, kept in sync when written here:
// - plugin storage (fast, session-scoped),
// - the engine's <data_dir>/prefs.json (so the `vi3ion` CLI sees the
//   same flag, and vice versa).

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";

const PYPI_JSON_URL = "https://pypi.org/pypi/vi3ion/json";
const NPM_REGISTRY_URL =
  "https://registry.npmjs.org/@subadeepan_y%2fvi3ion-opencode";

const UPDATE_TTL_MS = 5 * 60 * 1000; // 5 minutes
const FETCH_TIMEOUT_MS = 4000;

export const UPDATE_CHECK_KEY = "vi3ion-updates";
export const UPDATE_NOTIFIED_KEY = "vi3ion-update-notified";
export const UPDATES_AUTO_KEY = "vi3ion-auto-updates";

// ---------------------------------------------------------------------------
// Version helpers
// ---------------------------------------------------------------------------

export function parseVersion(value) {
  const out = [];
  for (const part of String(value || "")
    .trim()
    .replace(/^[vV]/, "")
    .replace(/-/g, ".")
    .split(".")) {
    const digits = part.replace(/\D/g, "");
    if (!digits) break;
    out.push(Number.parseInt(digits, 10));
    if (Number.isNaN(out[out.length - 1])) out.pop();
  }
  return out;
}

export function isNewer(latest, installed) {
  if (!latest || !installed) return false;
  const a = parseVersion(latest);
  const b = parseVersion(installed);
  if (!a.length || !b.length) return latest !== installed;
  const len = Math.max(a.length, b.length);
  for (let i = 0; i < len; i += 1) {
    const x = a[i] || 0;
    const y = b[i] || 0;
    if (x > y) return true;
    if (x < y) return false;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Small utilities
// ---------------------------------------------------------------------------

export function engineDataDir() {
  const fromEnv = process.env.VI3ION_DATA_DIR;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim();
  return path.join(os.homedir(), ".vi3ion");
}

function prefsPath(dir) {
  return path.join(dir, "prefs.json");
}

function readJsonFile(file, fallback) {
  try {
    if (fs.existsSync(file)) {
      const data = JSON.parse(fs.readFileSync(file, "utf8"));
      if (data && typeof data === "object" && !Array.isArray(data)) return data;
    }
  } catch {
    /* ignore corrupt prefs/cache */
  }
  return fallback;
}

function writeJsonFileAtomic(file, data) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(data, null, 2), "utf8");
    fs.renameSync(tmp, file);
  } catch (error) {
    console.error(`[vi3ion-attach] could not write ${file}: ${error.message}`);
  }
}

export async function fetchJson(url, timeoutMs = FETCH_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { "User-Agent": "vi3ion/update-check" },
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// Installed engine version from the Python that has vi3ion installed.
export function engineVersion(pythonBin) {
  if (!pythonBin) return Promise.resolve(null);
  return new Promise((resolve) => {
    execFile(
      pythonBin,
      [
        "-c",
        "import importlib.metadata; print(importlib.metadata.version('vi3ion'))",
      ],
      { timeout: 8000, windowsHide: true },
      (err, stdout) => {
        if (err) return resolve(null);
        const v = String(stdout || "").trim();
        resolve(v || null);
      },
    );
  });
}

// ---------------------------------------------------------------------------
// The check
// ---------------------------------------------------------------------------

async function readCachedCheck(ctx) {
  const cached = await ctx.storage.get(UPDATE_CHECK_KEY).catch(() => null);
  if (!cached || typeof cached !== "object") return null;
  const checkedAt = Number(cached.checked_at_epoch) || 0;
  if (Date.now() - checkedAt > UPDATE_TTL_MS) return null;
  return cached;
}

export function pluginInstalledVersion() {
  try {
    const pkg = JSON.parse(
      fs.readFileSync(new URL("./package.json", import.meta.url), "utf8"),
    );
    return typeof pkg.version === "string" ? pkg.version : null;
  } catch {
    return null;
  }
}

export async function checkUpdates(ctx, { python, force = false } = {}) {
  if (!force) {
    const cached = await readCachedCheck(ctx);
    if (cached) return cached;
  }

  const [engineInstalled, npmLatest, pypiLatest] = await Promise.all([
    engineVersion(python),
    fetchJson(NPM_REGISTRY_URL),
    fetchJson(PYPI_JSON_URL),
  ]);

  const pypiVersion =
    pypiLatest && pypiLatest.info && typeof pypiLatest.info.version === "string"
      ? pypiLatest.info.version
      : null;
  const npmVersion =
    npmLatest && npmLatest["dist-tags"] && typeof npmLatest["dist-tags"].latest === "string"
      ? npmLatest["dist-tags"].latest
      : null;

  const pluginInstalled = pluginInstalledVersion();

  const result = {
    checked_at: new Date().toISOString(),
    checked_at_epoch: Date.now(),
    offline: !pypiVersion && !npmVersion,
    engine: {
      installed: engineInstalled,
      latest: pypiVersion,
      update_available: isNewer(pypiVersion, engineInstalled),
      command: "pip install -U vi3ion",
    },
    plugin: {
      installed: pluginInstalled,
      latest: npmVersion,
      update_available: isNewer(npmVersion, pluginInstalled),
      command: "npm i -D @subadeepan_y/vi3ion-opencode@latest",
    },
  };

  await ctx.storage.set(UPDATE_CHECK_KEY, result).catch(() => {});
  writeSharedCache(result);
  return result;
}

export function writeSharedCache(result) {
  // Mirror the report into the engine's cache file so `vi3ion version` and
  // `vi3ion doctor` show the plugin state too.
  const file = path.join(engineDataDir(), "update-check.json");
  const merged = { ...result, engine: { ...result.engine }, plugin: { ...result.plugin } };
  writeJsonFileAtomic(file, merged);
}

export function updateSummary(result) {
  if (!result) return "update check unavailable";
  const lines = [];
  for (const key of ["engine", "plugin"]) {
    const entry = result[key] || {};
    if (entry.update_available) {
      lines.push(
        `${key} ${entry.installed || "?"} -> ${entry.latest || "?"}  update: ${entry.command || ""}`,
      );
    }
  }
  if (result.offline) lines.push("offline (showing last known state)");
  return lines.join("\n") || "no updates available";
}

// ---------------------------------------------------------------------------
// Consent
// ---------------------------------------------------------------------------

export async function readAutoFlag(ctx) {
  const stored = await ctx.storage.get(UPDATES_AUTO_KEY).catch(() => null);
  if (typeof stored === "boolean") return stored;
  const prefs = readJsonFile(prefsPath(engineDataDir()), {});
  return prefs.updates_auto === true;
}

export async function writeAutoFlag(ctx, enabled) {
  const prefs = readJsonFile(prefsPath(engineDataDir()), {});
  prefs.updates_auto = enabled === true;
  writeJsonFileAtomic(prefsPath(engineDataDir()), prefs);
  await ctx.storage.set(UPDATES_AUTO_KEY, enabled === true).catch(() => {});
  return enabled === true;
}

// Vi3ion auto-attach:
//  - enabled (default) via /vi3ionon, disabled via /vi3ionoff
//  - visionless active model  -> inject full measured evidence (eyes)
//  - vision-capable active model -> inject a short assistant note: the model's
//    own vision is primary; Vi3ion is only help for exact OCR/measurements.
//    verify_claim / cross_check_text remain available on request.
//
// Config (opencode.jsonc plugins entry options):
//   mode: "auto" | "always" | "never"   (default "auto": only visionless models)
//   codeCheck: false                     (disable the context+code cross-check run)
//   maxEvidenceChars: 1400               (trim injected evidence)
//   confirmOnly: true                    (force vision-role mode even for visionless)
import { execFile, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Plugin } from "@opencode/plugin";

const IMAGE_EXT = /\.(png|jpe?g|jpeg|webp|gif|bmp|heic|avif)$/i;

// MIME -> extension for inline (clipboard/pasted) attachments.
const MIME_EXT = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/jpg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
  "image/bmp": "bmp",
  "image/avif": "avif",
  "image/heic": "heic",
  "image/heif": "heic",
};

// Provider/model signals that imply native vision. Anything not matched is
// treated as visionless (safe default: eyes provided).
const VISION_CAPABLE = [
  "anthropic", "claude",
  "openai", "gpt-4o", "gpt-5", "gpt-6", "o-series", "gpt-image",
  "google", "gemini",
  "xai", "grok",
  "qwen-vl", "qwen2.5-vl", "qwen3-vl", "qwen-vl-max", "qwen-vl-plus",
  "glm-4v", "glm-5v", "glm-v", "glm-5.3-flash", "glm-5.3", "glm-5.2",
  "minicpm", "internvl", "deepseek-vl", "deepseek-v4.1", "deepseek-v4",
  "llava", "moondream",
];

// Local runtimes (Ollama, llama.cpp, LM Studio, vLLM, Unsloth, SGLang, ...).
// Their model ids carry vision support in the name, and OpenCode usually has
// no models.dev metadata for them, so detection is name based.
const LOCAL_PROVIDERS = [
  "ollama", "lmstudio", "lm-studio", "llama-cpp", "llamacpp", "llama.cpp",
  "vllm", "sglang", "localai", "local-ai", "unsloth", "jan", "koboldcpp",
  "kobold", "text-generation-webui", "oobabooga", "llamafile", "mlx",
  "lmstudio-community",
];

// URL fragments that mean "a local GPU exposed over the network".
const LOCAL_URL_MARKERS = [
  "localhost",
  "127.0.0.1",
  "0.0.0.0",
  "::1",
  ".unsloth.app",
  "trycloudflare.com",
  "ngrok.io",
  "ngrok-free.app",
  "loca.lt",
  "serveo.net",
];

const LOCAL_VISION_HINTS = [
  "llava", "bakllava", "llava-next", "nanollava", "moondream", "minicpm-v",
  "qwen2-vl", "qwen2.5-vl", "qwen2.5vl", "qwen3-vl", "qwen3vl", "qwen2-vl",
  "gemma3", "gemma-3", "llama3.2-vision", "llama-3.2-vision", "llama3.2v",
  "internvl", "idefics", "pixtral", "phi3-vision", "phi-3.5-vision",
  "granite-vision", "smolvlm", "molmo", "cogvlm", "ernie-4.5-vl", "step-1v",
  "hunyuan-vision", "kimi-vl", "em-3", "molmo-7b",
];

// ---------------------------------------------------------------------------
// Paths: nothing here may assume a particular machine.
// ---------------------------------------------------------------------------

// Where Vi3ion keeps its data. Resolution order:
//   1. VI3ION_DATA_DIR in the environment
//   2. the data dir configured for the Vi3ion MCP server in the editor config
//      (so the plugin and the MCP server never split the registry)
//   3. ~/.vi3ion
let dataDirCache = null;

function dataDir() {
  if (dataDirCache) return dataDirCache;
  const configured = process.env.VI3ION_DATA_DIR;
  if (configured && configured.trim()) {
    dataDirCache = path.resolve(configured.trim());
    return dataDirCache;
  }
  const fromConfig = mcpDataDirFromConfig();
  if (fromConfig) {
    dataDirCache = fromConfig;
    return dataDirCache;
  }
  dataDirCache = path.join(os.homedir(), ".vi3ion");
  return dataDirCache;
}

// Read VI3ION_DATA_DIR out of the editor's MCP registration for vi3ion.
function mcpDataDirFromConfig() {
  try {
    const home = process.env.USERPROFILE || os.homedir();
    const files = [
      path.join(home, ".config", "opencode", "opencode.jsonc"),
      path.join(home, ".config", "opencode", "opencode.json"),
      path.join(home, "opencode.json"),
    ];
    for (const file of files) {
      if (!fs.existsSync(file)) continue;
      const parsed = parseJsonc(fs.readFileSync(file, "utf8"));
      const servers = (parsed && (parsed.mcp?.servers || parsed.mcp)) || {};
      // The key may be "vi3ion" or "VI3ION" — the display name is the user's
      // choice, so match either.
      const key = Object.keys(servers || {}).find(
        (name) => name.trim().toLowerCase() === "vi3ion",
      );
      const entry = key ? servers[key] : null;
      const env = entry && (entry.environment || entry.env) ? (entry.environment || entry.env) : null;
      const value = env && (env.VI3ION_DATA_DIR || env.vi3ion_data_dir);
      if (value && String(value).trim() && !String(value).includes("~")) {
        return path.resolve(String(value).trim());
      }
      if (value && String(value).trim().startsWith("~")) {
        return path.join(os.homedir(), String(value).trim().slice(1));
      }
    }
  } catch {
    // config unreadable: fall back to the default
  }
  return null;
}

const INBOX_DIR = path.join(dataDir(), "inbox");

const PLUGIN_DIR = path.dirname(fileURLToPath(import.meta.url));

// The plugin lives in a repo checkout during development (plugins/opencode/),
// in node_modules when published, or behind a compatibility shim. The repo
// root is found by looking for pyproject.toml upwards - never hardcoded.
function findRepoRoot(start) {
  let current = start;
  for (let depth = 0; depth < 6; depth += 1) {
    if (fs.existsSync(path.join(current, "pyproject.toml"))) return current;
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return null;
}

const REPO_DIR = findRepoRoot(PLUGIN_DIR) || path.resolve(PLUGIN_DIR, "..");

function hasVi3ion(bin) {
  try {
    const res = spawnSync(bin, ["-c", "import vi3ion"], { timeout: 3000, windowsHide: true });
    return res.status === 0;
  } catch {
    return false;
  }
}

// Python that has Vi3ion installed. Resolution order:
//   1. VI3ION_PYTHON (explicit)
//   2. Repo or workspace .venv
//   3. python3 / python on PATH, verified with `import vi3ion`
//   4. nothing -> auto-analysis is disabled with a clear message
let pythonCache = null;

function candidatePythons() {
  const candidates = [];
  if (process.env.VI3ION_PYTHON && process.env.VI3ION_PYTHON.trim()) {
    candidates.push(process.env.VI3ION_PYTHON.trim());
  }
  const venvRel = process.platform === "win32" ? path.join(".venv", "Scripts", "python.exe") : path.join(".venv", "bin", "python");
  candidates.push(path.join(REPO_DIR, venvRel));
  if (process.platform === "win32") {
    candidates.push("python", "python3");
  } else {
    candidates.push("python3", "python");
  }
  return candidates;
}

function pythonPath() {
  if (pythonCache) return pythonCache;
  const configured = process.env.VI3ION_PYTHON && process.env.VI3ION_PYTHON.trim();
  if (configured) {
    if (hasVi3ion(configured)) {
      pythonCache = configured;
      return pythonCache;
    }
  }
  for (const candidate of candidatePythons()) {
    const found = findOnPath(candidate);
    if (found && hasVi3ion(found)) {
      pythonCache = found;
      return pythonCache;
    }
  }
  // Development checkout: the repo's own venv usually has Vi3ion installed.
  // Derived from the plugin location, never a hardcoded path.
  try {
    const candidates = [];
    if (process.platform === "win32") {
      candidates.push(
        path.join(REPO_DIR, ".venv", "Scripts", "python.exe"),
        path.join(REPO_DIR, ".venv", "bin", "python"),
      );
    } else {
      candidates.push(
        path.join(REPO_DIR, ".venv", "bin", "python"),
        path.join(REPO_DIR, ".venv", "Scripts", "python.exe"),
      );
    }
    for (const candidate of candidates) {
      if (fs.existsSync(candidate) && hasVi3ion(candidate)) {
        pythonCache = candidate;
        return pythonCache;
      }
    }
  } catch {
    // no repo venv
  }
  pythonCache = "";
  return pythonCache;
}

// Resolve an executable on PATH (Windows needs the extension search).
function findOnPath(name) {
  if (name.includes(path.sep) || name.includes("/")) {
    return fs.existsSync(name) ? name : null;
  }
  const pathVar = process.env.PATH || "";
  const separator = process.platform === "win32" ? ";" : ":";
  const extensions =
    process.platform === "win32"
      ? (process.env.PATHEXT || ".EXE;.CMD;.BAT").split(";").filter(Boolean)
      : [""];
  for (const dir of pathVar.split(separator)) {
    if (!dir) continue;
    for (const extension of extensions) {
      const candidate = path.join(dir, name + extension);
      try {
        if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
      } catch {
        // unreadable directory entry
      }
    }
  }
  return null;
}

// PLUGIN_DIR and REPO_DIR defined above

// Attachments reach the plugin in two shapes:
//   - prompt hook:  { uri, source?, name? }          (no mime, no bytes)
//   - message part: { data, mime, source, name }     (mime + bytes present)
// Everything is resolved through these helpers so both shapes work.
function isImageAttachment(file) {
  if (!file) return false;
  const mime = String(file.mime || "").toLowerCase();
  if (mime.startsWith("image/")) return true;
  const uri = String(file.uri || attachmentUri(file) || "");
  if (IMAGE_EXT.test(uri)) return true;
  if (uri.startsWith("data:image/")) return true;
  const source = file.source || {};
  if (source.type === "uri" && IMAGE_EXT.test(String(source.uri || ""))) return true;
  return false;
}

// The real file URI may sit in `source.uri` (V2) or in `uri` (older hosts).
function attachmentUri(file) {
  if (!file) return "";
  const source = file.source || {};
  if (source.type === "uri" && source.uri) return String(source.uri);
  return file.uri ? String(file.uri) : "";
}

// Bytes of an attachment: base64 `data`, or a data: URI.
function attachmentBytes(file) {
  if (!file) return null;
  if (file.data) {
    try {
      const buffer = Buffer.from(file.data, "base64");
      if (buffer.length) return buffer;
    } catch {
      // fall through
    }
  }
  const uri = String(file.uri || attachmentUri(file) || "");
  if (uri.startsWith("data:image/")) {
    const comma = uri.indexOf(",");
    if (comma > 0) {
      try {
        const buffer = Buffer.from(uri.slice(comma + 1), "base64");
        if (buffer.length) return buffer;
      } catch {
        // fall through
      }
    }
  }
  return null;
}

// Content hash: the identity of an image regardless of how it arrived.
function attachmentHash(file) {
  const bytes = attachmentBytes(file);
  if (bytes) return createHash("sha256").update(bytes).digest("hex").slice(0, 16);
  const uri = attachmentUri(file);
  if (uri) return createHash("sha256").update(uri).digest("hex").slice(0, 16);
  return "";
}

// Resolve an attachment to a real file on disk. Inline bytes (clipboard
// paste) are written to the Vi3ion inbox first.
async function materializeAttachment(file) {
  const mime = String(file.mime || "image/png").toLowerCase();
  const bytes = attachmentBytes(file);
  const hash = attachmentHash(file);

  if (bytes && bytes.length) {
    const ext = MIME_EXT[mime] || "png";
    const name =
      file.name && /\.[A-Za-z0-9]+$/.test(file.name)
        ? file.name
        : `clipboard-${hash}.${ext}`;
    const target = path.join(INBOX_DIR, `${hash}-${name}`);
    await mkdir(INBOX_DIR, { recursive: true });
    await writeFile(target, bytes);
    return { path: target, name, hash, bytes: bytes.length };
  }

  const filePath = fileUriToPath(attachmentUri(file));
  if (filePath) {
    return { path: filePath, name: path.basename(filePath), hash, bytes: 0 };
  }
  return null;
}

function isVisionCapable(model) {
  if (!model) return false;
  // Authoritative: OpenCode knows the model's input modalities.
  const input = model.capabilities && model.capabilities.input;
  if (Array.isArray(input) && input.length) {
    if (input.some((m) => String(m).toLowerCase().startsWith("image"))) return true;
  }
  const s = `${model.providerID || ""} ${model.id || ""} ${model.modelID || ""} ${model.name || ""}`.toLowerCase();
  // Local runtimes are checked first: a local OpenAI-compatible server is
  // usually registered under a generic provider id ("openai", "custom") and
  // would otherwise be mistaken for a cloud vision model.
  if (isLocalModel(model)) {
    return LOCAL_VISION_HINTS.some((k) => s.includes(k));
  }
  return VISION_CAPABLE.some((k) => s.includes(k.toLowerCase()));
}

// Local inference runtimes get a dedicated evidence profile: they are usually
// small-context and RAM-bound, so evidence must stay compact and cheap.
function isLocalModel(model) {
  if (!model) return false;
  const s = `${model.providerID || ""} ${model.id || ""} ${model.modelID || ""}`.toLowerCase();
  if (LOCAL_PROVIDERS.some((k) => s.includes(k))) return true;
  const base = model.baseURL || model.baseUrl || model.options?.baseURL || "";
  if (typeof base === "string" && LOCAL_URL_MARKERS.some((m) => base.toLowerCase().includes(m))) {
    return true;
  }
  return false;
}

async function shouldApply(ctx, mode) {
  if (mode === "always") return true;
  if (mode === "never") return false;
  try {
    const def = await resolveModel(ctx);
    return !def || !isVisionCapable(def);
  } catch {
    return true;
  }
}

// Catalog entry for a provider/model pair. The full model list carries the
// capabilities and limits that a bare { providerID, id } reference lacks.
async function catalogModel(ctx, providerID, id) {
  if (!id) return null;
  try {
    const list = await ctx.model.list();
    const items = (list && list.data) || list || [];
    const matches = (m) => m && (m.id === id || m.modelID === id);
    return items.find((m) => matches(m) && m.providerID === providerID) || items.find(matches) || null;
  } catch {
    return null;
  }
}

// The model a session will answer with. Prompt hooks carry no model on current
// hosts, and ctx.model.default() is the configuration default: it stays put
// when the user picks another model in the session.
async function sessionModel(ctx, sessionID) {
  if (!sessionID) return null;
  const get = ctx.session && ctx.session.get;
  if (!get) return null;
  try {
    const session = await get({ sessionID });
    const info = session && ((session.data && session.data.model) || session.model);
    if (!info || (!info.id && !info.modelID)) return null;
    return {
      id: info.id || info.modelID,
      providerID: info.providerID || "",
      name: info.name || "",
      capabilities: info.capabilities || null,
      limit: info.limit || null,
      baseURL: info.baseURL || info.baseUrl || (info.options && info.options.baseURL) || "",
    };
  } catch {
    return null;
  }
}

// Normalise the many shapes OpenCode uses for a model reference into one
// object with: id, providerID, capabilities.input, limit.context.
// ctx.model.default() may return { location, data } (API), { providerID,
// modelID } (editor) or a bare ModelInfo.
async function resolveModel(ctx, event) {
  const pick = (raw) => {
    if (!raw) return null;
    const info = raw.data && raw.data.id ? raw.data : raw;
    if (!info || (!info.id && !info.modelID)) return null;
    return {
      id: info.id || info.modelID,
      providerID: info.providerID || "",
      name: info.name || "",
      capabilities: info.capabilities || null,
      limit: info.limit || null,
      baseURL: info.baseURL || info.baseUrl || (info.options && info.options.baseURL) || "",
    };
  };

  // A session reference is just { providerID, id }, so fill in the catalog
  // metadata and the provider endpoint before handing it to the caller.
  const complete = async (model) => {
    const full = await catalogModel(ctx, model.providerID, model.id);
    if (full) {
      const info = pick(full);
      model.name = model.name || info.name;
      model.capabilities = model.capabilities || info.capabilities;
      model.limit = model.limit || info.limit;
      if (!model.baseURL) model.baseURL = info.baseURL;
    }
    if (!model.baseURL) model.baseURL = await providerBaseURL(ctx, model.providerID);
    return model;
  };

  // 1. The request event names the model that serves this call.
  if (event && event.model) {
    const fromEvent = pick(event.model);
    if (fromEvent) return complete(fromEvent);
  }

  // 2. The session's selected model. A new model is introduced when the user
  //    switches mid-chat, so this must win over the configuration default.
  const fromSession = await sessionModel(ctx, event && event.sessionID);
  if (fromSession) return complete(fromSession);

  // 3. Configuration default, for calls with no session model yet.
  try {
    const picked = pick(await ctx.model.default());
    if (picked) return complete(picked);
  } catch {
    // fall through
  }

  return null;
}

// Strip comments and trailing commas so JSONC config files can be parsed.
function parseJsonc(text) {
  const stripped = text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'\\])\/\/[^\n]*/g, "$1");
  return JSON.parse(stripped.replace(/,(\s*[}\]])/g, "$1"));
}

// Find the base URL of a provider so local runtimes can be detected even when
// the provider has a custom id (e.g. a local GPU behind a tunnel).
const providerUrlCache = new Map();

async function providerBaseURL(ctx, providerID) {
  if (!providerID) return "";
  if (providerUrlCache.has(providerID)) return providerUrlCache.get(providerID);
  let found = "";
  try {
    const provider = await ctx.provider.get(providerID);
    const settings = provider && (provider.settings || provider.options);
    found =
      (settings && (settings.baseURL || settings.baseUrl)) ||
      (provider && (provider.baseURL || provider.baseUrl)) ||
      (provider && provider.options && provider.options.baseURL) ||
      "";
    if (found) found = String(found);
  } catch {
    // provider API not available
  }
  if (!found) {
    try {
      const files = [
        path.join(process.env.USERPROFILE || "", ".config", "opencode", "opencode.jsonc"),
        path.join(process.env.USERPROFILE || "", ".config", "opencode", "opencode.json"),
        path.join(process.env.USERPROFILE || "", "opencode.json"),
      ];
      for (const file of files) {
        const raw = await readFile(file, "utf8").catch(() => null);
        if (!raw) continue;
        const parsed = parseJsonc(raw);
        const entry = parsed && parsed.provider && parsed.provider[providerID];
        const url = entry && entry.options && entry.options.baseURL;
        if (url) {
          found = String(url);
          break;
        }
      }
    } catch {
      // config unreadable
    }
  }
  providerUrlCache.set(providerID, found);
  return found;
}

async function activeModel(ctx, event) {
  // The prompt event carries the active model when available; fall back to the
  // context default so the intro never shows "?/?".
  return resolveModel(ctx, event);
}

function confirmInstruction(fileName) {
  return [
    `<context key="vi3ion-confirm" title="Vi3ion assistant: ${fileName}">`,
    "Your own vision is primary and better than Vi3ion for understanding this image.",
    "Vi3ion is available as an assistant if you want a second reading: exact OCR of",
    "small text (cross_check_text), pixel coordinates, or measured colour/geometry",
    "(verify_claim / inspect_region). Its output is data to help you, not a verdict",
    "that overrides your own judgement.",
    "</context>",
  ].join("\n");
}

// First-prompt introduction. It asks the agent to self-assess its vision and
// gives a protocol for both cases, so the role does not depend on model-name
// detection alone.
function introInstruction(model, vision, compactTier, changeNote) {
  const role = vision ? "VISION-CAPABLE (detected)" : "VISIONLESS (detected)";
  const modelName = model ? `${model.providerID || "?"}/${model.id || "?"}` : "unknown";
  const local = isLocalModel(model);
  const lines = [
    `<context key="vi3ion-intro" title="Vi3ion: visual perception layer">`,
    "Vi3ion is loaded in this conversation. It is a local, deterministic perception",
    "layer (OCR + geometry + colour + image memory) available as MCP tools and as",
    "auto-attached evidence blocks.",
    "",
  ];
  if (changeNote) {
    lines.push(changeNote, "");
  }
  if (local) {
    lines.push(
      "Active model runs on a LOCAL runtime (Ollama / llama.cpp / LM Studio / vLLM /",
      "Unsloth / SGLang / LocalAI / jan / koboldcpp). It is fast and private, and it may",
      "have no image input at all: assume it is blind to pixels unless the model name",
      "clearly says otherwise (llava, qwen2.5-vl, minicpm-v, gemma3, ...).",
      "Use detail=\"compact\" evidence to keep the context small.",
      "",
    );
  }
  lines.push(
    "Before your first answer, answer these internally:",
    "1. Do I have native vision, or am I blind to image pixels?",
    "2. Are Vi3ion tools available (inspect_image, inspect_region, verify_claim,",
    "   cross_check_text, list_images, remember_image, diff_images)?",
    `3. Is my context budget small (<32K tokens)? Vi3ion will then use compact evidence${compactTier ? " (this session: compact)" : ""}.`,
    "",
    `Model detected as: ${modelName}. Vi3ion role hint: ${role}.`,
    "Treat detection as a hint; your own answer to question 1 wins.",
    "If you are unsure, treat yourself as visionless (safe default) and say so briefly.",
    "",
    "If you are VISIONLESS:",
    "- Vi3ion is your eyes. Never claim what an image shows from its filename or memory.",
    "- When an image is attached, Vi3ion analyses it and the measured evidence is",
    "  attached to this request. That block IS the image: read it as the image.",
    "- Do not call inspect_image again for an image that already has a Vi3ion block.",
    "- Use verify_claim for exact text/geometry/colour claims and cross_check_text",
    "  for uncertain OCR.",
    "- Name screens with remember_image and compare versions with diff_images.",
    "If you are VISION-CAPABLE:",
    "- You are the lead: your own vision is primary and better than Vi3ion.",
    "- Vi3ion is an assistant on request: exact OCR/cross-check, pixel coordinates,",
    "  measured colour/geometry. It never overrides your judgement.",
    "- When evidence mentions similar_images, ask the user whether it is the same",
    "  screen before treating it as a version.",
    "",
    "In both roles: Vi3ion evidence is observed data, uncertainty is marked, and",
    "you must not invent what was not observed.",
    "</context>",
  );
  return lines.join("\n");
}

// Notice for the case where the active model changed inside a session: the
// new model has never seen Vi3ion and must not work blind to its existence.
function roleChangeNotice(currentKey, previousKey, vision) {
  const role = vision
    ? "your own vision is primary; Vi3ion is available as an assistant for exact OCR and measurements"
    : "Vi3ion is your eyes: image claims need Vi3ion evidence (never guess from a filename)";
  return [
    `Vi3ion role update: the active model changed in this session (now ${currentKey}, was ${previousKey}).`,
    `This model was not present when Vi3ion was introduced, so state the role now: ${role}.`,
    "Vi3ion tools: inspect_image, inspect_region, verify_claim, cross_check_text,",
    "list_images, remember_image, diff_images.",
  ].join(" ");
}

// Compact presence block injected into every model request (context) and into
// compaction summaries, so Vi3ion is never lost after history is summarised.
function presenceInstruction(vision, local) {
  const memory =
    "Image memory is available: list_images, remember_image and diff_images for screen versions.";
  if (vision) {
    const local_note = local
      ? "This model runs on a local runtime: it is fast and private, but small context — keep answers short."
      : "";
    return [
      "Vi3ion presence: active as a visual assistant in this session.",
      "Your own vision is primary. Use Vi3ion (verify_claim / cross_check_text",
      "inspect_region) when you want a second reading: exact OCR, pixel",
      "coordinates, or measured colour/geometry. It never overrides your judgement.",
      local_note,
      memory,
      "Keep this role in mind in summaries.",
    ]
      .filter(Boolean)
      .join(" ");
  }
  const local_note = local
    ? "This model runs on a local runtime and may have no image input: Vi3ion's compact evidence is the only source of image facts."
    : "";
  return [
    "Vi3ion presence: active as your eyes in this session.",
    "You have no native vision here: image claims require Vi3ion evidence",
    "(inspect_image / auto-injected blocks / verify_claim). Never guess from a",
    "filename or memory.",
    local_note,
    memory,
    "Keep this role in mind in summaries.",
  ]
    .filter(Boolean)
    .join(" ");
}

function missingMcpNotice(status = "not registered") {
  return [
    `Vi3ion notice: the Vi3ion MCP server is ${status} in this session.`,
    "Interactive inspection tools (inspect_image, inspect_region, verify_claim, cross_check_text, remember_image, diff_images) are unavailable, so image questions cannot be answered with measurements.",
    "The plugin is retrying the connection; if it does not come back, restart the editor (MCP servers are spawned at startup) and check the MCP entry.",
  ].join(" ");
}

// Live status of the Vi3ion MCP server, as OpenCode sees it.
// `event.tools` can still list tools from a server that has since died, so
// the authoritative signal is the server status.
async function vi3ionMcpStatus(ctx) {
  const unknown = { found: false, status: "unknown", raw: "", name: "" };
  try {
    if (!ctx.mcp || typeof ctx.mcp.list !== "function") return unknown;
    const listed = await ctx.mcp.list();
    const servers = (listed && listed.data) || listed || [];
    for (const server of servers) {
      if (!server || !isVi3ionServerName(server.name)) continue;
      const raw = server.status;
      let status = "unknown";
      if (typeof raw === "string") {
        status = raw;
      } else if (raw && typeof raw === "object") {
        status = String(raw.state || raw.status || raw._tag || "unknown");
      }
      return { found: true, status, raw: safeText(raw), name: server.name };
    }
    return { found: false, status: "missing", raw: "", name: "" };
  } catch (err) {
    return { found: false, status: "unknown", raw: safeText(String(err)), name: "" };
  }
}

// The MCP server may be registered as "vi3ion" or "VI3ION" (the key is the
// user's choice; only the display differs). Match either.
function isVi3ionServerName(name) {
  return typeof name === "string" && name.trim().toLowerCase() === "vi3ion";
}

// JSON that can never throw and never returns undefined.
function safeText(value) {
  try {
    const text = JSON.stringify(value);
    return typeof text === "string" ? text : String(text);
  } catch {
    return "";
  }
}

// Bring a dead MCP server back.
//   1. reload the MCP config
//   2. re-set the server entry: OpenCode restarts a server when its
//      configuration changes, but not when the config is merely reloaded
async function respawnMcpServer(ctx, serverName) {
  if (!ctx.mcp || typeof ctx.mcp.reload !== "function") return false;
  await ctx.mcp.reload();
  try {
    if (ctx.mcp.transform && typeof ctx.mcp.transform === "function") {
      await ctx.mcp.transform((editor) => {
        const name =
          serverName ||
          Object.keys(editor.list() || {}).find((key) =>
            isVi3ionServerName(key),
          );
        if (!name) return;
        const config = editor.get(name);
        if (!config) return;
        // A real change is what makes OpenCode restart a server; re-setting an
        // identical config is a no-op.
        editor.update(name, (current) => {
          if (current && typeof current === "object") {
            current.disabled = false;
          }
        });
      });
      return true;
    }
  } catch (error) {
    console.error(`[vi3ion-attach] MCP re-registration failed: ${error && error.message}`);
  }
  return false;
}

// Bring a dead Vi3ion MCP server back without an editor restart.
// MCP servers are spawned when the editor starts; if one dies (an upgrade
// replaced it, it was killed), OpenCode does not retry on its own.
async function reloadMcpIfStale(ctx) {
  const now = Date.now();
  const last = Number(await ctx.storage.get(MCP_RELOAD_KEY)) || 0;
  if (now - last < 60000) return false;
  try {
    await ctx.storage.set(MCP_RELOAD_KEY, now);
  } catch {
    // storage may be unavailable
  }
  try {
    if (ctx.mcp && typeof ctx.mcp.reload === "function") {
      await respawnMcpServer(ctx, status.name);
      console.error("[vi3ion-attach] Vi3ion MCP tools missing: asked OpenCode to restart the MCP servers");
      return true;
    }
  } catch (error) {
    console.error(`[vi3ion-attach] MCP reload failed: ${error && error.message}`);
  }
  return false;
}

function fileUriToPath(uri) {
  if (typeof uri !== "string") return null;
  let p = uri;
  if (p.startsWith("file://")) {
    p = p.slice(7);
    try {
      p = decodeURIComponent(p);
    } catch {
      // keep raw
    }
  }
  // file:///D:/... -> D:\... on Windows
  if (/^\/[A-Za-z]:\//.test(p)) p = p.slice(1);
  if (process.platform === "win32") p = p.replaceAll("/", "\\");
  return p || null;
}

function runPython(args, timeoutMs, envOverride) {
  return new Promise((resolve) => {
    const python = pythonPath();
    if (!python) {
      console.error(
        "[vi3ion-attach] no Python with Vi3ion found. Install it with " +
          "'pip install vi3ion' or set VI3ION_PYTHON.",
      );
      return resolve(null);
    }
    execFile(
      python,
      args,
      {
        timeout: timeoutMs,
        windowsHide: true,
        cwd: process.cwd(),
        maxBuffer: 32 * 1024 * 1024,
        env: envOverride || vi3ionEnv(),
      },
      (err, stdout, stderr) => {
        if (err) {
          console.error(`[vi3ion-attach] python failed (${args[1]}): ${err.message}`);
          if (stderr) console.error("[vi3ion-attach] stderr:", stderr.slice(0, 500));
          return resolve(null);
        }
        resolve(stdout);
      },
    );
  });
}

// Child-process environment: make sure the inbox (clipboard images) is inside
// the allowed roots and that code cross-check roots default to the workspace.
// Local runtimes get low-resource mode: the Japanese recognizer and the extra
// CJK pass are dropped, which cuts ~35% of the analysis time and RAM.
function vi3ionEnv(extra) {
  const env = { ...process.env, ...(extra || {}) };
  // The plugin and the CLI child must use the same store.
  env.VI3ION_DATA_DIR = dataDir();
  if (!env.VI3ION_CODE_ROOTS) {
    env.VI3ION_CODE_ROOTS = workspaceDir();
  }
  if (env.VI3ION_LOW_RESOURCE === undefined && env.VI3ION_LOCAL === "1") {
    env.VI3ION_LOW_RESOURCE = "1";
  }
  const roots = (env.VI3ION_ALLOWED_ROOTS || "")
    .split(";")
    .map((r) => r.trim())
    .filter(Boolean);
  for (const extra_root of [workspaceDir(), dataDir(), INBOX_DIR]) {
    if (extra_root && !roots.some((r) => r.toLowerCase() === extra_root.toLowerCase())) {
      roots.push(extra_root);
    }
  }
  env.VI3ION_ALLOWED_ROOTS = roots.join(";");
  return env;
}

// The workspace the agent is working in (the directory of the session), used
// for code cross-check roots. Never a hardcoded path.
let workspaceOverride = null;

function workspaceDir() {
  if (workspaceOverride) return workspaceOverride;
  try {
    return process.cwd();
  } catch {
    return os.homedir();
  }
}

function setWorkspaceDir(directory) {
  if (directory) workspaceOverride = String(directory);
}

// Hard ceiling so admission never blocks forever even if a subprocess wedges.
async function withTimeout(promise, ms, label) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((resolve) => {
        timer = setTimeout(() => {
          console.error(`[vi3ion-attach] ${label} timed out after ${ms}ms`);
          resolve(null);
        }, ms);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function runBrief(img, budgetTokens, local) {
  const args = ["-m", "vi3ion.cli", "brief", img, "--json"];
  if (budgetTokens > 0) args.push("--budget", String(budgetTokens));
  const stdout = await runPython(args, 240000, vi3ionEnv(local ? { VI3ION_LOCAL: "1" } : null));
  if (!stdout) return { text: null, layout: "" };
  try {
    const j = JSON.parse(stdout);
    return { text: j.text, layout: j.layout || "", tokens: j.tokens, truncated: j.truncated };
  } catch {
    return { text: stdout.trim() || null, layout: "" };
  }
}

async function runAnalyzeWithContext(img, text, label, local) {
  const args = ["-m", "vi3ion.cli", "analyze", img, "--detail", "compact"];
  if (text && text.trim()) args.push("--context", text.trim());
  if (label) args.push("--label", label);
  const stdout = await runPython(args, 240000, vi3ionEnv(local ? { VI3ION_LOCAL: "1" } : null));
  if (!stdout) return null;
  try {
    return JSON.parse(stdout);
  } catch {
    return null;
  }
}

// Local runtime report (Ollama / llama.cpp / LM Studio / vLLM, ...). Used by
// /vi3ionstatus so the user can see which local model to pair with Vi3ion.
async function runLocalStack() {
  const stdout = await runPython(["-m", "vi3ion.cli", "local", "--json"], 20000);
  if (!stdout) return null;
  try {
    return JSON.parse(stdout);
  } catch {
    return null;
  }
}

async function runDiff(older, newer) {
  const stdout = await runPython(
    ["-m", "vi3ion.cli", "diff", older, newer, "--json"],
    240000,
    vi3ionEnv(),
  );
  if (!stdout) return null;
  try {
    return JSON.parse(stdout);
  } catch {
    return null;
  }
}

function formatDiff(diff, olderName, newerName) {
  const parts = [];
  parts.push(`<context key="vi3ion-diff" title="Version comparison: ${olderName} -> ${newerName}">`);
  if (!diff || !diff.data || !diff.data.diff) {
    parts.push("Vi3ion could not compare these images. Do not guess what changed.");
    parts.push("</context>");
    return parts.join("\n");
  }
  const d = diff.data.diff;
  parts.push(
    `${diff.summary || `${d.change_count} change(s)`} ` +
      `(layout ${Math.round(d.layout_similarity * 100)}%, text ${Math.round(d.text_similarity * 100)}%)`,
  );
  const changes = (d.changes || []).slice(0, 15);
  if (!changes.length) {
    parts.push("No text or layout changes were observed between the two versions.");
  } else {
    parts.push(`Observed changes (${d.change_count}):`);
    for (const c of changes) {
      const region = c.region || "?";
      if (c.kind === "added") parts.push(`- added [${region}]: "${c.new}"`);
      else if (c.kind === "removed") parts.push(`- removed [${region}]: "${c.old}"`);
      else parts.push(`- ${c.kind} [${region}]: "${c.old}" -> "${c.new}"`);
    }
    if (d.change_count > changes.length) {
      parts.push(`… ${d.change_count - changes.length} more change(s) not shown.`);
    }
  }
  // Pixel comparison catches changes that carry no text (colour, spacing).
  const visual = diff.data.visual;
  if (visual && visual.available) {
    parts.push(
      `Pixel comparison: ${visual.changed_percent}% of pixels differ` +
        (visual.changed_region_count
          ? ` in ${visual.changed_region_count} area(s)` +
            ` (${visual.changed_regions.slice(0, 4).map((r) => `${r.position} @${r.bbox.join(",")}`).join("; ")})`
          : "") +
        ".",
    );
    if (!changes.length && visual.changed_percent > 0.05) {
      parts.push(
        "The pixels changed but no text changed: look for a colour, size or position change " +
          "in the listed areas, and ask the user to confirm.",
      );
    }
  }
  parts.push(
    "These are observed OCR/layout differences, not confirmed product changes. " +
      "Confirm identity (same screen?) and verify each change against the code or commit diff before reporting.",
  );
  parts.push("</context>");
  return parts.join("\n");
}

// Analyse the images of the newest user message and build the evidence text.
//
// The attachment arrives on the message (mime + bytes), so this is the only
// place where clipboard images and file attachments can both be resolved.
// Returns null when there is nothing new to analyse.
async function analyseMessageImages(ctx, event, model, vision, options) {
  const { images, text } = imagesFromMessages(event.messages);
  if (!images.length) return null;

  const state = (await ctx.storage.get(EV_STATE_KEY)) || {};
  const sessionState = state[event.sessionID] || { hashes: [], blocks: [] };
  const hashes = new Set(sessionState.hashes || []);

  const maxImages = options.maxImagesPerTurn || 6;
  const fresh = [];
  for (const image of images.slice(0, maxImages)) {
    const hash = attachmentHash(image);
    if (hash && hashes.has(hash)) continue;
    const resolved = await materializeAttachment(image);
    if (!resolved) continue;
    fresh.push({ ...resolved, hash });
    if (hash) hashes.add(hash);
  }

  if (!fresh.length) return null;

  const tier = await tierFor(ctx, model);
  const budget = await evidenceBudget(ctx, model, tier);
  const maxChars =
    budget > 0 ? Math.max(400, budget * 4) : options.maxEvidenceChars || 1400;
  const local = isLocalModel(model);
  const wantAnalyze =
    options.codeCheck === true || (options.codeCheck !== false && !local);

  const blocks = [];
  const analysed = [];

  for (const item of fresh) {
    if (vision) {
      // Assistant mode: no heavy OCR, the image goes to the vision model.
      blocks.push(confirmInstruction(item.name));
      continue;
    }
    const [brief, analysis] = await Promise.all([
      withTimeout(runBrief(item.path, budget, local), options.analyzeTimeoutMs || 240000, "brief"),
      wantAnalyze
        ? withTimeout(
            runAnalyzeWithContext(
              item.path,
              text,
              path.basename(item.name, path.extname(item.name)),
              local,
            ),
            options.analyzeTimeoutMs || 240000,
            "analyze",
          )
        : Promise.resolve(null),
    ]);
    blocks.push(formatEvidence(brief, analysis, item.name, maxChars, tier));
    analysed.push(item);
  }

  // Two images at once: compare them (the analysis is cached, so this is cheap).
  if (!vision && analysed.length === 2 && options.autoDiff !== false) {
    const [older, newer] = analysed;
    const diff = await withTimeout(
      runDiff(older.path, newer.path),
      options.analyzeTimeoutMs || 240000,
      "diff",
    );
    if (diff) blocks.push(formatDiff(diff, older.name, newer.name));
  }

  state[event.sessionID] = {
    hashes: [...hashes].slice(-40),
    blocks,
    updated: Date.now(),
  };
  await ctx.storage.set(EV_STATE_KEY, state);
  return { blocks, text };
}

// Compress each layout row to one line: `TOP "SUBADEEPAN" @88,24,274,54`.
function compactLayout(layout) {  if (!layout) return "";
  return layout
    .split("\n")
    .filter((line) => line.startsWith("|") && !line.startsWith("| Region") && !line.startsWith("|---|---"))
    .map((line) => {
      const cells = line.split("|").map((c) => c.trim()).filter(Boolean);
      if (cells.length < 4) return line;
      const [, region, text, box, pos] = cells;
      return `${region} ${text} @${box.slice(1, -1)} (${pos})`;
    })
    .join("\n");
}

function formatEvidence(brief, analysis, fileName, maxChars, tier) {
  const parts = [];
  parts.push(`<context key="vi3ion-auto" title="Image analysis: ${fileName}">`);
  const briefText = typeof brief === "string" ? brief : (brief && brief.text) || null;
  const layout = (brief && brief.layout) || (analysis && analysis.layout) || "";
  const truncated = brief && brief.truncated;
  if (!briefText && !analysis) {
    parts.push("Vi3ion analysis failed (is the venv Python path correct?). Do not guess image contents.");
  } else {
    if (briefText) {
      const slim = briefText.replace(/\s+/g, " ").trim();
      const clipped = slim.slice(0, maxChars);
      parts.push(clipped);
      if (clipped.length < slim.length) {
        parts.push(
          "(evidence trimmed to fit the context budget; call query_evidence or " +
            "inspect_region for the rest — do not claim what was cut.)",
        );
      }
    }
    if (layout) {
      if (tier === "compact") {
        parts.push("\nSPATIAL LAYOUT (compact):\n" + compactLayout(layout));
      } else {
        parts.push("\nSPATIAL LAYOUT (relative positions):\n" + layout);
      }
    }
    const ctx = analysis?.data?.analysis?.context;
    if (ctx?.code_matches?.length) {
      parts.push(`Code cross-check matches (${ctx.code_matches.length}):`);
      for (const m of ctx.code_matches.slice(0, 4)) {
        parts.push(`- ${m.file}:${m.line} — ${String(m.snippet).slice(0, 90)}`);
      }
    }
    if (ctx?.terms?.length && ctx.code_matches?.length) {
      parts.push(`Context terms: ${ctx.terms.slice(0, 8).join(", ")}`);
    }
    if (ctx?.path_candidates?.length) {
      parts.push(`File-path candidates in image (${ctx.path_candidates.length}):`);
      for (const c of ctx.path_candidates.slice(0, 5)) {
        parts.push(`- ${c}`);
      }
    }
    if (ctx?.similar_images?.length) {
      parts.push("This looks like a previously seen image (identity is a suggestion, confirm with the user):");
      for (const s of ctx.similar_images.slice(0, 3)) {
        const label = s.label ? ` "${s.label}"` : "";
        parts.push(
          `- ${s.image_id}${label} — similarity ${Math.round((s.similarity || 0) * 100)}%, ` +
            `${s.width || "?"}x${s.height || "?"}`,
        );
      }
      parts.push(
        "If the user confirms it is the same screen, compare versions with " +
          "diff_images(image_id_a=..., image_id_b=...) or ask them for the older image.",
      );
    }
  }
  if (truncated) {
    parts.push(
      "This brief was cut to fit the context budget. Ask for the missing part with " +
        "inspect_region / query_evidence instead of guessing it.",
    );
  }
  parts.push("</context>");
  parts.push("The block above is Vi3ion's measured evidence (OCR + layout + code cross-check). Treat it as observations, not as the final answer; verify uncertainty before claiming.");
  return parts.join("\n");
}

// Find the images of the newest user message in a model request.
//
// V2 hands the plugin the attachment on the *message*, not on the prompt:
//   { data: "<base64>", mime: "image/jpeg", source: { type: "inline" } }
//   { data: "<base64>", mime: "image/jpeg", source: { type: "uri", uri: "file://..." } }
// Older hosts used a `parts` array with { type: "file", mime, url, filename }.
function imagesFromMessages(messages) {
  if (!Array.isArray(messages)) return { images: [], text: "" };
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message) continue;
    const text = typeof message.text === "string" ? message.text : "";
    const files = Array.isArray(message.files) ? message.files : [];
    const parts = Array.isArray(message.parts) ? message.parts : [];
    const candidates = [...files];
    for (const part of parts) {
      if (!part || typeof part !== "object") continue;
      const type = String(part.type || "");
      if (type !== "file" && type !== "image") continue;
      candidates.push({
        mime: part.mime || part.mediaType || "",
        data: part.data,
        name: part.filename || part.name,
        source: part.url
          ? { type: "uri", uri: String(part.url) }
          : { type: "inline" },
      });
    }
    const images = candidates.filter(isImageAttachment);
    if (images.length) {
      return { images, text };
    }
  }
  return { images: [], text: "" };
}

// Record every injected block so the user can read exactly what the model
// received. Best-effort: never throws, never blocks the request.
const TRACE_FILE = path.join(INBOX_DIR, "last-injection.json");

async function recordInjection(payload) {
  try {
    await mkdir(INBOX_DIR, { recursive: true });
    let existing = { history: [] };
    try {
      const raw = await readFile(TRACE_FILE, "utf8");
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") existing = parsed;
    } catch {
      // no previous trace
    }
    const entry = { ...payload, timestamp: new Date().toISOString() };
    const history = Array.isArray(existing.history) ? existing.history : [];
    history.push(entry);
    existing.last = entry;
    existing.history = history.slice(-5);
    await writeFile(TRACE_FILE, JSON.stringify(existing, null, 2), "utf8");
  } catch {
    // tracing must never break the session
  }
}

export { isVisionCapable, confirmInstruction, fileUriToPath, formatDiff };

const ENABLED_KEY = "vi3ion-enabled";
const TIER_KEY = "vi3ion-tier";
const GREETED_KEY = "vi3ion-greeted";
const GREETED_MODEL_KEY = "vi3ion-greeted-model";
const REQUEST_MODEL_KEY = "vi3ion-request-model";
const BUDGET_KEY = "vi3ion-budget";
const EV_STATE_KEY = "vi3ion-ev-state";
const MCP_RELOAD_KEY = "vi3ion-mcp-reload-at";
const SEEN_KEY = "vi3ion-seen-by-session";

// Images already analysed in this session. Scoped per session so a new
// conversation always receives its own evidence.
async function sessionSeen(ctx, sessionID) {
  const map = (await ctx.storage.get(SEEN_KEY)) || {};
  const list = map[sessionID] || [];
  return Array.isArray(list) ? list : [];
}

async function setSessionSeen(ctx, sessionID, seen) {
  const map = (await ctx.storage.get(SEEN_KEY)) || {};
  map[sessionID] = [...seen].slice(-60);
  const keys = Object.keys(map);
  if (keys.length > 50) {
    for (const key of keys.slice(0, keys.length - 50)) delete map[key];
  }
  await ctx.storage.set(SEEN_KEY, map);
}

// Persist greeted session IDs so a plugin reload does not repeat the intro
// inside an existing conversation.
async function wasGreeted(ctx, sessionID) {
  const list = (await ctx.storage.get(GREETED_KEY)) || [];
  return Array.isArray(list) && list.includes(sessionID);
}

async function markGreeted(ctx, sessionID) {
  const list = (await ctx.storage.get(GREETED_KEY)) || [];
  if (!Array.isArray(list) || list.includes(sessionID)) return;
  list.push(sessionID);
  await ctx.storage.set(GREETED_KEY, list.slice(-200));
}

// Which model was introduced in this session? A user can switch models mid
// chat; the new model has never seen Vi3ion and must be told again.
function modelKey(model) {
  if (!model) return "unknown";
  return `${model.providerID || "?"}/${model.id || "?"}`;
}

async function greetedModel(ctx, sessionID) {
  const map = (await ctx.storage.get(GREETED_MODEL_KEY)) || {};
  return map[sessionID] || null;
}

async function setGreetedModel(ctx, sessionID, key) {
  const map = (await ctx.storage.get(GREETED_MODEL_KEY)) || {};
  map[sessionID] = key;
  // Keep the map bounded; drop the oldest entries.
  const keys = Object.keys(map);
  if (keys.length > 200) {
    for (const k of keys.slice(0, keys.length - 200)) delete map[k];
  }
  await ctx.storage.set(GREETED_MODEL_KEY, map);
}

// Model that served the previous model request in this session. Used to
// detect a mid-session model switch independently of the intro bookkeeping.
async function requestModel(ctx, sessionID) {
  const map = (await ctx.storage.get(REQUEST_MODEL_KEY)) || {};
  return map[sessionID] || null;
}

async function setRequestModel(ctx, sessionID, key) {
  const map = (await ctx.storage.get(REQUEST_MODEL_KEY)) || {};
  map[sessionID] = key;
  const keys = Object.keys(map);
  if (keys.length > 200) {
    for (const k of keys.slice(0, keys.length - 200)) delete map[k];
  }
  await ctx.storage.set(REQUEST_MODEL_KEY, map);
}

// Background instructions: session instruction entries render as <context>
// blocks in the model's instructions without appearing in the visible chat.
// If the APIs are unavailable (older host), fall back to appending to the
// prompt text so the model still receives the content.
async function viewInstruction(ctx, sessionID, key, value) {
  const entry = ctx.session && ctx.session.instructions && ctx.session.instructions.entry;
  if (!entry || !entry.put || !entry.remove) return false;
  try {
    if (value) {
      await entry.put({ sessionID, key, value });
    } else {
      await entry.remove({ sessionID, key });
    }
    return true;
  } catch {
    return false;
  }
}

async function isEnabled(ctx) {
  const value = await ctx.storage.get(ENABLED_KEY);
  return value !== false; // default ON
}

// Pick evidence tier: explicit override first, else by model context window
// (<32k -> compact, else full). Local runtimes default to compact because
// they are usually small-context and token-expensive.
async function tierFor(ctx, model) {
  const stored = await ctx.storage.get(TIER_KEY);
  if (stored === "compact" || stored === "full") return stored;
  const ctxSize = model && model.limit && model.limit.context;
  if (typeof ctxSize === "number" && ctxSize > 0 && ctxSize < 32768) return "compact";
  if (isLocalModel(model)) return "compact";
  return "full";
}

// Token budget for the brief. Small-context models get a tight budget so the
// evidence block cannot flood the context window. 0 = unlimited.
async function evidenceBudget(ctx, model, tier) {
  const stored = await ctx.storage.get(BUDGET_KEY);
  if (typeof stored === "number" && stored >= 0) return stored;
  if (tier !== "compact") return 0;
  const limit = model && model.limit && model.limit.context;
  if (typeof limit === "number" && limit > 0) {
    // Spend at most ~8% of the window on the evidence block.
    return Math.max(200, Math.min(900, Math.floor(limit * 0.08)));
  }
  return 700;
}

// Body of the context/compaction hooks. Kept separate so the caller can
// contain every failure: a plugin bug must never break the session.
async function handleRequestHook(ctx, event, hookName, options, mode) {
  if (!(await isEnabled(ctx))) return;
  if (mode === "never") return;
  const model = await resolveModel(ctx, event);
  const vision = options.confirmOnly === true || isVisionCapable(model);
  const local = isLocalModel(model);
  if (!Array.isArray(event.system)) return;

  const presence = presenceInstruction(vision, local);
  event.system.push({ type: "text", text: presence });

  // Are the Vi3ion MCP tools actually usable? The live server status is
  // authoritative: the tool list can still show tools from a server that has
  // since died.
  const tools = event.tools || {};
  const toolNames = Object.keys(tools);
  const toolsListed = toolNames.some((name) => /vi3ion/i.test(name) && /inspect/i.test(name));
  const status = await vi3ionMcpStatus(ctx);
  const mcpBroken =
    (status.found && status.status !== "connected" && status.status !== "pending") ||
    (!status.found && !toolsListed);
  if (mcpBroken) {
    event.system.push({
      type: "text",
      text: missingMcpNotice(status.found ? status.status : "not registered"),
    });
    await reloadMcpIfStale(ctx);
  }

  // A model switch inside the session: tell the new model who Vi3ion is,
  // otherwise it works without knowing the layer exists.
  const key = modelKey(model);
  const previous = await requestModel(ctx, event.sessionID);
  if (previous && previous !== key) {
    const notice = roleChangeNotice(key, previous, vision);
    event.system.push({ type: "text", text: notice });
    await recordInjection({
      session_id: event.sessionID,
      model: key,
      role: vision ? "assistant" : "eyes",
      reason: "model switch",
      blocks: [{ key: "vi3ion-role-change", chars: notice.length, text: notice }],
    });
  }
  await setRequestModel(ctx, event.sessionID, key);

  // Image analysis. The attachment (mime + bytes) only exists on the message,
  // so this is where images are found and measured.
  if (hookName === "context" && (await shouldApply(ctx, mode))) {
    const result = await analyseMessageImages(ctx, event, model, vision, options);
    if (result && result.blocks.length) {
      for (const block of result.blocks) {
        event.system.push({ type: "text", text: block });
      }
      // Keep the evidence in a session instruction too, so it survives
      // follow-up turns and compaction.
      await viewInstruction(ctx, event.sessionID, "vi3ion-evidence", result.blocks.join("\n\n"));
      await recordInjection({
        session_id: event.sessionID,
        model: key,
        role: vision ? "assistant" : "eyes",
        reason: "image analysed",
        blocks: result.blocks.map((block) => ({
          key: "vi3ion-evidence",
          chars: block.length,
          text: block,
        })),
      });
    } else {
      // No new image: re-attach the evidence of the last image so the model
      // can still reason about it.
      const state = (await ctx.storage.get(EV_STATE_KEY)) || {};
      const stored = state[event.sessionID];
      if (stored && Array.isArray(stored.blocks) && stored.blocks.length) {
        for (const block of stored.blocks) {
          event.system.push({ type: "text", text: block });
        }
      }
    }
  }
}

// Register the Vi3ion skill with the editor. The skill ships next to the
// plugin (SKILL.md) and describes when and how to use the MCP tools.
async function registerSkill(ctx) {
  try {
    if (!ctx.skill || !ctx.skill.transform || typeof ctx.skill.transform !== "function") {
      return false;
    }
    const skillPath = path.join(PLUGIN_DIR, "SKILL.md");
    let content = "";
    try {
      content = await readFile(skillPath, "utf8");
    } catch {
      return false;
    }
    if (!content.trim()) return false;
    await ctx.skill.transform((editor) => {
      const existing = editor.get("vi3ion");
      const skill = {
        id: "vi3ion",
        name: "Vi3ion",
        description:
          "Measured visual perception: read screenshots, diagrams and charts with OCR, geometry, per-element colours and version diffs.",
        content,
        path: skillPath,
        autoinvoke: true,
      };
      if (existing) editor.update("vi3ion", () => skill);
      else editor.add(skill);
    });
    return true;
  } catch (error) {
    console.error(`[vi3ion-attach] skill registration skipped: ${error && error.message}`);
    return false;
  }
}

export default Plugin.define({
  id: "vi3ion-attach",
  async setup(ctx) {
    const options = ctx.options || {};
    const mode = options.mode || "auto";

    // A heartbeat in the trace file: proves the plugin is loaded and where it
    // writes. Useful when the session behaves strangely.
    await recordInjection({
      session_id: "plugin",
      reason: "plugin loaded",
      blocks: [
        {
          key: "vi3ion-plugin",
          chars: 0,
          text: `data dir: ${dataDir()} · mode: ${mode} · python: ${pythonPath() || "not found"}`,
        },
      ],
    }).catch(() => {});

    // Self-heal: MCP servers are spawned when the editor starts. If the Vi3ion
    // server died (an upgrade replaced it, it was killed), ask OpenCode to
    // reload the MCP servers so it comes back without an editor restart.
    let heal = "not attempted";
    try {
      const status = await vi3ionMcpStatus(ctx);
      heal = `status=${status.status} found=${status.found}`;
      if (
        status.found &&
        status.status !== "connected" &&
        status.status !== "pending" &&
        ctx.mcp &&
        typeof ctx.mcp.reload === "function"
      ) {
        const last = Number(await ctx.storage.get(MCP_RELOAD_KEY)) || 0;
        if (Date.now() - last > 15000) {
          await ctx.storage.set(MCP_RELOAD_KEY, Date.now());
          await respawnMcpServer(ctx, status.name);
          heal += " -> respawn requested";
        } else {
          heal += " -> respawn skipped (cooldown)";
        }
      }
    } catch (error) {
      heal = `error: ${error && error.message}`;
    }
    await recordInjection({
      session_id: "plugin",
      reason: "mcp self-heal",
      blocks: [{ key: "vi3ion-mcp-heal", chars: 0, text: heal }],
    }).catch(() => {});

    // Register the Vi3ion skill with the editor, so an agent knows the rules
    // (when to call which tool) even without reading the MCP instructions.
    await registerSkill(ctx);

    // Persistent presence: appended to the system instructions of every model
    // request, and to compaction requests, so summarisation cannot silently
    // drop the fact that Vi3ion is the eyes/assistant in this session.
    // The role is recomputed per request: a user may switch models mid-chat,
    // and each request is handled for the model that will answer it.
    for (const hookName of ["context", "compaction"]) {
      await ctx.session.hook(hookName, async (event) => {
        // A plugin bug must never break the user's session: every failure
        // inside a hook is contained here.
        try {
          await handleRequestHook(ctx, event, hookName, options, mode);
        } catch (error) {
          // Record the failure where the user can see it (the trace file),
          // and never let it escape into the session.
          await recordInjection({
            session_id: event.sessionID,
            reason: `${hookName} hook error`,
            blocks: [
              {
                key: "vi3ion-error",
                chars: 0,
                text: `${error && error.stack ? error.stack : String(error)}`,
              },
            ],
          }).catch(() => {});
          console.error(
            `[vi3ion-attach] ${hookName} hook failed (ignored): ${
              error && error.stack ? error.stack : error
            }`,
          );
        }
      });
    }

    // /vi3ionoff and /vi3ionon toggles.
    await ctx.command.transform((editor) => {
      editor.add({
        name: "vi3ionon",
        description: "Enable Vi3ion auto-analysis of attached images",
        execute: async ({ sessionID }) => {
          await ctx.storage.set(ENABLED_KEY, true);
          try {
            await ctx.session.synthetic({
              sessionID,
              text: "Vi3ion is ON: attached images will be analysed for visionless models, and vision models are asked to verify claims against Vi3ion evidence.",
            });
          } catch { /* best-effort ack */ }
        },
      });
      editor.add({
        name: "vi3ionoff",
        description: "Disable Vi3ion auto-analysis of attached images",
        execute: async ({ sessionID }) => {
          await ctx.storage.set(ENABLED_KEY, false);
          try {
            await ctx.session.synthetic({
              sessionID,
              text: "Vi3ion is OFF: images pass through untouched.",
            });
          } catch { /* best-effort ack */ }
        },
      });
      editor.add({
        name: "vi3ioncompact",
        description: "Use compact evidence tier (less tokens, local models)",
        execute: async ({ sessionID }) => {
          await ctx.storage.set(TIER_KEY, "compact");
          try {
            await ctx.session.synthetic({
              sessionID,
              text: "Vi3ion evidence: compact mode (low token count).",
            });
          } catch { /* best-effort ack */ }
        },
      });
      editor.add({
        name: "vi3ionfull",
        description: "Use full evidence tier (more detail, more tokens)",
        execute: async ({ sessionID }) => {
          await ctx.storage.set(TIER_KEY, "full");
          try {
            await ctx.session.synthetic({
              sessionID,
              text: "Vi3ion evidence: full mode.",
            });
          } catch { /* best-effort ack */ }
        },
      });
      editor.add({
        name: "vi3ionstatus",
        description: "Show Vi3ion state: on/off, role (eyes/assistant), evidence tier, local runtime",
        execute: async ({ sessionID }) => {
          const model = await activeModel(ctx);
          const enabled = await isEnabled(ctx);
          const tier = await tierFor(ctx, model);
          const vision = options.confirmOnly === true || isVisionCapable(model);
          const modelName = model ? `${model.providerID || "?"}/${model.id || "?"}` : "unknown";
          const local = isLocalModel(model);
          const lines = [
            `Vi3ion: ${enabled ? "ON" : "OFF"} · ` +
              `role: ${vision ? "assistant (vision detected)" : "eyes (visionless)"} · ` +
              `evidence: ${tier} · model: ${modelName}`,
          ];
          if (local) {
            lines.push("Local runtime detected: compact evidence is used by default.");
          }
          // Report reachable local runtimes so the user can pair Vi3ion with
          // the right local model.
          const report = await runLocalStack();
          if (report) {
            const running = (report.runtimes || []).map((r) => r.name).join(", ");
            lines.push(
              running
                ? `Local runtimes serving: ${running}`
                : "No local LLM runtime is serving right now.",
            );
            if ((report.vision_models || []).length) {
              lines.push(`Local vision models: ${report.vision_models.join(", ")}`);
            }
          }
          try {
            await ctx.session.synthetic({ sessionID, text: lines.join("\n") });
          } catch { /* best-effort ack */ }
        },
      });
      editor.add({
        name: "vi3ionbudget",
        description: "Set the token budget for injected evidence (0 = auto/unlimited)",
        execute: async ({ sessionID, args }) => {
          const raw = String((args && args.trim()) || "").split(/\s+/)[0];
          const value = Number.parseInt(raw, 10);
          if (!Number.isFinite(value) || value < 0) {
            try {
              await ctx.session.synthetic({
                sessionID,
                text: "Usage: /vi3ionbudget <tokens> (0 = auto by model context window)",
              });
            } catch { /* best-effort ack */ }
            return;
          }
          await ctx.storage.set(BUDGET_KEY, value);
          try {
            await ctx.session.synthetic({
              sessionID,
              text: value === 0
                ? "Vi3ion evidence budget: auto (based on the model context window)."
                : `Vi3ion evidence budget: ${value} tokens per image.`,
            });
          } catch { /* best-effort ack */ }
        },
      });
      editor.add({
        name: "vi3iondiff",
        description: "Compare two images (paths or ids): /vi3iondiff old.png new.png",
        execute: async ({ sessionID, args }) => {
          const parts = String((args && args.trim()) || "").split(/\s+/).filter(Boolean);
          if (parts.length < 2) {
            try {
              await ctx.session.synthetic({
                sessionID,
                text: "Usage: /vi3iondiff <older image> <newer image> (paths or vi3ion ids)",
              });
            } catch { /* best-effort ack */ }
            return;
          }
          const diff = await withTimeout(
            runDiff(parts[0], parts[1]),
            options.analyzeTimeoutMs || 240000,
            "diff",
          );
          const block = diff
            ? formatDiff(diff, path.basename(parts[0]), path.basename(parts[1]))
            : "<context key=\"vi3ion-diff\">Vi3ion could not compare these images.</context>";
          try {
            await ctx.session.synthetic({ sessionID, text: block });
          } catch { /* best-effort ack */ }
        },
      });
      editor.add({
        name: "vi3iondoctor",
        description: "Run a Vi3ion self-check (OCR, RAM, registry, local runtimes, editor wiring)",
        execute: async ({ sessionID }) => {
          const stdout = await runPython(["-m", "vi3ion.cli", "doctor", "--json"], 60000);
          let lines = [];
          if (!stdout) {
            lines = ["Vi3ion doctor could not run (python unavailable)."];
          } else {
            try {
              const report = JSON.parse(stdout);
              for (const check of report.checks || []) {
                lines.push(`${check.ok ? "OK  " : "WARN"} ${check.check}: ${check.detail}`);
              }
              for (const action of report.next_actions || []) {
                lines.push(`-> ${action}`);
              }
            } catch {
              lines = ["Vi3ion doctor returned unreadable output."];
            }
          }
          try {
            await ctx.session.synthetic({ sessionID, text: lines.join("\n") });
          } catch { /* best-effort ack */ }
        },
      });
      editor.add({
        name: "vi3ionlocal",
        description: "List local LLM runtimes (Ollama, llama.cpp, LM Studio, vLLM, ...) and which models they serve",
        execute: async ({ sessionID }) => {
          const report = await runLocalStack();
          const lines = [];
          if (!report) {
            lines.push("Vi3ion could not query local runtimes (python unavailable).");
          } else if (!(report.runtimes || []).length) {
            lines.push("No local LLM runtime is serving right now.");
            const stopped = report.stopped_runtimes || [];
            if (stopped.length) {
              lines.push(
                `Installed but not running: ${stopped.map((r) => r.name).join(", ")}`,
              );
            }
          } else {
            for (const runtime of report.runtimes) {
              lines.push(`${runtime.name} (${runtime.host}:${runtime.port})`);
              for (const model of runtime.models) {
                const marker = runtime.vision_models.includes(model) ? "vision" : "text";
                lines.push(`  - ${model} [${marker}]`);
              }
            }
          }
          if (report) lines.push(report.recommendation);
          try {
            await ctx.session.synthetic({ sessionID, text: lines.join("\n") });
          } catch { /* best-effort ack */ }
        },
      });
    });

    await ctx.session.hook("prompt", async (event) => {
      // A plugin bug must never break the user's session.
      try {
        await handlePromptHook(ctx, event, options, mode);
      } catch (error) {
        await recordInjection({
          session_id: event.sessionID,
          reason: "prompt hook error",
          blocks: [
            {
              key: "vi3ion-error",
              chars: 0,
              text: `${error && error.stack ? error.stack : String(error)}`,
            },
          ],
        }).catch(() => {});
        console.error(
          `[vi3ion-attach] prompt hook failed (ignored): ${
            error && error.stack ? error.stack : error
          }`,
        );
      }
    });

    async function handlePromptHook(ctx, event, options, mode) {
      if (!(await isEnabled(ctx))) return;
      if (mode === "never") return;

      const model = await activeModel(ctx, event);
      const vision = options.confirmOnly === true || isVisionCapable(model);
      const compactTier = (await tierFor(ctx, model)) === "compact";

      // Role bookkeeping only. Image analysis happens in the context hook,
      // where the attachment (mime + bytes) is actually available.
      const greeted = await wasGreeted(ctx, event.sessionID);
      const currentKey = modelKey(model);
      const previousKey = await greetedModel(ctx, event.sessionID);

      if (!greeted) {
        await markGreeted(ctx, event.sessionID);
        await setGreetedModel(ctx, event.sessionID, currentKey);
        const intro = introInstruction(model, vision, compactTier);
        await viewInstruction(ctx, event.sessionID, "vi3ion-intro", intro);
        await recordInjection({
          session_id: event.sessionID,
          model: currentKey,
          role: vision ? "assistant" : "eyes",
          blocks: [{ key: "vi3ion-intro", chars: intro.length, text: intro }],
        });
      } else if (previousKey && previousKey !== currentKey) {
        // The user switched models mid-conversation. The new model has never
        // seen Vi3ion, so introduce it again and state the new role.
        await setGreetedModel(ctx, event.sessionID, currentKey);
        const intro = introInstruction(
          model,
          vision,
          compactTier,
          `Model changed in this conversation (was ${previousKey}). Re-read the Vi3ion role now.`,
        );
        await viewInstruction(ctx, event.sessionID, "vi3ion-intro", intro);
        await recordInjection({
          session_id: event.sessionID,
          model: currentKey,
          role: vision ? "assistant" : "eyes",
          reason: "model switch",
          blocks: [{ key: "vi3ion-intro", chars: intro.length, text: intro }],
        });
      }
    }
  },
});

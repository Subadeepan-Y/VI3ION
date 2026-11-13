// Smoke test for the vi3ion-attach plugin.
//
// Covers:
//   - role/intro injection (prompt hook)
//   - persistent presence (context + compaction hooks)
//   - message-level image analysis (context hook): file attachment, clipboard
//     (inline base64), retention, per-session cache
//   - vision vs visionless role
//   - on/off toggles, diff formatting, local runtime behaviour
//   - the injection trace file
import fs from "node:fs";
import assert from "node:assert";
import os from "node:os";
import path from "node:path";

// The smoke test must not touch the user's real data dir (it writes the
// injection trace). Use a throwaway directory. ESM hoists imports, so the
// plugin is loaded dynamically after the variable is set.
const SMOKE_DATA = fs.mkdtempSync(path.join(os.tmpdir(), "vi3ion-smoke-"));
process.env.VI3ION_DATA_DIR = SMOKE_DATA;

const { default: plugin } = await import("./index.js");

// Locate the repository root (the package lives in plugins/opencode/) and the
// sample image inside it. No absolute paths: the suite runs on any machine.
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

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\//, ""));
const REPO_DIR = findRepoRoot(HERE);
const SAMPLE = REPO_DIR ? path.join(REPO_DIR, "tests", "fixtures", "sample_ui.png") : "";
const IMG = SAMPLE;
const IMG_URI = SAMPLE ? `file:///${SAMPLE.replace(/\\/g, "/")}` : "";
const TRACE = path.join(SMOKE_DATA, "inbox", "last-injection.json");
if (!SAMPLE || !fs.existsSync(SAMPLE)) {
  console.log("SMOKE skipped (sample_ui.png not found - run from the repository)");
  process.exit(0);
}

let hooks = {};
let commands = [];

function makeCtx(model, initialEnabled = undefined, opts = {}) {
  const store = new Map();
  if (initialEnabled !== undefined) store.set("vi3ion-enabled", initialEnabled);
  const instructionsStore = new Map();
  const session = {
    async hook(name, fn) {
      assert.ok(["prompt", "context", "compaction"].includes(name), `unexpected hook ${name}`);
      hooks[name] = fn;
    },
    async synthetic() {},
  };
  if (!opts.noInstructions) {
    session.instructions = {
      entry: {
        async put({ sessionID, key, value }) {
          instructionsStore.set(`${sessionID}::${key}`, value);
        },
        async remove({ sessionID, key }) {
          instructionsStore.delete(`${sessionID}::${key}`);
        },
      },
    };
  }
  const modelInfo = (m) =>
    m
      ? {
          id: m.id,
          modelID: m.id,
          providerID: m.providerID,
          name: m.name || m.id,
          capabilities: m.capabilities || { input: ["text"], output: ["text"] },
          limit: m.limit || { context: 32768, output: 4096 },
          baseURL: m.baseURL || "",
        }
      : null;
  return {
    options: { mode: "always", codeCheck: false, updatesCheck: false },
    _store: store,
    _instructions: instructionsStore,
    storage: {
      async get(k) { return store.get(k); },
      async set(k, v) { store.set(k, v); },
    },
    model: {
      async default() { return { location: {}, data: modelInfo(model) }; },
      async list() { return { location: {}, data: modelInfo(model) ? [modelInfo(model)] : [] }; },
    },
    provider: {
      async get() { return null; },
    },
    session,
    command: {
      async transform(fn) {
        const editor = {
          add(def) { commands.push(def); },
        };
        fn(editor);
      },
    },
  };
}

// Prompt hook: role bookkeeping only. The user's text must never change.
const runHook = (ctx, text = "look at this") => {
  const ev = { sessionID: "ses_test", prompt: { text, files: [] } };
  return hooks.prompt(ev).then(() => ev.prompt.text);
};

// Context hook: a model request. `messages` carry the attachments.
const runContext = async (ctx, { messages = [], sessionID = "ses_test", model } = {}) => {
  const event = { sessionID, model, system: [], messages };
  await hooks.context(event);
  return event.system.map((part) => part.text).join("\n");
};

const runSystemHook = async (name, model, sessionID = "ses_test") => {
  const event = { sessionID, model, system: [] };
  await hooks[name](event);
  return event.system.map((part) => part.text).join("\n");
};

const instr = (ctx, key) => ctx._instructions.get(`ses_test::${key}`);

const fileMessage = () => ({
  role: "user",
  text: "what does this show?",
  files: [
    {
      mime: "image/png",
      name: "sample_ui.png",
      data: fs.readFileSync(IMG).toString("base64"),
      source: { type: "uri", uri: IMG_URI },
    },
  ],
});

const clipboardMessage = () => ({
  role: "user",
  text: "and this one?",
  files: [
    {
      mime: "image/png",
      name: "clipboard",
      data: fs.readFileSync(IMG).toString("base64"),
      source: { type: "inline" },
    },
  ],
});

// --- 1. visionless: role + intro, then image evidence from the message ---
commands = [];
const visionlessCtx = makeCtx({ providerID: "inception", id: "mercury-3" });
await plugin.setup(visionlessCtx);
assert.strictEqual(commands.length, 11, "expected on/off/compact/full/status/budget/local/diff/doctor/version/auto commands");
for (const name of [
  "vi3ionon", "vi3ionoff", "vi3ioncompact", "vi3ionfull",
  "vi3ionstatus", "vi3ionbudget", "vi3ionlocal", "vi3iondiff", "vi3iondoctor",
  "vi3ionversion", "vi3ionauto",
]) {
  assert.ok(commands.some((c) => c.name === name), `missing command ${name}`);
}

const ev1 = await runHook(visionlessCtx);
assert.strictEqual(ev1, "look at this", "visionless: prompt text must stay untouched");
assert.ok(instr(visionlessCtx, "vi3ion-intro").includes("vi3ion-intro"), "visionless: intro block missing");
assert.ok(instr(visionlessCtx, "vi3ion-intro").includes("VISIONLESS"), "visionless: role hint missing");
assert.ok(instr(visionlessCtx, "vi3ion-intro").includes("Do I have native vision"), "visionless: self-check question missing");

// The image arrives on the message: the context hook must analyse it.
const withImage = await runContext(visionlessCtx, { messages: [fileMessage()] });
assert.ok(withImage.includes("vi3ion-auto"), "visionless: evidence block missing from the request");
assert.ok(withImage.includes("Save"), "visionless: OCR text missing");
assert.ok(withImage.includes("SPATIAL LAYOUT"), "visionless: spatial layout missing");
assert.ok(
  visionlessCtx._instructions.has("ses_test::vi3ion-evidence"),
  "visionless: evidence not stored as a session instruction",
);

// Intro must not repeat on a later prompt or after a plugin reload.
const ev1b = await runHook(visionlessCtx);
assert.strictEqual(ev1b, "look at this", "visionless: prompt text changed on later prompt");
await plugin.setup(visionlessCtx); // simulate plugin reload, same storage
const ev1c = await runHook(visionlessCtx);
assert.strictEqual(ev1c, "look at this", "visionless: prompt text changed after reload");

// --- 1b. persistent presence in every request and in compaction ---
const presenceEyes = await runSystemHook("context", { providerID: "inception", id: "mercury-3" });
assert.ok(presenceEyes.includes("Vi3ion presence"), "context: presence missing");
assert.ok(presenceEyes.includes("eyes"), "context: visionless role missing");
const compactionEyes = await runSystemHook("compaction", { providerID: "inception", id: "mercury-3" });
assert.ok(compactionEyes.includes("Keep this role in mind in summaries"), "compaction: presence missing");

// --- 1c. intro appears even when no image is attached ---
{
  const noImageCtx = makeCtx({ providerID: "inception", id: "mercury-3" });
  await plugin.setup(noImageCtx);
  const evNoImage = { sessionID: "ses_no_image", prompt: { text: "hello", files: [] } };
  await hooks.prompt(evNoImage);
  assert.strictEqual(evNoImage.prompt.text, "hello", "no-image: prompt must stay untouched");
  assert.ok(noImageCtx._instructions.has("ses_no_image::vi3ion-intro"), "no-image: intro missing");
}

// --- 2. vision model: assistant note (default ON) ---
const visionCtx = makeCtx({ providerID: "deepseek", id: "deepseek-v4.1-flash" });
await plugin.setup(visionCtx);
const ev2 = await runHook(visionCtx);
assert.strictEqual(ev2, "look at this", "vision: prompt text must stay untouched");
assert.ok(instr(visionCtx, "vi3ion-intro").includes("VISION-CAPABLE"), "vision: intro role hint missing");
assert.ok(instr(visionCtx, "vi3ion-intro").includes("primary"), "vision: lead role not stated");
const presenceConfirmer = await runSystemHook("compaction", {
  providerID: "deepseek",
  id: "deepseek-v4.1-flash",
});
assert.ok(presenceConfirmer.includes("assistant"), "compaction: assistant role missing");

// A vision model gets no heavy OCR: only the assistant note.
const visionRequest = await runContext(visionCtx, { messages: [fileMessage()] });
assert.ok(visionRequest.includes("vi3ion-confirm"), "vision: assistant note missing");
assert.ok(!visionRequest.includes("Dominant colour"), "vision: heavy brief must not be injected");
assert.ok(!visionRequest.includes("authoritative"), "vision: must not claim authority over the model");

// --- 3. disabled: nothing injected ---
const offCtx = makeCtx({ providerID: "inception", id: "mercury-3" }, false);
await plugin.setup(offCtx);
const ev3 = await runHook(offCtx);
assert.strictEqual(ev3, "look at this", "disabled: prompt should be untouched");
const offRequest = await runContext(offCtx, { messages: [fileMessage()] });
assert.ok(!offRequest.includes("vi3ion-auto"), "disabled: evidence must not be injected");

// --- 4. low-context visionless model -> compact tier ---
const smallCtx = makeCtx({ providerID: "inception", id: "mercury-3", limit: { context: 8192 } });
await plugin.setup(smallCtx);
await hooks.prompt({ sessionID: "ses_small", prompt: { text: "hi", files: [] } });
const smallIntro = smallCtx._instructions.get("ses_small::vi3ion-intro");
assert.ok(smallIntro.includes("this session: compact"), "small-context: intro tier hint missing");
const smallRequest = await runContext(smallCtx, { messages: [fileMessage()], sessionID: "ses_small" });
assert.ok(smallRequest.includes("SPATIAL LAYOUT (compact)"), "small-context: compact layout expected");
assert.ok(!smallRequest.includes("| Region |"), "small-context: full table should not appear");

// --- 5. re-enabled: injection resumes ---
const offCtx2 = makeCtx({ providerID: "inception", id: "mercury-3" }, false);
await plugin.setup(offCtx2);
await offCtx2.storage.set("vi3ion-enabled", true);
const ev4 = await runHook(offCtx2);
assert.strictEqual(ev4, "look at this", "re-enabled: prompt must stay untouched");
const onRequest = await runContext(offCtx2, { messages: [fileMessage()] });
assert.ok(onRequest.includes("vi3ion-auto"), "re-enabled: evidence block missing");

// --- 6. clipboard (inline base64) image ---
{
  const clipCtx = makeCtx({ providerID: "inception", id: "mercury-3" });
  await plugin.setup(clipCtx);
  const request = await runContext(clipCtx, { messages: [clipboardMessage()], sessionID: "ses_clip" });
  assert.ok(request.includes("vi3ion-auto"), "clipboard: inline image not analysed");
  assert.ok(request.includes("Save"), "clipboard: OCR text missing");
}

// --- 6b. raw clipboard (base64 data only, no mime/name/source, as sent by OpenCode) ---
{
  const rawClipCtx = makeCtx({ providerID: "inception", id: "mercury-3" });
  await plugin.setup(rawClipCtx);
  const rawClipMsg = {
    role: "user",
    text: "look at this clipboard image",
    files: [{ data: fs.readFileSync(IMG).toString("base64") }],
  };
  const request = await runContext(rawClipCtx, { messages: [rawClipMsg], sessionID: "ses_raw_clip" });
  assert.ok(request.includes("vi3ion-auto"), "raw clipboard: inline base64 image without mime not analysed");
  assert.ok(request.includes("Save"), "raw clipboard: OCR text missing");
  const { createHash } = await import("node:crypto");
  const expectedHash = createHash("sha256").update(fs.readFileSync(IMG)).digest("hex").slice(0, 16);
  const expectedClipPath = path.join(SMOKE_DATA, "inbox", `clipboard-${expectedHash}.png`);
  assert.ok(fs.existsSync(expectedClipPath), `raw clipboard: expected file ${expectedClipPath} not found`);
}

// --- 7. version diff formatting (no subprocess needed) ---
{
  const sampleDiff = {
    summary: "1 change(s) between versions; overall similarity 92.9%",
    data: {
      diff: {
        change_count: 1,
        layout_similarity: 1.0,
        text_similarity: 0.86,
        changes: [
          { kind: "changed", region: "centre", old: "system", new: "custom" },
        ],
      },
    },
  };
  const { formatDiff } = await import("./index.js");
  const block = formatDiff(sampleDiff, "old.png", "new.png");
  assert.ok(block.includes("vi3ion-diff"), "diff: context block missing");
  assert.ok(block.includes('"system" -> "custom"'), "diff: change line missing");
  assert.ok(block.includes("Confirm identity"), "diff: confirmation hint missing");
}

// --- 8. pixel comparison is reported in the diff block ---
{
  const { formatDiff } = await import("./index.js");
  const visualDiff = {
    summary: "0 text change(s)",
    data: {
      diff: { change_count: 0, layout_similarity: 1, text_similarity: 1, changes: [] },
      visual: {
        available: true,
        changed_percent: 1.42,
        changed_region_count: 2,
        changed_regions: [
          { bbox: [10, 20, 60, 40], pixels: 500, position: "top-left" },
        ],
      },
    },
  };
  const block = formatDiff(visualDiff, "a.png", "b.png");
  assert.ok(block.includes("Pixel comparison"), "visual: pixel comparison line missing");
  assert.ok(block.includes("1.42%"), "visual: percentage missing");
  assert.ok(block.includes("no text changed"), "visual: must flag textless changes");
}

// --- 9. legacy host without session-instruction API ---
{
  const legacyCtx = makeCtx({ providerID: "inception", id: "mercury-3" }, undefined, { noInstructions: true });
  await plugin.setup(legacyCtx);
  const request = await runContext(legacyCtx, { messages: [fileMessage()], sessionID: "ses_legacy" });
  assert.ok(request.includes("vi3ion-auto"), "legacy: evidence must still reach the request");
}

// --- 10. model switch mid-session: new model is re-introduced ---
{
  const switchCtx = makeCtx({ providerID: "inception", id: "mercury-3" });
  await plugin.setup(switchCtx);
  await hooks.prompt({ sessionID: "ses_switch", prompt: { text: "hi", files: [] } });
  const first = switchCtx._instructions.get("ses_switch::vi3ion-intro");
  assert.ok(first && first.includes("VISIONLESS"), "switch: first intro missing");

  switchCtx.model.default = async () => ({
    location: {},
    data: {
      id: "qwen3-8b",
      modelID: "qwen3-8b",
      providerID: "ollama",
      name: "qwen3-8b",
      capabilities: { input: ["text"], output: ["text"] },
      limit: { context: 8192, output: 2048 },
    },
  });
  await hooks.prompt({ sessionID: "ses_switch", prompt: { text: "and now?", files: [] } });
  const second = switchCtx._instructions.get("ses_switch::vi3ion-intro");
  assert.ok(second && second.includes("Model changed"), "switch: intro not refreshed after model change");
  assert.ok(second.includes("ollama/qwen3-8b"), "switch: new model not named");

  await runSystemHook("context", { providerID: "inception", id: "mercury-3" }, "ses_switch");
  const notice = await runSystemHook(
    "context",
    { providerID: "ollama", id: "qwen3-8b" },
    "ses_switch",
  );
  assert.ok(notice.includes("Vi3ion presence"), "switch: presence missing");
  assert.ok(notice.includes("active model changed"), "switch: role change notice missing");
  assert.ok(notice.includes("Vi3ion is your eyes"), "switch: role not restated");
}

// --- 11. local runtime: compact tier + name-based vision detection ---
{
  const { isVisionCapable } = await import("./index.js");
  assert.ok(isVisionCapable({ providerID: "ollama", id: "llava:7b" }), "local: llava should be vision capable");
  assert.ok(!isVisionCapable({ providerID: "ollama", id: "qwen3-8b" }), "local: text-only ollama model must not be vision capable");
  assert.ok(isVisionCapable({ providerID: "llamacpp", id: "qwen2.5vl-7b" }), "local: qwen2.5vl should be vision capable");
  assert.ok(
    isVisionCapable({ providerID: "x", id: "y", capabilities: { input: ["text", "image"], output: ["text"] } }),
    "capabilities: image input must be authoritative",
  );
  assert.ok(
    !isVisionCapable({ providerID: "openai", id: "qwen3-8b", baseURL: "http://127.0.0.1:8080/v1" }),
    "local: generic provider id must not be treated as vision capable",
  );
  assert.ok(
    isVisionCapable({ providerID: "openai", id: "llava:7b", baseURL: "http://127.0.0.1:8080/v1" }),
    "local: llava behind a generic provider id must still be vision capable",
  );

  const localCtx = makeCtx({ providerID: "ollama", id: "qwen3-8b", limit: { context: 32768, output: 4096 } });
  await plugin.setup(localCtx);
  await hooks.prompt({ sessionID: "ses_local", prompt: { text: "hi", files: [] } });
  const intro = localCtx._instructions.get("ses_local::vi3ion-intro");
  assert.ok(intro.includes("this session: compact"), "local: compact tier not selected for local runtime");
  assert.ok(intro.includes("LOCAL runtime"), "local: runtime not announced in intro");
  const localPresence = await runSystemHook("context", { providerID: "ollama", id: "qwen3-8b" }, "ses_local");
  assert.ok(localPresence.includes("local runtime"), "local: presence does not mention the local runtime");
  assert.ok(localPresence.includes("only source of image facts"), "local: presence must state the evidence source");

  const tunnelCtx = makeCtx({
    providerID: "kaggle-qwen",
    id: "qwen3.8-27b",
    baseURL: "https://jeff-sail-aquatic-fabrics.trycloudflare.com/v1",
    limit: { context: 65536, output: 8192 },
  });
  await plugin.setup(tunnelCtx);
  await hooks.prompt({ sessionID: "ses_tunnel", prompt: { text: "hi", files: [] } });
  const tunnelIntro = tunnelCtx._instructions.get("ses_tunnel::vi3ion-intro");
  assert.ok(tunnelIntro.includes("this session: compact"), "tunnel: compact tier not selected");
}

// --- 12. the same image is not analysed twice, and the evidence is retained ---
{
  const cacheCtx = makeCtx({ providerID: "inception", id: "mercury-3" });
  await plugin.setup(cacheCtx);
  const first = await runContext(cacheCtx, { messages: [fileMessage()], sessionID: "ses_cache" });
  assert.ok(first.includes("vi3ion-auto"), "cache: first request has no evidence");
  const second = await runContext(cacheCtx, { messages: [fileMessage()], sessionID: "ses_cache" });
  assert.ok(second.includes("vi3ion-auto"), "cache: evidence must stay available on later requests");
}

// --- 13. the injection trace file records what the model received ---
{
  assert.ok(fs.existsSync(TRACE), "trace: last-injection.json was not written");
  const trace = JSON.parse(fs.readFileSync(TRACE, "utf8"));
  assert.ok(Array.isArray(trace.history), "trace: history missing");
  const withEvidence = trace.history.find((entry) => entry.reason === "image analysed");
  assert.ok(withEvidence, "trace: no image analysis recorded");
  assert.ok(withEvidence.blocks.length > 0, "trace: no blocks recorded");
  assert.ok(
    withEvidence.blocks.some((block) => block.text.includes("vi3ion-auto")),
    "trace: evidence text not recorded",
  );
}

// --- 15. a dead MCP server is detected and reloaded ---
{
  let reloaded = 0;
  const reloadCtx = makeCtx({ providerID: "inception", id: "mercury-3" });
  reloadCtx.mcp = {
    async reload() { reloaded += 1; },
    async list() { return { data: [{ name: "vi3ion", status: "failed" }] }; },
  };
  await plugin.setup(reloadCtx);
  // The server is failed -> the plugin notices and asks OpenCode to reload
  // the MCP servers (at most once a minute).
  const request = await runContext(reloadCtx, { messages: [], sessionID: "ses_reload" });
  assert.ok(request.includes("failed"), "reload: status not reported");
  assert.ok(request.includes("not registered or reachable") === false, "reload: wrong notice text");
  assert.strictEqual(reloaded, 1, "reload: MCP reload was not requested");
  // A second request inside the cooldown must not reload again.
  await runContext(reloadCtx, { messages: [], sessionID: "ses_reload" });
  assert.strictEqual(reloaded, 1, "reload: MCP reload repeated inside the cooldown");
}

// --- 16. a connected MCP server triggers no reload ---
{
  let reloaded = 0;
  const okCtx = makeCtx({ providerID: "inception", id: "mercury-3" });
  okCtx.mcp = {
    async reload() { reloaded += 1; },
    async list() { return { data: [{ name: "vi3ion", status: "connected" }] }; },
  };
  await plugin.setup(okCtx);
  const request = await runContext(okCtx, { messages: [], sessionID: "ses_ok" });
  assert.ok(!request.includes("Vi3ion notice"), "connected: spurious notice");
  assert.strictEqual(reloaded, 0, "connected: unexpected MCP reload");
}

// --- 17. a failed MCP server is re-registered (what actually restarts it) ---
{
  let reloaded = 0;
  let updated = null;
  let seenConfig = null;
  const healCtx = makeCtx({ providerID: "inception", id: "mercury-3" });
  healCtx.mcp = {
    async reload() { reloaded += 1; },
    async list() { return { data: [{ name: "vi3ion", status: "failed" }] }; },
    async transform(fn) {
      const config = { type: "local", command: ["python.exe", "-m", "vi3ion.mcp_server"] };
      const editor = {
        get: () => config,
        update: (name, updater) => { updated = name; updater(config); },
        set: () => {},
        remove: () => {},
      };
      fn(editor);
      seenConfig = config;
    },
  };
  await plugin.setup(healCtx);
  assert.strictEqual(reloaded, 1, "heal: the MCP config was not reloaded");
  assert.strictEqual(updated, "vi3ion", "heal: the vi3ion server entry was not re-registered");
  assert.ok(seenConfig && seenConfig.disabled === false, "heal: the server was not re-enabled");
}

// --- 17. a plugin bug inside a hook must never break the session ---
{
  const brokenCtx = makeCtx({ providerID: "inception", id: "mercury-3" });
  await plugin.setup(brokenCtx);
  // Make the model resolution explode: the hook must swallow it.
  brokenCtx.model.default = async () => {
    throw new Error("boom");
  };
  const request = await runContext(brokenCtx, { messages: [], sessionID: "ses_broken" });
  assert.ok(typeof request === "string", "broken: hook did not return");
  // The prompt hook must survive the same failure.
  const prompt = await runHook(brokenCtx);
  assert.strictEqual(prompt, "look at this", "broken: prompt hook changed the user text");
}

console.log("SMOKE OK (intro / presence / compaction / message-images / clipboard / retention / cache / trace / visionless / vision / off / on / diff / model-switch / local / mcp-reload / fault-isolation)");

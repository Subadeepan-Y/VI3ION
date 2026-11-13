// End-to-end, LOCAL model path: real screenshot, compact tier, one Python pass.
//
// A local runtime (Ollama, llama.cpp, LM Studio, vLLM, ...) is usually
// RAM-bound and has a small context window. This script checks that the
// plugin still produces usable evidence for such a model.
import fs from "node:fs";
import assert from "node:assert";
import path from "node:path";

import plugin from "./index.js";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\//, ""));
const REPO_DIR = path.resolve(HERE, "..", "..");
const IMG = path.join(REPO_DIR, "data", "debug", "sample_ui_v2.png");
const IMG_URI = "file:///" + IMG.replace(/\\/g, "/");
assert.ok(fs.existsSync(IMG), "screenshot missing");

let hooks = {};
const store = new Map();
const instructionsStore = new Map();

const ctx = {
  // A local runtime: 8K context, no image input.
  options: { mode: "auto", codeCheck: undefined, maxEvidenceChars: 1400 },
  storage: {
    async get(k) { return store.get(k); },
    async set(k, v) { store.set(k, v); },
  },
  model: {
    async default() {
      return {
        location: {},
        data: {
          id: "qwen3-8b",
          modelID: "qwen3-8b",
          providerID: "ollama",
          name: "qwen3-8b",
          capabilities: { input: ["text"], output: ["text"] },
          limit: { context: 8192, output: 2048 },
          baseURL: "http://127.0.0.1:11434/v1",
        },
      };
    },
    async list() { return { location: {}, data: [] }; },
  },
  provider: { async get() { return null; } },
  session: {
    async hook(name, fn) { hooks[name] = fn; },
    instructions: {
      entry: {
        async put({ sessionID, key, value }) {
          instructionsStore.set(`${sessionID}::${key}`, value);
        },
        async remove({ sessionID, key }) {
          instructionsStore.delete(`${sessionID}::${key}`);
        },
      },
    },
    async synthetic() {},
  },
  command: { async transform() {} },
};

await plugin.setup(ctx);
assert.ok(hooks.context, "context hook not registered");
assert.ok(hooks.prompt, "prompt hook not registered");

// First prompt: the role is introduced.
await hooks.prompt({
  sessionID: "ses_e2e_local",
  prompt: { text: "what does this screen show?", files: [] },
});

const event = {
  sessionID: "ses_e2e_local",
  model: { providerID: "ollama", id: "qwen3-8b" },
  system: [],
  messages: [
    {
      role: "user",
      text: "what does this screen show?",
      files: [
        {
          mime: "image/png",
          name: "sample_ui_v2.png",
          data: fs.readFileSync(IMG).toString("base64"),
          source: { type: "uri", uri: IMG_URI },
        },
      ],
    },
  ],
};

const started = Date.now();
await hooks.context(event);
const elapsed = Date.now() - started;

const text = event.system.map((part) => part.text).join("\n");
const instr = (key) => instructionsStore.get(`ses_e2e_local::${key}`) || "";

// The role is announced and the local runtime is named.
assert.ok(text.includes("Vi3ion presence"), "presence missing");
assert.ok(text.includes("local runtime"), "local runtime not announced");

const intro = instr("vi3ion-intro");
assert.ok(intro.includes("LOCAL runtime"), "local runtime not announced in intro");
assert.ok(intro.includes("VISIONLESS"), "local text model must be treated as visionless");
assert.ok(intro.includes("this session: compact"), "compact tier not selected");

const evidence = instr("vi3ion-evidence");
assert.ok(evidence, "no evidence stored");
assert.ok(evidence.includes("vi3ion-auto"), "evidence block missing");
assert.ok(evidence.includes("SPATIAL LAYOUT (compact)"), "compact layout missing");
assert.ok(evidence.includes("Save"), "OCR text missing");
assert.ok(!evidence.includes("| Region |"), "full table must not appear for a local model");

// Local models skip the duplicate analysis pass (code cross-check).
assert.ok(!evidence.includes("Code cross-check"), "local path must skip the code cross-check pass");

console.log(`E2E LOCAL OK (${elapsed} ms)`);
console.log("--- evidence (first 700 chars) ---");
console.log(evidence.slice(0, 700));

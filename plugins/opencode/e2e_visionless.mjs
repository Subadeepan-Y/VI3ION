// End-to-end, visionless model: real screenshot, real plugin hook.
//
// Stubs only the OpenCode context (storage/model/session), exactly like the
// plugin sees it inside OpenCode with a visionless active model.
import fs from "node:fs";
import assert from "node:assert";
import path from "node:path";

import plugin from "./index.js";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\//, ""));
const REPO_DIR = path.resolve(HERE, "..", "..");

// Code cross-check roots for the child Python process (inherited env).
// Defaults to this repository; override with VI3ION_CODE_ROOTS.
process.env.VI3ION_CODE_ROOTS =
  process.env.VI3ION_CODE_ROOTS || REPO_DIR;

const IMG = path.join(REPO_DIR, "data", "debug", "sample_ui_v2.png");
const IMG_URI = "file:///" + IMG.replace(/\\/g, "/");
assert.ok(fs.existsSync(IMG), "screenshot missing");

let hooks = {};
const store = new Map();
const instructionsStore = new Map();

const ctx = {
  options: { mode: "always", codeCheck: true, maxEvidenceChars: 1600 },
  storage: {
    async get(k) { return store.get(k); },
    async set(k, v) { store.set(k, v); },
  },
  model: {
    async default() {
      return {
        location: {},
        data: {
          id: "mercury-3",
          modelID: "mercury-3",
          providerID: "inception",
          name: "mercury-3",
          capabilities: { input: ["text"], output: ["text"] },
          limit: { context: 32768, output: 4096 },
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
assert.ok(hooks.prompt && hooks.context, "hooks not registered");

// First prompt: the role is introduced.
await hooks.prompt({
  sessionID: "ses_e2e",
  prompt: { text: "there is a bug in the portfolio landing page; the footer map looks wrong", files: [] },
});
assert.ok(instructionsStore.has("ses_e2e::vi3ion-intro"), "intro missing");

// The image arrives on the message.
const event = {
  sessionID: "ses_e2e",
  model: { providerID: "inception", id: "mercury-3" },
  system: [],
  messages: [
    {
      role: "user",
      text: "there is a bug in the portfolio landing page; the footer map looks wrong",
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

await hooks.context(event);

const text = event.system.map((part) => part.text).join("\n");
assert.ok(text.includes("vi3ion-auto"), "evidence block not injected into the request");
assert.ok(text.includes("SPATIAL LAYOUT"), "spatial layout missing");

const evidence = instructionsStore.get("ses_e2e::vi3ion-evidence") || "";
assert.ok(evidence.includes("Image 1280x800"), "brief header missing");

console.log("E2E VISIONLESS OK");
console.log("--- injected evidence (first 1200 chars) ---");
console.log(evidence.slice(0, 1200));

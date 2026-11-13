// End-to-end with a REAL attachment taken from an actual OpenCode session.
//
// The attachment JSON (data/inbox/real-attachment.json) is the exact message
// shape OpenCode stores: { mime, data, source: { type: "uri", uri } }.
// This proves the plugin can analyse what a real session delivers.
import fs from "node:fs";
import assert from "node:assert";
import path from "node:path";

import plugin from "./index.js";

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\//, ""));
const REPO_DIR = path.resolve(HERE, "..", "..");
const FIXTURE = path.join(REPO_DIR, "data", "inbox", "real-attachment.json");
if (!fs.existsSync(FIXTURE)) {
  console.log("E2E REAL skipped (no real attachment captured)");
  process.exit(0);
}

const payload = JSON.parse(fs.readFileSync(FIXTURE, "utf8"));

let hooks = {};
const store = new Map();
const instructions = new Map();

const ctx = {
  options: { mode: "always", codeCheck: true },
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
        async put({ sessionID, key, value }) { instructions.set(`${sessionID}::${key}`, value); },
        async remove({ sessionID, key }) { instructions.delete(`${sessionID}::${key}`); },
      },
    },
    async synthetic() {},
  },
  command: { async transform() {} },
};

await plugin.setup(ctx);
assert.ok(hooks.context, "context hook not registered");

const event = {
  sessionID: "ses_e2e_real",
  model: { providerID: "inception", id: "mercury-3" },
  system: [],
  messages: payload.messages,
};

const started = Date.now();
await hooks.context(event);
const elapsed = Date.now() - started;

const text = event.system.map((part) => part.text).join("\n");
assert.ok(text.includes("Vi3ion presence"), "presence missing");
assert.ok(text.includes("vi3ion-auto"), "evidence block missing");

const evidence = instructions.get("ses_e2e_real::vi3ion-evidence") || "";
assert.ok(evidence.includes("vi3ion-auto"), "evidence not stored as session instruction");

console.log(`E2E REAL OK (${elapsed} ms)`);
console.log("--- injected evidence (first 900 chars) ---");
console.log(evidence.slice(0, 900));

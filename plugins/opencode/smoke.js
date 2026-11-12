// Smoke test: stub OpenCode ctx, attach sample_ui.png, assert evidence injected.
"use strict";

const plugin = require("./index.js");
const fs = require("node:fs");
const assert = require("node:assert");

const IMG = "D:\\PROJECTS\\VI3ION\\tests\\fixtures\\sample_ui.png";
assert.ok(fs.existsSync(IMG), "sample image missing");

let hookFn = null;
let promptEvent = null;

const ctx = {
  options: { mode: "always", codeCheck: false },
  storage: {
    async get() { return undefined; },
    async set() {},
  },
  model: {
    async default() { return { providerID: "inception", id: "mercury-3" }; },
  },
  session: {
    async hook(name, fn) {
      assert.strictEqual(name, "prompt");
      hookFn = fn;
    },
  },
};

(async () => {
  await plugin.setup(ctx);
  assert.ok(hookFn, "hook not registered");

  promptEvent = {
    prompt: {
      text: "here is a screenshot, please look at the save area",
      files: [{ uri: "file:///D:/PROJECTS/VI3ION/tests/fixtures/sample_ui.png" }],
    },
  };
  await hookFn(promptEvent);

  assert.ok(promptEvent.prompt.text.includes("vi3ion-auto"), "evidence context not injected");
  assert.ok(promptEvent.prompt.text.includes("Save"), "OCR text missing from evidence");
  console.log("SMOKE OK");
  console.log(promptEvent.prompt.text.slice(0, 500));
})().catch((err) => {
  console.error("SMOKE FAILED:", err);
  process.exit(1);
});

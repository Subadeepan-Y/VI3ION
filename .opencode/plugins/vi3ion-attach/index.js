// Compatibility entry point.
//
// The plugin source now lives in plugins/opencode/ (it is published to npm as
// @vi3ion/opencode). This file keeps existing OpenCode configurations that
// point at .opencode/plugins/vi3ion-attach working.
export * from "../../../plugins/opencode/index.js";
export { default } from "../../../plugins/opencode/index.js";

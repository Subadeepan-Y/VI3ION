# Running Vi3ion with local models

Vi3ion is the perception layer for agents. When the agent's model is local
(Ollama, llama.cpp, LM Studio, vLLM, Unsloth, SGLang, LocalAI, jan,
koboldcpp, text-generation-webui), Vi3ion has three jobs:

1. Be the **eyes** for models that cannot read pixels.
2. Stay **out of the way** for local vision models that can.
3. Stay **cheap**: low RAM, low CPU, small token footprint.

## 1. See what is running

```powershell
vi3ion local          # runtimes + models + which ones accept images
vi3ion local --json   # same, machine readable
```

Output looks like:

```
llama.cpp             127.0.0.1:8080  reachable
                      openai-compatible: http://127.0.0.1:8080/v1
                      - qwen3-8b (text)
                      - qwen2.5vl-7b (vision)

No local vision model detected: Vi3ion is the eyes for local models.
```

In OpenCode, `/vi3ionlocal` prints the same in the chat and `/vi3ionstatus`
adds it to the status line.

The MCP tool `local_stack` exposes the same data to the agent itself.

## 2. Point OpenCode at the local model

```jsonc
{
  "provider": {
    "llamacpp": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "llama.cpp",
      "options": {
        "baseURL": "http://127.0.0.1:8080/v1",
        "apiKey": "dummy"
      },
      "models": {
        "qwen2.5vl-7b": { "name": "Qwen2.5-VL 7B", "limit": { "context": 32768, "output": 4096 } }
      }
    }
  }
}
```

Ollama uses `http://127.0.0.1:11434/v1` with the same openai-compatible npm
package.

## 3. What Vi3ion does automatically for local models

| Behaviour | Local model | Cloud model |
|---|---|---|
| Vision detection | `capabilities.input`, then name heuristics (`llava`, `qwen2.5-vl`, `minicpm-v`, `gemma3`, `llama3.2-vision`, `internvl`, `pixtral`, `smolvlm`, …) | declared modalities + known names |
| Evidence tier | `compact` | `compact` below 32K, else `full` |
| Token budget | ~8% of the context window (min 200, max 900) | unlimited in `full` tier |
| Second analysis pass | skipped (code cross-check only when `codeCheck: true`) | on |
| Role for a text-only model | Vi3ion is the eyes | Vi3ion is the eyes |
| Role for a vision model | model's own vision leads; Vi3ion assists | same |

A local model that cannot see images gets the same treatment as any
vision-less model: the intro states it must use Vi3ion evidence and must never
describe an image from its filename.

## 4. Keep the evidence small

The token budget is derived from the model's context window. Override it when
needed:

- In OpenCode: `/vi3ionbudget 400` (0 = auto).
- In the CLI: `vi3ion brief screenshot.png --budget 400`.

With a budget, sections are kept in priority order — OCR text first, then
omission notes, composition, colour, scene prose, and the honesty note last.

## 5. Model switching

A user can switch models mid-conversation. Vi3ion re-binds automatically:

- the intro block is re-injected with the new model and its role,
- the next request carries a role-change notice,
- the evidence tier and budget are recomputed for the new model.

No manual step is needed, and switching models never drops the evidence that
was already collected.

## 6. If the local model is not detected as vision capable but it is

Name heuristics are conservative on purpose. Override per session with
`/vi3ionon` and `mode: "always"` in the plugin options, or rename the model
so the hint is visible (`qwen2.5vl-7b` is recognised; `my-model` is not).

## 7. Checks

```powershell
node .\.opencode\plugins\vi3ion-attach\smoke.mjs        # hook behaviour
node .\.opencode\plugins\vi3ion-attach\e2e_local.mjs    # local-model path, real screenshot
node .\.opencode\plugins\vi3ion-attach\e2e_visionless.mjs
```

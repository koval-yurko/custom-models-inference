# Model tabs

The UI reads `models.json` and shows one tab per model. The URL hash selects the tab. Each tab shows its title, type, model name and base URL, and keeps its state when the user switches tabs. A type with no panel shows a clear message.

## Sub-features

- `tabs-list` shows one link per entry in `models.json`, in order.
- `tabs-hash` selects the tab from `#/<id>` and updates when the hash changes. No hash selects the first tab.
- `tabs-keep-state` keeps a chat or audio result when the user switches tabs and back.
- `tabs-no-panel` shows `No panel for type "<type>" yet. Add one with the model-ui skill.` for an unknown type.
- `tabs-bad-config` shows an error when `models.json` is missing or invalid.

## How to get to it (user POV)

- Choose a tab link (`TTS mock`, `LLM mock`, `STT mock`) in the header.
- Open `<ui_url>`, `<ui_url>#/llm-mock` or another `#/<id>` URL directly.

## Driving it with Paseo browser

Preconditions:

- `./scripts/verify-ui.py doctor` passes.

Read the active tab with `browser_evaluate` `() => document.querySelector('nav a.active')?.textContent`. The snapshot does not show which link is active.

- **List.** Open `<ui_url>` and `browser_wait` for `Fill a long text`. The `navigation` has the links `TTS mock`, `LLM mock`, `STT mock`, and the TTS tab shows (no hash selects the first entry).
- **No panel.** Click the link `STT mock`. The URL ends with `#/stt-mock`, the active link is `STT mock`, and the visible tab text is `STT mock stt · whisper · <mock_url>` and `No panel for type "stt" yet. Add one with the model-ui skill.`.
- **Hash.** Run `browser_navigate` to `<ui_url>#/llm-mock`. The active link is `LLM mock`, and the heading reads `LLM mock llm · gemma-4-12b · <mock_url>`.
- **Keep state.** With the key `test`, send `keep me` on `LLM mock` and `browser_wait` for `tok/s`. Click `TTS mock`, then `LLM mock`. The chat still shows `keep me` and `Echo: keep me. The sea is wide and deep.`.
- **Proof.** Save the screenshot after the keep-state step, the results of the `browser_evaluate` checks and the `mock.log` line of `keep me` as `model-tabs.*` in `<run_dir>/evidence/`.

## Gotchas

- `tabs-bad-config` needs a broken `ui/public/models.json`, which `verify-ui.py` owns during a run. Do not edit it by hand in a shared run. Unit tests in `ui/src/lib.test.ts` cover `parseModels`.
- A `base_url` must start with `https://`, `http://localhost` or `http://127.0.0.1`, or the whole config fails to load.
- Every tab stays mounted. The TTS tab loads voices when the page opens, even when you open another tab. With no key, that call adds a `GET /v1/audio/voices 403 bad key` line to `mock.log`.
- When the STT panel is added, `stt-mock` stops showing the "no panel" message. Then move `tabs-no-panel` to a test type, and add an STT feature file.

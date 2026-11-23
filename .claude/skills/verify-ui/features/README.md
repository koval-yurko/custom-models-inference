# Model test UI verification map

This directory is the maintained source for verifying the user-facing behavior of the model test UI (`ui/`). Read this index before you drive the app, then use the matching feature file as the recipe. Launch, doctor, evidence and cleanup are in `../SKILL.md`.

## Baseline preconditions

- `./scripts/verify-ui.py up` printed `READY` and `./scripts/verify-ui.py doctor` passes.
- The UI is at `ui_url` and the mock at `mock_url` from `.verify/ui/current.json`. Ports change on every run.
- The mock config has 4 tabs: `tts-mock` (type `tts`), `llm-mock` (type `llm`, 3 platforms), `llm-routes-mock` (type `llm-routes`), `stt-mock` (type `stt`, STT-A mock, 2 platforms). All point to the mock. A platform calls `<mock_url>/<platform id>`, and the mock drops the prefix (see `platform-picker.md`).
- The mock accepts only the API key `test`. A new run starts with no key in the browser.
- Never drive an instance that this run did not start.

## Driving conventions

- Drive with the Paseo browser tools (`mcp__paseo__browser_*`).
- Find elements by accessible name in `browser_snapshot`, not by position or coordinates.
- Enter text with `browser_type`. `browser_fill` does not update React state. To replace text, `browser_fill` with `""` first.
- Take a new snapshot after each action that changes the page. Refs expire.
- Start each recipe from a fresh tab at `<ui_url>#/<tab-id>`.

## Proof and skip reporting

- Capture the user action and the result: the request line in `<run_dir>/mock.log` and the panel text.
- UI proof is a screenshot plus the `innerText` of the visible tab, in `<run_dir>/evidence/<feature-id>.*`.
- Record the feature ID and the entry point in each file name or file.
- When a precondition is missing, report the step, the command and the missing precondition. Do not weaken the journey.
- Do not report an entry point as verified through a different entry point.
- A pass against the mock proves the UI, not a real gateway or model. Say so.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph about the user-visible behavior. Then it has exactly 4 H2 sections in this order.

1. `Sub-features` lists short IDs with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with Paseo browser` starts with `Preconditions:` and uses labeled bullets that pair each user action with an exact tool call and an observable result.
4. `Gotchas` lists traps that can waste or invalidate a run.

## Features

- [LLM chat](./llm-chat.md) covers send by button and by Enter, streaming and non-streaming answers, timings, curl, stop and new chat. Its `llm-send-button` and `llm-send-enter` paths were proved end to end on 2026-11-14.
- [TTS speech](./tts-speech.md) covers voices, full-file and streamed audio, download and timings. All recipe steps were driven on 2026-11-14.
- [API key](./api-key.md) covers entering, showing, clearing and persisting the key, and the wrong-key error. All recipe steps were driven on 2026-11-14.
- [STT transcribe and history](./stt-transcribe.md) covers upload, the first version, transcribe again with a label, 2 versions side by side and the file link. All recipe steps were driven on 2026-11-21.
- [Model tabs](./model-tabs.md) covers tabs from `models.json`, hash routes, kept panel state and the "no panel" message. All recipe steps except `tabs-bad-config` were driven on 2026-11-14.

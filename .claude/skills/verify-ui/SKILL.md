---
name: verify-ui
description: Drive the model test UI (ui/, React + Vite, one tab per model) the way a user does, against the local mock gateways, and capture proof. Use to prove a change in ui/, ui/mock-server.mjs or a panel works in a real browser (chat, TTS, API key, tabs), before you say a UI change is done. No GCP, no cost.
---

# Verify the model test UI

The test UI is a static React app in `ui/`. A user opens it, enters the API key in the header, picks a model tab and sends a request to that model's API Gateway. This skill runs the same app on your machine against `ui/mock-server.mjs`, a local stand-in for the gateways (TTS and LLM routes, key `test`). You drive it in the Paseo browser and keep the proof in `.verify/ui/<run-id>/`.

Scope:

- Primary surface: the test UI against the mock. Everything here is local and free.
- Not covered: the real gateways (`https://...gateway.dev`), Cloud Run and Vertex AI. A call to them can start a GPU replica (about $1.34 per hour). Drive them only when the user asks in the same message, and follow the "UI test with Claude in Chrome" steps in `CLAUDE.md`.
- Not covered: Terraform. Use `./scripts/check.py` and the `terraform-change-checklist` skill for that.

Read `features/README.md` before you drive, then the feature file for the change.

Fast path first. Before a browser run, run what is faster and proves part of the change:

- Pure logic (`parseModels`, SSE, PCM, WAV): `cd ui && npm test` (under 1 s).
- The mock routes and the CORS answers: `./scripts/verify-ui.py doctor` (curl-level, 1 s).
- The real gateways, auth and CORS: the `verify-gcp` skill, level 3 (`./scripts/verify-gcp.py smoke`, about 3 s).

Use the browser only for what these cannot see: React state, button states, streaming playback, error texts and tab state.

## Launch

```sh
./scripts/verify-ui.py up
```

What it does:

1. Runs `npm ci` in `ui/` when `ui/node_modules` is missing (the first run takes about 30 s).
2. Picks 2 free ports. It writes `ui/public/models.json` from `ui/public/models.mock.json`, with every `base_url` set to the mock port. It keeps a copy of an existing `models.json` and restores it in `down`.
3. Starts `node mock-server.mjs` (with `MOCK_PORT`) and `vite --host 127.0.0.1 --port <port> --strictPort`, each in its own process group. Logs go to `.verify/ui/<run-id>/mock.log` and `vite.log`.
4. Waits until every doctor check passes, then prints the state and a line like `READY http://127.0.0.1:57136/  key: test  evidence: .../.verify/ui/<run-id>/evidence/`.

Ready means all of these are true: both processes own their ports, Vite serves the page and this run's `models.json`, and the mock accepts the key `test` and rejects a wrong key. If `up` prints `Not ready`, read the 2 logs, then run `down`.

The state of the active run is in `.verify/ui/current.json` (`ui_url`, `mock_url`, pids, ports, `run_dir`).

Isolation: one run per checkout, because `ui/public/models.json` is shared. `up` refuses to start when a run is active. For a parallel run, use another git worktree: the ports are free ports, so worktrees do not collide. Never drive a UI that this run did not start (for example a developer's own `npm run dev` on port 5173).

## Doctor

```sh
./scripts/verify-ui.py doctor
```

Read-only. It prints `ok` or `FAIL` for each check and exits 1 on a failure. Run it first when something looks wrong. A `models.json ... found [...]` failure means something else (for example `scripts/ui-deploy.py --local`) overwrote `ui/public/models.json`: run `down`, then `up`.

## Drive

Use the Paseo browser tools (`mcp__paseo__browser_*`; load them with ToolSearch `select:` first). Refs (`@e4`) come from the latest `browser_snapshot` and expire when the page changes, so take a new snapshot after every action that changes the page.

1. Open the tab at the feature's route: `browser_new_tab` with `<ui_url>#/<tab-id>`. Tab IDs from the mock config: `tts-mock`, `llm-mock`, `stt-mock`.
2. `browser_wait` for a text that the tab shows when it is loaded (each feature file names it).
3. `browser_snapshot`. Find elements by their accessible name, not by position:
   - Tabs: links `TTS mock`, `LLM mock`, `STT mock` in the `navigation`.
   - API key: the `textbox` and the buttons `Show` and `Clear` in the `banner`. All 3 share one accessible name that changes with the state (`API keyShowClear`, `API keyHideClear`). Pick them by role and visible text, not by that name.
   - Labels that wrap a field put the field content in its name (for example `TextHello from the test UI.`). Match the start of the name. Disabled fields have no ref.
   - The rest: see the feature file.
4. Enter text with `browser_type`, not `browser_fill`. `browser_fill` sets the DOM value but React does not see it: the button stays disabled. To replace a value, first `browser_fill` with `""`, then `browser_type` the new text.
5. Click with `browser_click`. Wait for the result text with `browser_wait` (`timeoutMs` up to 30000).
6. Read the result: `browser_evaluate` with `() => document.querySelector('main > div:not([hidden])').innerText` returns the text of the visible tab.

The key persists in the browser's `localStorage` (`model-test-ui.api-key`) for the origin `http://127.0.0.1:<ui_port>`. A new run has a new port, so it starts with no key.

## Evidence

Put all proof in `<run_dir>/evidence/`, with the feature ID in each file name:

- `<feature>.png`: a screenshot after the result shows. `browser_screenshot` saves the PNG under the session's `tool-results/` folder and names the path in its result. Copy that file with `cp`.
- `<feature>.panel.txt`: the `innerText` of the visible tab after the result (step 6 of Drive). Write it exactly as returned.
- `<feature>.mock-requests.txt`: the mock's own log of the request (`grep <route> <run_dir>/mock.log`). This proves the click reached the server with the right body. A screen alone is not proof.

Proof standards:

- Drive the user path: type and click in the page. Do not call the mock with curl or set React state from `browser_evaluate` to make a result appear.
- Capture the action and the result: the request line in `mock.log` and the answer in the panel.
- The mock is a stand-in for the gateways. A pass here proves the UI logic, not a real model, gateway CORS or a cold start on Vertex AI. Say so in your report.

## Cleanup

1. `browser_close_tab` for every tab you opened.
2. `./scripts/verify-ui.py down`. It stops only the 2 process groups that `up` started (by pid, never by name), restores or removes `ui/public/models.json` and removes `.verify/ui/current.json`.
3. Confirm that `<run_dir>/evidence/` still has your files. `down` never deletes the run dir.

Run `down` after a failed attempt too, so no process keeps a port. Old run dirs stay in `.verify/` (git-ignored). Delete them when the user no longer needs them.

## Helpers

- `scripts/verify-ui.py up | doctor | down`: see above. Python 3 standard library only. It needs `node`, `npm` and `lsof`.
- `ui/mock-server.mjs`: `MOCK_PORT=<port> node ui/mock-server.mjs` (default 5181). It logs one line per request: time, method, path, then the body, or `403 bad key` for a rejected key. When you add a panel for a new model type, add its routes here (see the `model-ui` skill) and add a feature file to `features/`.

After the app changes, keep `features/` current with the pstack skill `/pstack:maintain-verification-skill`.

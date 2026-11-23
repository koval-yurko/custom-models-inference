# Platform picker

A model tab with 2 or more platforms (Vertex AI, Runpod) has a platform picker above the panel. The user picks the platform, and the panel calls the gateway path of that platform (`/<platform><route>`). The choice is kept per model in the browser and in the hash (`#/<tab>@<platform>`).

## Sub-features

- `picker-shows` shows the picker only for a model with 2 or more platforms. The first platform is pressed by default.
- `picker-routes` sends the panel request to `/<platform><route>`.
- `picker-keeps-chat` keeps the chat when the user switches platform (the panel stays mounted).
- `picker-wait` shows the live wait line during a cold start, and the chat sends again after a gateway time limit.
- `picker-stored` keeps the last choice after a reload of `#/<tab>` (no platform in the hash).
- `picker-link` saves a platform that comes from a link, so the tab link keeps it.
- `picker-stt-link` keeps the platform when the STT panel opens a file link `#/<tab>/<file id>`.

## How to get to it (user POV)

- Choose the tab link `LLM mock` or `STT-A mock` in the header.
- Open `<ui_url>#/llm-mock@runpod` directly.

## Driving it with Paseo browser

Preconditions:

- `./scripts/verify-ui.py doctor` passes.
- The API key `test` is entered (see `api-key.md`).

1. **Picker shows.** Open `<ui_url>#/llm-mock`. The group `Platform` has the buttons `Vertex AI` and `Runpod`. `Vertex AI` is pressed (`aria-pressed=true`). The heading ends with `Vertex AI · <mock_url>/vertex`.
2. **Route.** Click `Runpod`. The hash is `#/llm-mock@runpod`. Send `picker ping`. `grep runpod <run_dir>/mock.log` has `POST /runpod/v1/chat/completions`.
3. **Chat kept.** Click `Vertex AI`, then `Runpod`. The chat still shows `picker ping` and its echo answer.
4. **Wait line.** Start the mock with `MOCK_DROP_MS=32000 MOCK_COLD_MS=8000`. Click `Runpod` and send a message. After 3 s the text `Waiting for Runpod…` shows with a running time. At about 0:32 the mock answers 504 without CORS headers; the line then says `attempt 2`, and `mock.log` has a second `POST /runpod/v1/chat/completions` about 2 s later. The answer comes after about 40 s.
5. **Stored choice.** Open `<ui_url>#/llm-mock` and reload. `Runpod` (the last click) is still pressed.
6. **No picker.** Open `<ui_url>#/tts-mock`. There is no group `Platform`.
7. **STT link.** Open `<ui_url>#/stt-mock`, click `Runpod`, transcribe a file and open it from the list. The hash becomes `#/stt-mock/<file id>`, and `Runpod` stays pressed. `mock.log` has `/runpod/v1beta/...` lines.
8. **Link choice is saved.** In a new run (empty storage), open `<ui_url>#/llm-mock@runpod`. `Runpod` is pressed. Click the tab link `TTS mock`, then `LLM mock`. `Runpod` is still pressed.
9. **Proof.** Save the screenshots, the hash and the `mock.log` lines as `platform-picker.*` in `<run_dir>/evidence/`.

## Gotchas

- The mock drops the `/vertex` or `/runpod` prefix, so all platforms give the same answer. The proof that the platform was used is the path in `mock.log`, not the answer.
- Without `MOCK_DROP_MS` and `MOCK_COLD_MS` the mock answers at once, so there is no wait line. A cut connection (instead of the 504) is sent again by the browser itself, so it does not test the UI retry.

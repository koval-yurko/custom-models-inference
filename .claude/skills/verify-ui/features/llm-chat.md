# LLM chat

The LLM tab is a chat with an OpenAI-compatible model. The user types a message, sends it and sees the answer appear, token by token when streaming is on, with HTTP status, time to first token, total time and tokens per second.

## Sub-features

- `llm-send-button` sends the message with the `Send` button.
- `llm-send-enter` sends with Enter. Shift+Enter makes a new line.
- `llm-stream` shows the answer while it streams (SSE) and reports tokens from the usage chunk.
- `llm-no-stream` waits for the full answer when `Stream (SSE)` is off.
- `llm-curl` shows the same request as a curl command, with `$KEY` instead of the key.
- `llm-stop-new` stops an answer with `Stop` and clears the chat with `New chat`.

## How to get to it (user POV)

- Choose the tab link `LLM mock` in the header.
- Open `<ui_url>#/llm-mock` directly.

## Driving it with Paseo browser

Preconditions:

- `./scripts/verify-ui.py doctor` passes.
- The API key `test` is entered (see `api-key.md`), so the notice `Enter the API key in the header` is gone.

- **Open the tab.** Run `browser_new_tab` with `<ui_url>#/llm-mock` and `browser_wait` for `No messages yet.`. The heading reads `LLM mock llm · gemma-4-12b · Vertex AI · <mock_url>/vertex` (the default platform; see `platform-picker.md`).
- **Enter the key.** Run `browser_type` on the textbox `API keyShowClear` with `test`. The notice `Enter the API key in the header` disappears.
- **Type a message.** Run `browser_type` on the textbox `Message… (Enter sends, Shift+Enter is a new line)` with `verify-ui ping`. A new snapshot shows the button `Send` with a ref (it is enabled).
- **Send.** Run `browser_click` on `Send`, then `browser_wait` for `tok/s` (`timeoutMs` 15000). The chat shows `You` / `verify-ui ping` and `LLM mock` / `Echo: verify-ui ping. The sea is wide and deep.`. Timings show `HTTP 200`, `First token`, `Total` and `Tokens 9 (... tok/s)`.
- **Check the server side.** Run `grep chat/completions <run_dir>/mock.log`. One line has `"messages":[{"role":"user","content":"verify-ui ping"}]` and `"stream":true`.
- **Send with Enter.** Type `second` in the message textbox and press Enter (`browser_keypress` `Enter`). A second echo answer appears, and `mock.log` has a request with 3 messages (user, assistant, user).
- **No stream.** Click the checkbox `Stream (SSE)` to clear it and send `plain`. The answer appears at once. `mock.log` shows `"stream":false`.
- **Curl.** Click `Request as curl`. The text starts with `curl -sS -N -X POST "<mock_url>/vertex/v1/chat/completions"` and has `-H "x-api-key: $KEY"`, not the key.
- **New chat.** Click `New chat`. The text `No messages yet.` returns and the timings show `–`.
- **Proof.** Save the screenshot, the panel `innerText` and the `mock.log` lines as `llm-chat.*` in `<run_dir>/evidence/`.

## Gotchas

- `browser_fill` on the message textbox does not enable `Send`. Use `browser_type`.
- The mock always answers `Echo: <last message>. The sea is wide and deep.` (9 words). It ignores `max_tokens`, `temperature` and the system prompt. Check those fields in `mock.log`, not in the answer.
- The mock never returns HTTP 429, so the Vertex AI cold-start retry (`Model is starting (HTTP 429)… retry n/60`) cannot be driven here. It retries every 30 s, so do not try to wait for it.
- A streamed answer takes about 0.8 s. Wait for `tok/s`, not for the echo text, or you read the timings before the usage chunk.
- The number inputs show the browser's locale (`0,7`). The request still sends `0.7`.
- After a failed request (for example a wrong key), the chat keeps an empty `LLM mock` answer. The next request sends it as `{"role":"assistant","content":""}`. Click `New chat` first when the request body matters.

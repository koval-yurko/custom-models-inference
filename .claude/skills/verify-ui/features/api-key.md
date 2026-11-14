# API key

Every request from the UI sends the header `x-api-key`. The user enters the key once in the header field. It stays in this browser (`localStorage`), it is hidden by default, and it can be shown or cleared.

## Sub-features

- `key-enter` stores the key and removes the notice `Enter the API key in the header`.
- `key-show` toggles the field between hidden and plain text.
- `key-clear` removes the key and shows the notice again.
- `key-persist` keeps the key after a page reload.
- `key-wrong` shows the error of a rejected request.

## How to get to it (user POV)

- The `API key` field, with the buttons `Show` and `Clear`, is in the header of every tab.

## Driving it with Paseo browser

Preconditions:

- `./scripts/verify-ui.py doctor` passes.
- The tab is new in this run, so no key is stored for this origin.

The field and both buttons have no accessible name of their own. In the snapshot, all 3 have the same name: `API keyShowClear` while the key is hidden, `API keyHideClear` while it shows. Find them in the `banner` by role and visible text: the `textbox`, the `button` with the text `Show` (or `Hide`), and the `button` with the text `Clear`. Do not search by that name: it changes with the state.

- **No key.** Open `<ui_url>#/llm-mock`. The main area shows `Enter the API key in the header (terraform output -raw api_key in infra/core).`.
- **Enter the key.** Run `browser_type` on the header `textbox` with `test`. The notice disappears. `browser_evaluate` `() => localStorage.getItem('model-test-ui.api-key')` returns `"test"`, and `document.querySelector('header input').type` is `"password"`.
- **Show.** Click the button with the text `Show`. Its text changes to `Hide`, and the field type changes to `text`. Click `Hide` to hide it again.
- **Persist.** Run `browser_reload`, then `browser_wait` for `No messages yet.`. The notice stays hidden, the field holds 4 characters and its type is `password`.
- **Clear.** Click the button with the text `Clear`. The field is empty, the notice returns, and `localStorage.getItem('model-test-ui.api-key')` returns `null`.
- **Wrong key.** Type `wrong` in the header `textbox`. Type `ping` in the message textbox of the LLM tab and press Enter (`browser_keypress` `Enter`). `browser_wait` for `Error: HTTP 403: bad key`. The timings show `HTTP 403`. `grep chat/completions <run_dir>/mock.log` shows a line that ends with `403 bad key`.
- **Replace the key.** `browser_fill` the header `textbox` with `""`, then `browser_type` `test`. `localStorage.getItem('model-test-ui.api-key')` returns `"test"`.
- **Proof.** Save the screenshot and the panel `innerText` after the wrong-key step, the results of the `browser_evaluate` checks, and the `mock.log` line as `api-key.*` in `<run_dir>/evidence/`.

## Gotchas

- The mock answers a wrong key with HTTP 403 and CORS headers, so the UI shows the real status (`Error: HTTP 403: bad key`). A real gateway answers without CORS headers, and the UI shows `Request to ... failed. Most likely a wrong API key ...` instead. The mock cannot reproduce that text.
- After a rejected chat request, the chat keeps an empty `LLM mock` answer. The next request sends it as `{"role":"assistant","content":""}`. Click `New chat` before you test with the right key, or expect that message in `mock.log`.
- `browser_fill` sets the field but React does not store the key. Use `browser_type`.
- Never type the real gateway key here. The mock key is `test`.

# STT transcribe and history

The STT tab keeps every uploaded audio file and every transcript run (spec: `docs/specs/2026-11-21-stt-a-design.md`). The user uploads a file, and the first transcript starts at once. "Transcribe again" makes a new version of a stored file, with an optional label. The versions table lists the runs. 1 ticked version shows in full (1 line per speaker turn, 1 color per speaker). 2 ticked versions show side by side. The URL `#/stt-mock/<file id>` opens a file directly.

## Sub-features

- `stt-upload` sends `POST /v1beta/uploads` (with `name`), the signed `PUT`, then `POST /v1beta/files/<id>/transcribe`. The file appears in the list with 1 version, and the URL gets the file id.
- `stt-again` sends `transcribe` again with the label, and a new version appears at the top of the table.
- `stt-compare` shows 2 ticked versions side by side.
- `stt-link` opens `#/stt-mock/<file id>` in a new tab and shows the file and its versions.
- `stt-curl` shows the `transcribe` call as curl with `$KEY`.

## How to get to it (user POV)

- Choose the tab link `STT-A mock` in the header.
- Open `<ui_url>#/stt-mock` or `<ui_url>#/stt-mock/<file id>` directly.

## Driving it with Paseo browser

Preconditions:

- `./scripts/verify-ui.py doctor` passes.
- The API key `test` is entered (see `api-key.md`).
- A WAV file inside the worktree, because `browser_upload` takes workspace paths only. Make it in `<run_dir>` with `python3 -c "import wave; w=wave.open('<run_dir>/stt-small.wav','wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\x00\x00'*32000); w.close()"`. Delete it after the run.

- **Open the tab.** Run `browser_new_tab` with `<ui_url>#/stt-mock` and `browser_wait` for `Upload a file`. Before the key is entered, the tab shows `Error: HTTP 403: bad key` (the list loads at once). This is expected.
- **Upload.** Enter the key, then run `browser_upload` on the textbox `Upload a file (up to 500 MB; it is kept, so you can transcribe it again later)` with `<run_dir>/stt-small.wav`, and `browser_wait` for `mock run 1`. The list shows `stt-small.wav 1 version`, the URL ends with `#/stt-mock/<uuid>`, and the table has 1 row. `mock.log` has, in this order: `POST /v1beta/uploads {"name":"stt-small.wav",...}`, `PUT /mock-upload/<uuid> 64044 bytes audio/wav`, `POST /v1beta/files/<uuid>/transcribe {"diarization":true}`.
- **Again.** Type `t2` in the textbox `Label`, click `Transcribe again`, and `browser_wait` for `mock run 2`. The table has 2 rows; the top row has the label `t2`. `mock.log` has `transcribe {"diarization":true,"label":"t2"}`.
- **Compare.** Click the unticked checkbox `Show <time>` of the older row, and `browser_wait` for `mock run 1`. Both transcripts show side by side.
- **Link.** Open the same URL in a new tab and `browser_wait` for `mock run 2`. The file and its 2 versions show. The key is still in `localStorage` (same origin).
- **Proof.** Save the screenshot, the panel text and the `mock.log` lines as `stt-history.*` in `<run_dir>/evidence/`.

## Gotchas

- The mock answer is fixed: 3 turns of 2 speakers. Only `run N` in the first line changes, so 2 versions differ. Check the requests in `mock.log`.
- The mock keeps files in memory. `down` and `up` start with an empty list.
- The mock `PUT` route needs no API key, as a real signed GCS URL. The browser sends it with plain `fetch`.
- A pass here proves the UI logic. It does not prove the real files service, GCS, the GCS CORS rule or the model.

# STT transcribe and history

The STT tab keeps every uploaded audio file and every transcript run (spec: `docs/specs/2026-11-21-stt-a-design.md`). The user uploads a file, and the first transcript starts at once. "Transcribe again" makes a new version of a stored file, with an optional label. The versions table lists the runs. 1 ticked version shows in full (1 line per speaker turn, 1 color per speaker). 2 ticked versions show side by side. The URL `#/stt-mock/<file id>` opens a file directly.

## Sub-features

- `stt-upload` sends `POST /v1beta/uploads` (with `name`), the signed `PUT`, then `POST /v1beta/files/<id>/transcribe`. The file appears in the list with 1 version, and the URL gets the file id.
- `stt-again` sends `transcribe` again with the label, and a new version appears at the top of the table.
- `stt-compare` shows 2 ticked versions side by side.
- `stt-link` opens `#/stt-mock/<file id>` in a new tab and shows the file and its versions.
- `stt-rename` saves names for the speakers of 1 version (`PUT .../versions/<id>/names`). The names show in the turns of that version, also after a reload and in the compare view. Other versions keep `spk_N`.
- `stt-play` plays 1 speaker turn: `GET /v1beta/files/<id>/audio`, then the signed `GET` (`/mock-audio/<id>`, with a `Range` header). The row is highlighted and its button shows `■` while it plays. The audio stops at the end of the turn.
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
- **Rename.** Type `Alice` in `Name of spk_1` and `Bob` in `Name of spk_2`, click `Save names`, and `browser_wait` for `Bob 00:00:02`. Reload, tick both versions, and check that only 1 transcript shows `Alice`. `mock.log` has `PUT .../names {"spk_1":"Alice","spk_2":"Bob"}`.
- **Play.** Use a WAV with sound of 7 s or more (the mock turns end at 5.35 s), for example a 440 Hz tone. Before the click, record the audio events with `browser_evaluate` (`seeked`, `playing`, `pause` and `currentTime`; this only reads). Click `Play turn 2`. Expect `playing` at 2.5 and `pause` within 0.3 s after 4.45.
- **Proof.** Save the screenshot, the panel text and the `mock.log` lines as `stt-history.*` in `<run_dir>/evidence/`.

## Gotchas

- The mock answer is fixed: 3 turns of 2 speakers. Only `run N` in the first line changes, so 2 versions differ. Check the requests in `mock.log`.
- The mock `/mock-audio/<id>` route needs no API key, as a real signed GCS URL. It answers `Range` requests (`206`), because the `<audio>` element seeks with them.
- The mock keeps files in memory. `down` and `up` start with an empty list.
- The mock `PUT` route needs no API key, as a real signed GCS URL. The browser sends it with plain `fetch`.
- A pass here proves the UI logic. It does not prove the real files service, GCS, the GCS CORS rule or the model.

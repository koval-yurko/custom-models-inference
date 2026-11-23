# STT transcribe and history

The STT tab keeps every uploaded audio file and every transcript run (specs: `docs/specs/2026-11-21-stt-a-design.md`, layout: `docs/specs/2026-11-24-stt-ui-layout-design.md`). The tab has 3 columns: files | history | work area. The history column starts with the reference row of the file (optional, 1 per file), then "＋ New run", then 1 card per version (newest first). A version shows the Transcript tab. The reference row shows Edit, and with a saved reference also Evaluation and Speakers. A sticky player is at the top of the work area. The URL is `#/stt-mock/<file id>[/<version id>|/ref/<edit|evaluation|speakers>?v=<version id>]`; `#/stt-mock/all` is the All files view.

## Sub-features

- `stt-upload` sends `POST /v1beta/uploads` (with `name`), the signed `PUT`, then `POST /v1beta/files/<id>/transcribe`. The file card appears with 1 version and `no reference`, and the URL gets the file id and the version id.
- `stt-again` sends `transcribe` again with the values of "＋ New run" (label), and a new card appears at the top of the history. The URL selects it.
- `stt-compare` shows the selected version and 1 ticked version (`Compare <time>`) side by side.
- `stt-link` opens a copied URL in a new tab and shows the same file, row and tab.
- `stt-rename` without a reference: saves names for the speakers of 1 version (`PUT .../versions/<id>/names`) from the Transcript tab.
- `stt-play` plays 1 speaker turn: `GET /v1beta/files/<id>/audio`, then the signed `GET` (`/mock-audio/<id>`, with a `Range` header). The turn row is highlighted and the audio stops at the end of the turn. The player button plays on to the end of the file.
- `stt-reference` on the reference row: Import (TXT, JSON or Speechmatics JSON), Draft from version, Save (`PUT .../reference`). The reference row then shows the summary, and each card a cpWER chip.
- `stt-evaluation` shows 3 score cards (cpWER, WER, DER) for the working version and 1 row per version.
- `stt-speakers` renames a reference speaker (`PUT .../reference` with the new name) and the version names ("Use the matches", "Save", "Apply to all versions": only empty names, after a confirm box).
- `stt-all` shows the setup table at full width.
- `stt-curl` shows the `transcribe` call as curl with `$KEY` in "Request details".

## How to get to it (user POV)

- Choose the tab link `STT-A mock` in the header.
- Open `<ui_url>#/stt-mock` or a deep link (see above) directly.

## Driving it with Paseo browser

Preconditions:

- `./scripts/verify-ui.py doctor` passes.
- The API key `test` is entered (see `api-key.md`).
- A WAV file inside the worktree, because `browser_upload` takes workspace paths only. Make it in `<run_dir>` with `python3 -c "import wave; w=wave.open('<run_dir>/stt-small.wav','wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\x00\x00'*96000); w.close()"` (6 s, so turn 2 of the mock can play to its end). Delete it after the run.
- For the import: a small Speechmatics JSON in `<run_dir>` (`{"metadata":{"transcription_config":{"language":"en"}},"results":[...]}` with `type`, `start_time`, `end_time`, `alternatives[0].content` and `.speaker`; punctuation has `"attaches_to":"previous"`).

Steps:

- **Open the tab.** Run `browser_new_tab` with `<ui_url>#/stt-mock` and `browser_wait` for `Drop an audio file`. Before the key is entered, the tab shows `Scores: Error: HTTP 403: bad key`. This is expected.
- **Upload (state 1).** Enter the key, then run `browser_upload` on the textbox `Upload a file` with `<run_dir>/stt-small.wav`, and `browser_wait` for `mock run 1`. The card shows `no reference`. The history shows the dashed `＋ Add reference`, no score chip. The work area has only the tab `Transcript` and the name fields.
- **Again.** Click `＋ New run`, type `t2` in `Label`, click `Transcribe`, and `browser_wait` for `mock run 2`. `mock.log` has `transcribe {"diarization":true,"label":"t2"}`.
- **Reference (state 3).** Click the `📌 ＋ Add reference` row. Run `browser_upload` on `Import a reference` with the Speechmatics file; the editor shows lines such as `[00:00:00.1 - 00:00:03.0] S1: Hello there.` Click `Save`, and `browser_wait` for `✓ saved`. The tabs `Edit`, `Evaluation`, `Speakers` show, and each card has a `cpWER` chip.
- **Speakers.** In `Speakers`, replace `Reference name of S1` with `Alice` and click `Rename in reference`; the match of `spk_1` becomes `Alice`. Click `Use the matches`, `Save`, then `Apply to all versions`. The confirm box cannot be clicked by the driver: before the click, replace `window.confirm` with a function that returns `true` (`browser_evaluate`). `mock.log` has 2 `PUT .../names` lines.
- **Reload.** Reload the page on `.../ref/speakers?v=<id>`. The same tab and version show.
- **Compare (state 2).** Tick `Compare <time>` of the older card and click the newer card. 2 transcripts show side by side with the saved names.
- **Play.** Click `Play turn 2`. Expect the audio to start at 2.5 s and pause within 0.3 s after 4.45 s, with the turn highlighted in both transcripts.
- **All files.** Click `📊 All files: scores`. The URL ends with `/all`, the history column hides, and the setup table shows 1 row.
- **Proof.** Save the screenshots, the panel text and the `mock.log` lines as `stt-*.*` in `<run_dir>/evidence/`.

## Gotchas

- The mock answer is fixed: 3 turns of 2 speakers. Only `run N` in the first line changes, so 2 versions differ. Check the requests in `mock.log`.
- The mock `/mock-audio/<id>` route needs no API key, as a real signed GCS URL. It answers `Range` requests (`206`), because the `<audio>` element seeks with them.
- The mock keeps files in memory. `down` and `up` start with an empty list.
- The mock `PUT` route needs no API key, as a real signed GCS URL. The browser sends it with plain `fetch`.
- A pass here proves the UI logic. It does not prove the real files service, GCS, the GCS CORS rule or the model.
- The STT mock tab has 2 platforms. With the default platform, `mock.log` shows each API path with the `/vertex` prefix (for example `POST /vertex/v1beta/uploads`). The signed URLs (`/mock-upload/`, `/mock-audio/`) have no prefix.

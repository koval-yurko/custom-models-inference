# TTS speech

The TTS tab turns text into speech. The user picks a voice, speed and format, then either waits for the full file or streams PCM and hears it while it arrives. The result has an audio player, a download link and timings (first byte, total, size).

## Sub-features

- `tts-voices` loads the voice list from `GET /v1/audio/voices` on open and with `Reload voices`.
- `tts-full` asks for the full file (`Wait for the full file`) and shows a player and a `Download <format>` link.
- `tts-stream` streams PCM (`Stream and play at once (PCM)`), plays it at once and offers a WAV for replay.
- `tts-long-text` fills about 3 minutes of text with one click.
- `tts-curl` shows the request as curl with `$KEY`.

## How to get to it (user POV)

- Choose the tab link `TTS mock` in the header. It is the first tab, so it also opens at `<ui_url>` with no hash.
- Open `<ui_url>#/tts-mock` directly.

## Driving it with Paseo browser

Preconditions:

- `./scripts/verify-ui.py doctor` passes.
- The API key `test` is entered (see `api-key.md`).

The labels wrap their fields, so the accessible name of a field includes its content. In the snapshot, the `Text` textbox is `TextHello from the test UI.`, the `Voice` combobox is `Voiceaf_heart` (`Voiceaf_heartam_adam` after the voices load), and the `Format` combobox is `Formatmp3wavpcm`. Find these by role and the start of the name (`Text`, `Voice`, `Format`). The buttons, radios, `Speed` and the `Download <format>` link have plain names.

- **Open the tab.** Run `browser_new_tab` with `<ui_url>#/tts-mock` and `browser_wait` for `Fill a long text`. The heading reads `TTS mock tts · kokoro · <mock_url>`.
- **Load voices.** After you enter the key, click `Reload voices`. The `Voice` combobox lists `af_heart` and `am_adam`, and the error `Voices: HTTP 403: bad key` is gone. `mock.log` has a `GET /v1/audio/voices` line with no `403`.
- **Full file.** Keep the radio `Wait for the full file`. Run `browser_select` on the `Format` combobox with `wav`, click `Generate`, then `browser_wait` for `Download`. The result reads `Download wav`, `HTTP 200`, `First byte`, `Total` (about 1.5 s) and `Size 117 KB`. `mock.log` has `POST /v1/audio/speech` with `"response_format":"wav"` and `"stream":false`.
- **Stream.** Click the radio `Stream and play at once (PCM)`. The `Format` combobox shows `pcm` and is disabled: it has no ref in the snapshot. Check it with `browser_evaluate` on `[...document.querySelectorAll('main > div:not([hidden]) select')][1]` (`value` is `"pcm"`, `disabled` is `true`). Click `Generate`, then `browser_wait` for `Download wav`. The result shows `Size 117 KB`. `mock.log` has `"response_format":"pcm"` and `"stream":true`.
- **Check the WAV.** Run `browser_evaluate` with `async () => { const a = document.querySelector('main > div:not([hidden]) audio'); const b = await (await fetch(a.src)).arrayBuffer(); return [b.byteLength, new TextDecoder().decode(new Uint8Array(b, 0, 4))]; }`. It returns `[120044, "RIFF"]` (a 44-byte WAV header and 120000 bytes of PCM).
- **Long text.** Click `Fill a long text (about 3 min of audio, to see streaming)`. The `Text` textbox starts with `This is sentence number 1 of a long text to test streaming.`.
- **Proof.** Save the screenshot, the result text, the WAV check and the `mock.log` lines as `tts-speech.*` in `<run_dir>/evidence/`.

## Gotchas

- The tab loads voices once when it opens. With no key yet, that call gets 403 and the tab shows `Voices: HTTP 403: bad key`. Enter the key, then click `Reload voices`. This is expected, not a bug.
- The mock always returns the same 2.5 s of a 440 Hz tone as raw PCM (5 x 24000 bytes), whatever the text, voice, speed or format. In full-file mode, the UI labels these raw PCM bytes as the chosen format (`mp3`, `wav`), so the player cannot play them (from the code; not checked in a run). Only stream mode gives a playable file: the UI wraps the PCM in a WAV header. Check the request fields in `mock.log`.
- The text `Playing while it streams…` shows for only about 1.5 s. `browser_wait` for it usually misses it. Wait for `Download wav` instead.
- The `<audio>` player is not in the snapshot. Read it with `browser_evaluate`.
- Browsers start audio only after a user gesture. Whether a `browser_click` counts as a gesture for audio is not verified. Prove the result by the WAV check and the size, not by sound.
- The mock never returns 429, so the cold-start retry cannot be driven here.

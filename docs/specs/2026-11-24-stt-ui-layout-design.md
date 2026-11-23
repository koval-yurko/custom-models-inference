# Design: STT tab layout (files, history, transcript, reference, evaluation, speakers)

Date: 2026-11-24. Status: layout approved by the user in chat (3 rounds of mockups). This document waits for approval.

## Intent

The STT tab of the test UI (`ui/src/panels/Stt.tsx`) uses the space badly. The page grid is `3fr 2fr` (`.panel` in `ui/src/styles.css`). The left 60 % holds only the upload field, the file list and the "Accuracy per setup" table. The right 40 % holds the file header, the run settings, a version table with 12 columns, the reference editor, the speaker names and the transcripts. At 1440 px each version row wraps to about 6 lines, and the transcripts start below the fold.

The user wants a clear split into 6 parts:

1. Uploaded files.
2. Transcription history (the versions of 1 file).
3. The selected transcription.
4. The ideal reference of the file.
5. Evaluation and comparison.
6. Speaker names, for the transcriptions and for the reference.

The reference is optional. Without a reference, the tab is a plain transcription tool: upload, run, read, listen, rename speakers. Nothing about scores shows.

## Decisions (by the user)

Mockups: `.superpowers/brainstorm/19885-1795473984/content/` (`stt-layout.html`, `history-v3.html`, `final-v1.html`).

1. Frame: 3 columns. Files | history | work area.
2. The reference is 1 per file. It is a pinned first row of the history column, above the versions.
3. The reference is optional. A file without a reference shows a dashed row "＋ Add reference (optional)", no score chips and no Evaluation.
4. Files: cards with status badges, a drop zone at the top and a search field.
5. History: version cards (2 to 3 lines each), newest first, with "＋ New run" at the top.
6. Selected transcription: a reading view with a sticky player.
7. Reference: side by side. The left side shows the ticked version (read only). The right side is the reference text editor.
8. Evaluation: score cards only. No word diff.
9. Speakers: 1 speaker table per file.

## Layout

### Sidebar: files (column 1, about 20 %)

- First row: "📊 All files: scores". It opens the setup table (`GET /v1beta/scores`, `setups`) in the work area at full width. The history column hides in this view.
- A drop zone ("Drop an audio file or click"). It also accepts a click, with the same `accept` list as today.
- A search field. It filters the cards by name, in the browser.
- 1 card per file: name, size, number of versions, date. Badges: "✓ reference" or "no reference". With a reference, also "best cpWER x %" (the lowest `cpwer` of the file in the `rows` of `GET /v1beta/scores`).
- The selected file has the selected style. The Refresh button moves to the sidebar header.

### History column (column 2, about 23 %)

From the top:

1. The pinned reference row.
   - With a reference: "📌 Reference", then "45 turns · 5 speakers · times ✓" (or "no times: no DER").
   - Without a reference: a dashed row "📌 ＋ Add reference (optional: gives scores)".
   - A click selects the row and opens the reference view in the work area.
2. "＋ New run". A click opens a box in place: Language (auto or a code), Speakers (diarization on or off), Label, and "Transcribe". While a run works, a row "running… 0:12" with a Stop button shows under the box. A failed run is not stored. Its error shows in that row until the next run.
3. 1 card per version, newest first:
   - Line 1: a tick box (compare), the time, and with a reference a cpWER chip (green below 20 %, amber from 20 % to 40 %, red above 40 %).
   - Line 2: label (or "no label"), short setup (`setupShort`), number of speakers, run time.
   - A click on the card selects the version. A tick adds it to the compare set (2 at most, as today).

### Work area (column 3, the rest)

A file header: file name, size, created date. Errors and the "busy" line show in a slim bar under the header.

The tabs depend on the row that is selected in the history column:

| Selected row | Tabs |
|---|---|
| A version | Transcript |
| The reference | Edit, Evaluation, Speakers |
| The reference row of a file without a reference | Edit only (an empty editor with the help text) |

#### Transcript (a version)

- A sticky player at the top of the work area: play or pause, the time ("00:55 / 16:28"), a seek bar, a speed choice (1×, 1.25×, 1.5×, 2×) and a "follow" switch. It uses the one `<audio>` element and the signed URL logic of today.
- The turn that plays has a highlight. With "follow" on, the view scrolls to it.
- Each turn is 1 row: ▶ button, start time in a fixed column, speaker name in its colour, text. A click on the time seeks the audio there.
- Above the turns: the version line (time, image tag, label).
- Speaker names: without a reference, the name fields of today show above the turns (1 field per label, "Save names"). With a reference, the names come from the Speakers tab, and a link "Rename speakers" opens it.
- With 2 ticked versions, the 2 transcripts show side by side (as today, `.compare`).
- At the bottom: a closed box "Request details" with `Timings` and `Curl`.

#### Edit (the reference)

- A top bar: state chip ("✓ saved" or "not saved"), a summary (turns, speakers, times), "Draft from version", "Import…", "Save".
- 2 panes side by side:
  - Left: the first ticked version, read only, turns with speaker names and start times.
  - Right: the text editor in the line format of `parseReference` (`[00:00:00.0 - 00:00:04.9] Alice: Hello.`). JSON is also accepted, as today.
- The 2 panes scroll together by time.
- Import accepts `.txt` (line format), `.json` (the reference format) and a Speechmatics JSON transcript (`format`, `results`). Speechmatics JSON is converted in the browser: consecutive items of 1 speaker make 1 turn, punctuation joins the word before it, an entity uses its `content`.
- The language field stays in the top bar.

#### Evaluation (the reference)

- 3 score cards: cpWER, WER, DER. Each card shows the value of the selected version, the best value of the file, and the change from the previous version. The DER card also shows missed, false alarm and confusion.
- Under the cards: a compact table with 1 row per version: time, label, cpWER, WER, DER, speakers ("5 of 5"), speed. This keeps the numbers of today without the 12-column table in a narrow column.
- No word diff.

#### Speakers (the reference)

2 tables side by side:

- Reference speakers: ID (as in the reference, for example `S1`), name field, speech time (the sum of the turn times, or "–" without times). "Rename in reference" changes the speaker of every turn with that ID and saves the reference (`PUT /v1beta/files/<id>/reference`).
- The selected version: label (`spk_1`), auto match (from `mapping` of the score), name field, ▶ (play the first turn of that speaker). "Use the matches" fills each empty name from the match. "Apply to all versions" saves the same names on every version where the match of the label is the same reference speaker. "Save" saves the names of the selected version (`PUT .../versions/<id>/names`).

### All files view

The setup table of today, at full width in the work area: Setup, Files, Versions, cpWER, WER, DER. Lower is better. It shows only when at least 1 file has a reference. Without one, it shows "Add a reference to a file to get scores."

## URL

`#/<tab>/<file>` or `#/<tab>@<platform>/<file>` today. New: the same, plus `/<row>/<view>`, where `<row>` is a version ID or `ref`, and `<view>` is `transcript`, `edit`, `evaluation` or `speakers`. `#/<tab>/all` opens the All files view. An old URL without `<row>` selects the newest version. A reload keeps the view.

## Narrow screens

Below 1000 px the 3 columns stack: files, then history, then the work area. The files column then shows only the selected file and a "Change file" button. Phone use is kept, not improved.

## Approaches

1. 3-column workbench with tabs (picked). The history stays visible, so a click on a version changes the work area at once. The reference as a pinned history row makes "1 per file" visible.
2. A sidebar and 1 long page with section links. Simple, but a 16-minute meeting needs a lot of scrolling, and the reference still looks like a part of the selected version.
3. A sidebar and tabs, with the version picker as a drop-down in the file header. The widest work area, but you do not see the scores of all versions at once.

## Behaviour details (agent calls, from the builder check)

1. Select and tick. A click on a card selects it: it becomes the "working version". A tick only adds a version to the compare set. The working version stays when the reference row is selected. Edit (left pane), Evaluation (the cards) and Speakers (the right table) all use the working version. The Transcript tab shows the working version, and a second ticked version next to it. The URL for the reference row is `.../ref/<view>?v=<version>`, so a reload keeps the working version. Default: the newest version.
2. Player. ▶ on a turn plays that turn only and stops at its end, as today (`stopAt`). The play button of the sticky player plays on from the current position to the end of the file. The highlight follows the audio time in each transcript that shows.
3. "Apply to all versions" fills only empty names. It never overwrites a name that the user set. A confirm box first says how many versions change. The UI fetches each full version to read its names before the save.
4. Upload. A drop or a click in the drop zone uploads the file and starts a run at once, as today. The run uses the current values of the "New run" box (default: auto language, speakers on, no label).
5. "Rename in reference" changes only the reference. The scores then show the new name in `mapping`. Names that are already saved on versions do not change. "Use the matches" fills the current reference name (for example "Alice" after a rename, or `S1` before).
6. "Scroll together" is close, not exact. The editor stays a `<textarea>`. When the top visible line of 1 pane has a start time, the other pane scrolls to the turn nearest that time. Without times in the reference, the 2 panes scroll on their own.

## How it is built (agent calls)

- React and plain CSS, as today. No new dependency.
- `Stt.tsx` is about 540 lines. Split it into `ui/src/panels/stt/`: `index.tsx` (state, data loading, URL), `Files.tsx`, `History.tsx`, `Transcript.tsx`, `ReferenceEdit.tsx`, `Evaluation.tsx`, `Speakers.tsx`, `AllFiles.tsx`, `Player.tsx`, and `lib.ts` for the pure functions. `panels/index.ts` keeps the same export.
- The pure functions that exist (`groupTurns`, `parseReference`, `formatReference`, `draftFromVersion`, `refTime`, `clock`, `namesBody`, `mappingNames`, `setupShort`) move to `lib.ts` without a change. Their tests in `ui/src/lib.test.ts` keep passing.
- New pure functions with unit tests: Speechmatics JSON to reference, reference speaker rename, speech time per reference speaker, "apply to all versions" (which versions get which names), the score chip colour.
- No change to the STT API or the mock routes. All the data comes from the routes of today. The mock server (`ui/mock-server.mjs`) gets no change, unless a test needs a second file.
- The `.panel` grid of the other tabs (TTS, LLM) does not change. The STT tab gets its own grid class.
- Update the `stt` row and the link format in the `model-ui` skill (`.claude/skills/model-ui/SKILL.md`, it names `Stt.tsx`), and the STT part of `docs/README.md` if it describes the old layout. Run `verify-ui` to prove the 3 states in a browser.

## Non-goals

- No change to the STT API, the scoring code or the reference format.
- No word diff between versions or against the reference.
- No delete of a file, a version or a reference (the API has no route for it).
- No file length in the cards (the API does not return it).
- No change to the TTS and LLM tabs.

## Anti-goals

- The tab must stay usable without a reference. A file without a reference must not show empty score columns, "–" cells or an empty Evaluation tab.
- The reference must not look like a part of 1 version.

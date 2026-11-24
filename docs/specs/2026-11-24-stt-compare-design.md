# Design: STT compare page (2 transcripts side by side, word and speaker mismatches)

Date: 2026-11-24. Status: approved by the user in chat (2 rounds of mockups: `.superpowers/brainstorm/97313-1795505688/content/compare-v1.html`, `compare-v2.html`), then "implement".

## Intent

The reference editor (`docs/specs/2026-11-24-stt-ui-layout-design.md`) shows a version next to the reference text, but you cannot see where they differ, and the speaker mapping is not visible on the text. The user wants a separate full-width page that compares 2 transcripts of 1 file, shows exactly which words and which speakers do not match, plays each sentence on both sides, and lets the user name the speakers there.

## Decisions (by the user)

1. Layout: aligned rows side by side (diff style). 1 row per turn of the left side.
2. A shift at the start (extra or missed words) must not spoil the next rows.
3. Complex speaker problems must show clearly: merged speakers, split speakers, a speaker change in the wrong place, overlap, no speakers at all.
4. Speaker naming: a click on a speaker chip opens a small box with 3 audio samples, the match, the word shares and a name field.

## How it works

- Page: `#/<tab>[@<platform>]/<file>/compare?a=<ref|version id>&b=<version id>`. It hides the files and history columns. "← Back" returns to the workbench. Default: `a` = the reference (or the second newest version), `b` = the working version (or the newest). 2 drop-downs change `a` and `b`. A "Compare" button in the work-area header opens it when the file has 1 version and a reference, or 2 versions.
- Words: each side becomes a list of tokens (display text, normalized text, speaker, times). Normalization as `norm_words` of the scoring code (lowercase, no apostrophes, no punctuation). Tokens with an empty normal form are left out.
- Alignment: word edit distance over the whole file with a backtrace (ops: ok, wrong word, missed, extra). It finds its way back after a gap, so a shift stays in its own rows. Rows are never matched by position or by time.
- Rows: each left token belongs to its left turn. An extra right word belongs to the row of the previous left word. 4 or more extra words in a run get their own row "only in <right>" (left side empty).
- Speaker map: for each right speaker, the share of its aligned words (ok and wrong word) per left speaker. 1-to-1 match: greedy by the largest count. Problems: "merged" (2 or more left speakers with a share of 20 % or more), "split" (no 1-to-1 match, but 50 % or more of 1 left speaker), "no match". Missed words per left speaker. A click on a cell shows only the rows with that pair.
- Word marks: wrong word (amber), missed (red, struck through), extra (green), right word with the wrong speaker (red dashed). A chip gets a red frame when its words have the wrong speaker.
- Gutter: errors per row (words + speaker errors). Red when the row has speaker errors, amber for word errors only, ✓ for none.
- Error strip at the top (click jumps to the row), "only rows with errors", "previous error" and "next error".
- Play: each left row and each right speaker segment has ▶. The right side uses its word times. The left side uses the turn times of the reference, or the times of the aligned right words when the reference has no times. ▶ plays only that part (the 1-turn play of the Transcript tab).
- Speaker box: the 3 longest turns of that speaker as samples, the word shares, a "merged"/"split" badge, and a name field. Save: a reference speaker is renamed in the reference (`PUT .../reference`); a version label gets a name (`PUT .../versions/<id>/names`, the other names of that version stay).
- No speakers on one side: only words are compared. The speaker map and the speaker marks are hidden, and a note says so.

## Approaches

1. Aligned rows from a word alignment (picked): obvious marks, fast reading, resyncs after a gap.
2. Stacked REF/HYP lines (sclite style): exact, but long and narrow.
3. Speaker lanes on a time axis (MeetEval style): clear for speaker errors, hard to read as sentences.

## Agent calls

- All in the browser, in `ui/src/panels/stt/`: pure functions in `compare.ts` with vitest tests, the page in `Compare.tsx`. No change to the STT API or the mock server.
- shortcut: the alignment table is n × m bytes. It refuses files with more than 40 million word pairs (about 6,300 words per side, about 40 minutes of speech) with a note. Upgrade to a banded or Hirschberg alignment if longer files need it.
- A missed run inside a left turn stays in that row (marked red). A fully missed left turn shows an empty right side ("not in <right>").
- The 1-to-1 match is greedy, not Hungarian. With 2 to 8 speakers it gives the same match in the normal case.

## Non-goals

- No change to the scores (WER, cpWER, DER stay as the server computes them).
- No editing of the reference text on this page (use the Edit tab).
- No word-level times for the reference.

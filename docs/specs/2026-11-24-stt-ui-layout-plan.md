# STT tab layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 2-column STT tab with a 3-column workbench: files | history (pinned reference row, version cards) | work area (Transcript for a version; Edit, Evaluation, Speakers for the reference).

**Architecture:** Split `ui/src/panels/Stt.tsx` into `ui/src/panels/stt/` (1 component per part, pure functions in `lib.ts`). The state, the data loading and the URL stay in `stt/index.tsx`. No change to the STT API or the mock server. All new logic that is not React is a pure function with a vitest test.

**Tech Stack:** React 19, TypeScript, Vite, vitest, plain CSS (`ui/src/styles.css`). No new dependency.

**Spec:** `docs/specs/2026-11-24-stt-ui-layout-design.md`. Mockups: `.superpowers/brainstorm/19885-1795473984/content/final-v1.html` (states 1 to 3), `stt-layout.html` (parts 1, 3, 4, 5B, 6A).

## Global Constraints

- No new npm dependency. No change in `deployments/` or `ui/mock-server.mjs`.
- The TTS and LLM tabs do not change. The `.panel` grid (`3fr 2fr`) stays for them.
- The reference is optional. A file without a reference shows no score chip, no "–" score cell and no Evaluation or Speakers tab.
- The reference is 1 per file. It is the pinned first row of the history column.
- Score chip colour from cpWER: below 0.20 green (`ok`), 0.20 to 0.40 amber (`warn`), above 0.40 red (`bad`).
- URL: `#/<tab>[@<platform>]/<file>[/<row>[/<view>]][?v=<version>]`, `<row>` is a version ID or `ref`, `<view>` is `transcript`, `edit`, `evaluation` or `speakers`. `#/<tab>[@<platform>]/all` is the All files view. An old URL without `<row>` selects the newest version.
- "Apply to all versions" never overwrites a saved name. "Rename in reference" changes only the reference.
- UI copy and docs prose: Simplified Technical English (short sentences, active voice, no contractions).
- Checks for every task: `cd ui && npm test && npm run build` pass.

## Review Focus

1. A file with 0 versions (a run failed after the upload): the history shows the reference row and "New run" only; the work area says `No versions yet. Use "New run".` (Task 4 step, Task 5 test.)
2. A version without speakers (diarization off): `groupTurns` gives speaker `""`. The Speakers table says "This version has no speaker labels." and its buttons are disabled; `applyNames` returns `null`. (Task 2 test, Task 8.)
3. A reference without times: no DER value ("no times: no DER"), speech time "–", the panes scroll on their own (`nearestTurn` gets no starts). (Task 2 tests.)
4. A URL with an unknown version ID, or an old `#/<tab>/<file>` link: select the newest version; `ref` on a file without a reference opens Edit only. (Task 3 test, Task 4 step.)
5. A file change while version, score or reference fetches are in flight: a late answer for another file must not show (keep the `current` ref guard of today in every loader). (Task 4 step.)

---

## File Structure

| File | Responsibility |
|---|---|
| `ui/src/panels/stt/lib.ts` | Types (`FileRow`, `Summary`, `Version`, `Score`, `SetupRow`, `Reference`, `RefTurn`, `Names`, `WordInfo`, `Setup`) and pure functions (moved and new) |
| `ui/src/panels/stt/index.tsx` | `Stt` panel: state, loaders, URL sync, 3-column frame, upload, transcribe |
| `ui/src/panels/stt/Files.tsx` | Sidebar: All files row, drop zone, search, file cards |
| `ui/src/panels/stt/AllFiles.tsx` | Setup table at full width |
| `ui/src/panels/stt/History.tsx` | Reference row, New run box, running row, version cards |
| `ui/src/panels/stt/Player.tsx` | Sticky player bar (play, time, seek, speed, follow) |
| `ui/src/panels/stt/Transcript.tsx` | Turns of 1 version, names editor without reference, compare, Request details |
| `ui/src/panels/stt/ReferenceEdit.tsx` | Edit tab: top bar, version pane, editor pane, import, scroll sync |
| `ui/src/panels/stt/Evaluation.tsx` | Score cards and compact version table |
| `ui/src/panels/stt/Speakers.tsx` | Reference speakers table and version speakers table |
| `ui/src/config.ts` | `parseHash` gets `row`, `view`, `v`; new `sttHash` |
| `ui/src/styles.css` | `.stt-*` classes; `main:has(.stt)` wider |
| `ui/src/lib.test.ts` | Imports from `./panels/stt/lib`; new tests |

Delete `ui/src/panels/Stt.tsx` in Task 1. `ui/src/panels/index.ts` imports `Stt` from `./stt`.

---

### Task 1: Move the STT panel into `stt/` without a behaviour change

**Files:**
- Create: `ui/src/panels/stt/lib.ts`, `ui/src/panels/stt/index.tsx`
- Delete: `ui/src/panels/Stt.tsx`
- Modify: `ui/src/panels/index.ts:5`, `ui/src/lib.test.ts:6`

**Interfaces:**
- Produces: `lib.ts` exports the types above and `groupTurns`, `gatewayTimedOut`, `clock`, `speakerName`, `namesBody`, `refTime`, `parseReference`, `formatReference`, `draftFromVersion`, `speakerCount`, `pct`, `setupShort`, `mappingNames`, `words`, `when`, `vtime`, `mimeOf`, `LANGS`, `COLORS` (all with today's bodies; the private ones become exports). `index.tsx` default-exports `Stt({ model }: { model: ModelConfig })`.

- [ ] **Step 1:** Move the types, constants and pure functions of `Stt.tsx` (lines 12–104) to `lib.ts` with `export`. Move the rest to `index.tsx`, with imports from `./lib`, `../../api`, `../../components`, `../../config`. Delete `Stt.tsx`.
- [ ] **Step 2:** In `panels/index.ts`, `import Stt from "./stt";`. In `lib.test.ts` line 6, import from `"./panels/stt/lib"`.
- [ ] **Step 3:** Run `cd ui && npm test && npm run build`. Expected: all tests pass, build has no type error.
- [ ] **Step 4:** Commit: `refactor(ui): move the STT panel into panels/stt`.

---

### Task 2: New pure functions for the reference, the speakers and the scores

**Files:**
- Modify: `ui/src/panels/stt/lib.ts`
- Test: `ui/src/lib.test.ts` (new `describe` blocks)

**Interfaces:**
- Produces (all in `lib.ts`):
  - `refSeconds(value: string | number): number` — the TypeScript twin of `seconds()` in `stt_api/evaluation/reference.py`: `12.5`, `"12.5"`, `"12.5s"`, `"01:02.5"`, `"00:01:02.5"` → seconds; throws on other text.
  - `speechmaticsToReference(doc: unknown): Reference` — throws `Error("not a Speechmatics transcript")` when `doc.results` is not an array.
  - `importReference(text: string, language: string): Reference` — Speechmatics JSON (an object with `results`), else `parseReference(text, language)`.
  - `renameRefSpeaker(r: Reference, from: string, to: string): Reference`
  - `refSummary(r: Reference): { turns: number; speakers: string[]; timed: boolean }` (speakers in first-seen order; `timed` when every turn has `start` and `end`).
  - `speechTime(r: Reference): Record<string, number | null>` (seconds per speaker, times read with `refSeconds`; `null` for all when not `timed`).
  - `scoreTone(cpwer: number): "ok" | "warn" | "bad"`
  - `bestCpwer(rows: { file_id: string; cpwer: number }[]): Record<string, number>`
  - `applyNames(source: { names: Names; mapping: Record<string, string> }, target: { names: Names; mapping: Record<string, string> }): Names | null` — the full new names of `target`, or `null` when nothing changes.
  - `nearestTurn(starts: number[], t: number): number` — index of the last start `<= t` (0 when `t` is before the first; -1 for an empty list).
  - `previousScore(versions: Summary[], scores: Record<string, Score>, id: string): Score | undefined` — the score of the next older version that has a score.

- [ ] **Step 1: Write the failing tests**

```ts
describe("speechmaticsToReference", () => {
  const item = (content: string, speaker: string | undefined, start: number, end: number, type = "word") =>
    ({ type, start_time: start, end_time: end, ...(type === "punctuation" ? { attaches_to: "previous" } : {}), alternatives: [{ content, ...(speaker ? { speaker } : {}) }] });
  it("joins items of 1 speaker, attaches punctuation, keeps entity text", () => {
    const doc = { metadata: { transcription_config: { language: "en" } }, results: [
      item("It's", "S1", 0.4, 0.88), item("100%", "S1", 0.9, 1.2, "entity"), item(",", "S1", 1.2, 1.2, "punctuation"),
      item("Yeah", "S2", 2, 2.3), item(".", "S2", 2.3, 2.3, "punctuation"), item("Ok", "S1", 3, 3.5) ] };
    expect(speechmaticsToReference(doc)).toEqual({ language: "en", turns: [
      { speaker: "S1", start: 0.4, end: 1.2, text: "It's 100%," },
      { speaker: "S2", start: 2, end: 2.3, text: "Yeah." },
      { speaker: "S1", start: 3, end: 3.5, text: "Ok" } ] });
  });
  it("uses 'unknown' for an item without a speaker and rejects other JSON", () => {
    expect(speechmaticsToReference({ results: [item("a", undefined, 0, 1)] }).turns[0].speaker).toBe("unknown");
    expect(() => speechmaticsToReference({ turns: [] })).toThrow("not a Speechmatics transcript");
  });
});

describe("importReference", () => {
  it("detects Speechmatics JSON, else uses parseReference", () => {
    expect(importReference(JSON.stringify({ results: [] }), "en")).toEqual({ language: "en", turns: [] }); // no language in the file: keep the field value
    expect(importReference("Alice: Hi", "en")).toEqual({ language: "en", turns: [{ speaker: "Alice", text: "Hi" }] });
  });
});

describe("refSeconds", () => {
  it("reads the time forms of the reference", () => {
    expect([12.5, "12.5", "12.5s", "01:02.5", "00:01:02.5"].map(refSeconds)).toEqual([12.5, 12.5, 12.5, 62.5, 62.5]);
    expect(() => refSeconds("abc")).toThrow();
  });
});

describe("reference speakers", () => {
  const r = { language: "en", turns: [{ speaker: "S1", text: "a", start: 0, end: 2 }, { speaker: "S2", text: "b", start: 2, end: 3.5 }, { speaker: "S1", text: "c", start: 4, end: 5 }] };
  it("renames every turn of 1 speaker", () => {
    expect(renameRefSpeaker(r, "S1", "Alice").turns.map((t) => t.speaker)).toEqual(["Alice", "S2", "Alice"]);
  });
  it("summarizes and sums speech time; null without times", () => {
    expect(refSummary(r)).toEqual({ turns: 3, speakers: ["S1", "S2"], timed: true });
    expect(speechTime(r)).toEqual({ S1: 3, S2: 1.5 });
    const untimed = { language: "", turns: [{ speaker: "A", text: "x" }] };
    expect(refSummary(untimed).timed).toBe(false);
    expect(speechTime(untimed)).toEqual({ A: null });
  });
});

describe("scores", () => {
  it("colours cpWER", () => {
    expect([0.19, 0.2, 0.4, 0.41].map(scoreTone)).toEqual(["ok", "warn", "warn", "bad"]);
  });
  it("finds the best cpWER per file", () => {
    expect(bestCpwer([{ file_id: "a", cpwer: 0.3 }, { file_id: "a", cpwer: 0.18 }, { file_id: "b", cpwer: 0.5 }])).toEqual({ a: 0.18, b: 0.5 });
  });
});

describe("applyNames", () => {
  const source = { names: { spk_1: "Alice", spk_2: "Bob" }, mapping: { spk_1: "S1", spk_2: "S2" } };
  it("fills empty names of labels that map to the same reference speaker", () => {
    expect(applyNames(source, { names: {}, mapping: { spk_1: "S2", spk_2: "S1", spk_3: "S5" } })).toEqual({ spk_1: "Bob", spk_2: "Alice" });
  });
  it("never overwrites a saved name, and returns null when nothing changes", () => {
    expect(applyNames(source, { names: { spk_1: "Carol" }, mapping: { spk_1: "S1", spk_2: "S2" } })).toEqual({ spk_1: "Carol", spk_2: "Bob" });
    expect(applyNames(source, { names: { spk_1: "Alice" }, mapping: { spk_1: "S1" } })).toBeNull();
    expect(applyNames(source, { names: {}, mapping: { "": "S1" } })).toBeNull(); // no speaker labels (diarization off)
  });
});

describe("nearestTurn", () => {
  it("finds the last turn that starts at or before t", () => {
    expect(nearestTurn([0, 5, 10], 7)).toBe(1);
    expect(nearestTurn([2, 5], 1)).toBe(0);
    expect(nearestTurn([], 3)).toBe(-1);
  });
});
```

Add a `previousScore` test: versions `[v3, v2, v1]` (newest first), scores for `v3` and `v1` only → `previousScore(..., "v3")` is the score of `v1`; for `"v1"` it is `undefined`.

- [ ] **Step 2:** Run `cd ui && npx vitest run src/lib.test.ts`. Expected: FAIL, the new functions are not exported.
- [ ] **Step 3:** Implement the functions in `lib.ts`. `speechmaticsToReference`: language from `metadata.transcription_config.language` (else `""`; `importReference` then uses its `language` argument); for each item take `alternatives[0]`; same speaker as the last turn → append (`attaches_to === "previous"` without a space), `end = max(end, end_time)`; else a new turn. `applyNames`: build `refName` = reference speaker → source name for labels with a non-empty source name; for each target label matching `/^spk_\d{1,2}$/` with an empty name and `refName[mapping[label]]`, set it.
- [ ] **Step 4:** Run `cd ui && npm test`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ui): STT reference import, speaker and score helpers`.

---

### Task 3: URL with row, view and working version

**Files:**
- Modify: `ui/src/config.ts:66-72`
- Test: `ui/src/lib.test.ts` (`describe("parseHash")`)

**Interfaces:**
- Produces: `parseHash(hash: string): { tab: string; platform?: string; file?: string; row?: string; view?: string; v?: string }` and `sttHash(tab: string, platform: string | undefined, file?: string, row?: string, view?: string, v?: string): string`. `file` may be `"all"`.

- [ ] **Step 1: Write the failing tests**

```ts
it("reads the row, the view and the working version", () => {
  expect(parseHash("#/stt-mock/f1/ref/edit?v=20261124T101200")).toEqual({ tab: "stt-mock", file: "f1", row: "ref", view: "edit", v: "20261124T101200" });
  expect(parseHash("#/stt-mock@runpod/f1/20261124T101200")).toEqual({ tab: "stt-mock", platform: "runpod", file: "f1", row: "20261124T101200" });
  expect(parseHash("#/stt-mock/all")).toEqual({ tab: "stt-mock", file: "all" });
});
it("builds an STT hash and leaves out empty parts", () => {
  expect(sttHash("stt-mock", undefined, "f1", "ref", "speakers", "v9")).toBe("#/stt-mock/f1/ref/speakers?v=v9");
  expect(sttHash("stt-mock", "runpod", "f1")).toBe("#/stt-mock@runpod/f1");
});
```

The 2 existing `parseHash` tests must keep passing unchanged.

- [ ] **Step 2:** Run `cd ui && npx vitest run src/lib.test.ts -t parseHash`. Expected: FAIL.
- [ ] **Step 3:** Split off `?v=` first, then the path parts. Encode each part with `encodeURIComponent` in `sttHash`.
- [ ] **Step 4:** Run `cd ui && npm test`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ui): STT hash with row, view and version`.

---

### Task 4: Frame, files sidebar and All files view

**Files:**
- Create: `ui/src/panels/stt/Files.tsx`, `ui/src/panels/stt/AllFiles.tsx`
- Modify: `ui/src/panels/stt/index.tsx`, `ui/src/styles.css`

**Interfaces:**
- Consumes: `bestCpwer`, `sttHash`, `parseHash` (Tasks 2, 3).
- Produces:
  - `Files({ files, selected, best, busy, onOpen, onAll, onUpload, onRefresh }: { files: FileRow[]; selected?: string; best: Record<string, number>; busy: boolean; onOpen: (id: string) => void; onAll: () => void; onUpload: (f: File) => void; onRefresh: () => void })`
  - `AllFiles({ setups }: { setups: SetupRow[] })`
  - In `index.tsx`: state `row` (`"ref"` or a version ID), `view`, `working` (version ID); `go(patch)` writes the hash with `history.replaceState` for view changes and `location.hash` for file changes. CSS classes `.stt` (grid `minmax(200px,20%) minmax(240px,23%) 1fr`), `.stt-files`, `.stt-history`, `.stt-work`, `.stt-card`, `.stt-card.selected`, `.chip`, `.chip.ok|warn|bad`, `.stt-drop`.

- [ ] **Step 1:** In `styles.css`, add `main:has(.stt) { max-width: none; }` and the `.stt*` classes. Below 1000 px, `.stt` is 1 column; `.stt-files` shows only the selected card and a "Change file" button (state in `Files`).
- [ ] **Step 2:** `Files`: "📊 All files: scores" row, drop zone (`<label>` that wraps a hidden `<input type="file" accept="audio/*,.m4a,.webm">` and handles `onDrop`/`onDragOver`), a search `<input>` that filters by name (case-insensitive), 1 card per file: name, `x.x MB · n versions · date`, badge `✓ reference` or `no reference`, and `best x.x %` when `best[id]` exists. Refresh in the header.
- [ ] **Step 3:** `AllFiles`: the setup table of today (`Setup, Files, Versions, cpWER, WER, DER`, "Lower is better"). With no rows: `Add a reference to a file to get scores.`
- [ ] **Step 4:** `index.tsx`: render `<section className="stt">` with Files | History placeholder | work area. Load `GET /v1beta/scores` once and keep `rows` and `setups`. On `file === "all"` hide the history column and show `AllFiles`. Read `row`, `view`, `v` from the hash: an unknown or missing `row` selects the newest version (no versions → `ref`); `ref` without a reference forces `view = "edit"`. Keep the `current` guard in every loader. With 0 versions and a version row, the work area says `No versions yet. Use "New run".`
- [ ] **Step 5:** Run `cd ui && npm test && npm run build`. Expected: PASS.
- [ ] **Step 6:** Commit: `feat(ui): STT 3-column frame, file cards, All files view`.

---

### Task 5: History column

**Files:**
- Create: `ui/src/panels/stt/History.tsx`
- Modify: `ui/src/panels/stt/index.tsx`

**Interfaces:**
- Consumes: `refSummary`, `scoreTone`, `setupShort`, `vtime`, `pct` (Tasks 1, 2).
- Produces: `History({ versions, scores, reference, row, ticked, run, onSelect, onTick, onRun, onStop }: { versions: Summary[]; scores: Record<string, Score>; reference?: Reference; row: string; ticked: string[]; run: { busy: string; startedAt?: number; error?: string }; onSelect: (row: string) => void; onTick: (id: string) => void; onRun: (o: { lang: string; diarize: boolean; label: string }) => void; onStop: () => void })`. The New run values live in `index.tsx` (state `newRun`), because the upload uses them too.

- [ ] **Step 1:** Reference row first. With a reference: `📌 Reference` and `{turns} turns · {speakers.length} speakers · times ✓` or `· no times: no DER`. Without: dashed `📌 ＋ Add reference (optional: gives scores)`. Click → `onSelect("ref")`.
- [ ] **Step 2:** "＋ New run" box (closed by default): Language select (`auto` + `LANGS`), Speakers checkbox, Label input (max 200), `Transcribe`. While `run.busy`: a row `running… m:ss` (a 1 s interval from `startedAt`) with `Stop`. `run.error` shows in that row until the next run.
- [ ] **Step 3:** 1 card per version, newest first: tick box (`aria-label="Compare {vtime}"`), time, chip `cpWER x.x %` with `scoreTone` only when `scores[id]` exists; line 2 `label || "no label"` · `setupShort` · `n spk` · `run_seconds s`. Card click → `onSelect(id)`; the tick does not select.
- [ ] **Step 4:** In `index.tsx`, the upload uses `newRun` for the transcribe body (as today: upload, open the file, transcribe). After a run, select the new version.
- [ ] **Step 5:** Run `cd ui && npm test && npm run build`. Expected: PASS.
- [ ] **Step 6:** Commit: `feat(ui): STT history column with reference row and version cards`.

---

### Task 6: Player and Transcript tab

**Files:**
- Create: `ui/src/panels/stt/Player.tsx`, `ui/src/panels/stt/Transcript.tsx`
- Modify: `ui/src/panels/stt/index.tsx`

**Interfaces:**
- Consumes: `groupTurns`, `clock`, `speakerName`, `namesBody`, `COLORS`, `nearestTurn`.
- Produces:
  - `Player({ audio, time, duration, playing, rate, follow, onToggle, onSeek, onRate, onFollow }: { audio: RefObject<HTMLAudioElement | null>; time: number; duration: number; playing: boolean; rate: number; follow: boolean; onToggle: () => void; onSeek: (t: number) => void; onRate: (r: number) => void; onFollow: (f: boolean) => void })` — rates `[1, 1.25, 1.5, 2]`.
  - `Transcript({ v, time, playingTurn, follow, editNames, onPlayTurn, onSeek, onNames }: { v: Version; time: number; playingTurn?: number; follow: boolean; editNames: boolean; onPlayTurn: (turn: number, start: number, end: number) => void; onSeek: (t: number) => void; onNames: (n: Names) => Promise<void> })`
  - In `index.tsx`: `ensureAudio(): Promise<void>` (today's signed-URL logic, refetch after 10 minutes); `playTurn` sets `stopAt` (today's behaviour); the player button plays with `stopAt = Infinity`. State `time` from `timeupdate` plus the frame loop of today.

- [ ] **Step 1:** `Player` is `position: sticky; top: 0` inside `.stt-work`: ▶/❚❚, `mm:ss / mm:ss`, `<input type="range">` for seek, rate `<select>`, `follow` checkbox.
- [ ] **Step 2:** `Transcript`: version line (time · image · label); when `editNames` (no reference), the name fields and `Save names` of today; else a link `Rename speakers` that goes to `ref/speakers`. Turns as grid rows `▶ | start (button, seeks) | name + text`. The turn with `nearestTurn(starts, time)` while audio plays gets `.playing`; with `follow` it calls `scrollIntoView({ block: "nearest" })`.
- [ ] **Step 3:** In `index.tsx`, the Transcript tab shows the working version, and a second ticked version next to it (`.compare`). Under it a closed `<details>` "Request details" with `Timings` and `Curl`. Errors and the busy line move under the file header.
- [ ] **Step 4:** Run `cd ui && npm test && npm run build`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ui): STT sticky player and reading view`.

---

### Task 7: Reference Edit tab

**Files:**
- Create: `ui/src/panels/stt/ReferenceEdit.tsx`
- Modify: `ui/src/panels/stt/index.tsx`

**Interfaces:**
- Consumes: `importReference`, `refSummary`, `draftFromVersion`, `parseReference`, `formatReference`, `nearestTurn`, `groupTurns`.
- Produces: `ReferenceEdit({ text, language, saved, version, onText, onLanguage, onSave, onDraft }: { text: string; language: string; saved?: Reference; version?: Version; onText: (t: string) => void; onLanguage: (l: string) => void; onSave: () => void; onDraft: () => void })`. `index.tsx` keeps `saveReference` and `draftReference` of today; `draftReference` uses the working version (not the first ticked one).

- [ ] **Step 1:** Top bar: chip `✓ saved` or `not saved`, summary from `refSummary(saved)`, Language input, `Draft from version`, `Import…` (file input, `.txt,.json,text/plain,application/json`), `Save` (disabled for empty text). Import: read the text; JSON with `results` → `formatReference(importReference(text, language))` into the editor; other text → the editor as is. An import error shows in the error bar.
- [ ] **Step 2:** 2 panes: left the working version (read only, name + start + text per turn, or `Select a version to see it here.`), right the `<textarea>` with the help line of today.
- [ ] **Step 3:** Scroll sync: on scroll of 1 pane, find the start time of its top visible turn (left: `data-start` on each row; right: the line at `scrollTop / lineHeight`, parsed with the `[start - end]` prefix), then scroll the other pane to `nearestTurn`. Skip it when the reference text has no times. A flag stops the echo scroll.
- [ ] **Step 4:** Run `cd ui && npm test && npm run build`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(ui): STT reference editor next to the working version`.

---

### Task 8: Evaluation and Speakers tabs

**Files:**
- Create: `ui/src/panels/stt/Evaluation.tsx`, `ui/src/panels/stt/Speakers.tsx`
- Modify: `ui/src/panels/stt/index.tsx`

**Interfaces:**
- Consumes: `previousScore`, `pct`, `vtime`, `refSummary`, `speechTime`, `renameRefSpeaker`, `applyNames`, `mappingNames`, `groupTurns`, `COLORS`.
- Produces:
  - `Evaluation({ versions, scores, working }: { versions: Summary[]; scores: Record<string, Score>; working?: string })`
  - `Speakers({ reference, version, score, onRenameRef, onSaveNames, onApplyAll, onPlayFirst }: { reference: Reference; version?: Version; score?: Score; onRenameRef: (from: string, to: string) => Promise<void>; onSaveNames: (n: Names) => Promise<void>; onApplyAll: (source: { names: Names; mapping: Record<string, string> }) => Promise<number>; onPlayFirst: (label: string) => void })`
  - In `index.tsx`: `renameRef` (PUT the renamed reference, reload scores), `applyAll` (fetch each other full version, `applyNames`, `confirm("Save names on N versions?")`, PUT each non-null, return N).

- [ ] **Step 1:** `Evaluation`: 3 cards. cpWER and WER: value of the working version, `best x.x %` over the file, `was x.x %` from `previousScore`. DER: value, `missed · false alarm · confusion`, or `no times: no DER`. Under the cards: table `Version, Label, cpWER, WER, DER, Speakers (h of r), Speed`, working row highlighted.
- [ ] **Step 2:** `Speakers`, left table: ID, name `<input>` (default = ID), speech time (`m:ss` or `–`). `Rename in reference` calls `onRenameRef` for each changed row, then reloads. Right table (working version): label, match (`score.mapping[label]` or chip `no match`), name `<input>`, ▶. Buttons `Use the matches` (fills empty inputs with the current reference name), `Apply to all versions`, `Save`. With no `spk_` labels: `This version has no speaker labels.` and the 3 buttons disabled.
- [ ] **Step 3:** Run `cd ui && npm test && npm run build`. Expected: PASS.
- [ ] **Step 4:** Commit: `feat(ui): STT evaluation cards and file speaker table`.

---

### Task 9: Docs and browser proof

**Files:**
- Modify: `.claude/skills/verify-ui/features/stt-transcribe.md`, `.claude/skills/model-ui/SKILL.md` (the `stt` row at line 60 and the link format at line 48), `docs/README.md` (STT part, when it names the old layout)

- [ ] **Step 1:** Update `stt-transcribe.md`: new field names (drop zone, `New run`, `Transcribe`, `Compare <time>` tick boxes, reference row, tabs), the new URL form, and the 3 states of `final-v1.html` as checks.
- [ ] **Step 2:** Update the `model-ui` skill: panel folder `panels/stt/`, link `#/<tab>[@<platform>]/<file id>[/<row>[/<view>]]`.
- [ ] **Step 3:** Run `./scripts/verify-ui.py up`, then drive the STT tab with the Paseo browser: upload, 2 runs, State 1 (no reference: no chips, Transcript only), Draft from version + Save, State 2 (chips, best badge), State 3 (Edit, Evaluation, Speakers), a Speechmatics import (a 3-item file in `<run_dir>`), a reload on `.../ref/speakers?v=...`. Save screenshots in `<run_dir>/evidence/`. Run `./scripts/verify-ui.py down`.
- [ ] **Step 4:** Run `cd ui && npm test && npm run build`. Expected: PASS.
- [ ] **Step 5:** Commit: `docs(ui): STT layout in the verify-ui feature and model-ui skill`.

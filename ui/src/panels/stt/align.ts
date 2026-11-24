// The compare page logic (spec: docs/specs/2026-11-24-stt-compare-design.md). No React. Tested in ui/src/compare.test.ts (file name: align.ts, because Compare.tsx exists and macOS ignores case).
import { refSeconds, type Reference, type WordInfo } from "./lib";

export interface Tok { text: string; norm: string; speaker: string; turn: number; start?: number; end?: number }
export interface Side { turns: { speaker: string; start?: number; end?: number }[]; toks: Tok[] }
export type Op = "ok" | "sub" | "del" | "ins";
export interface Cell { text: string; op: Op; wrongSpk?: boolean }
export interface Seg { speaker: string; start?: number; end?: number; cells: Cell[] }
export interface Row { kind: "pair" | "onlyB"; left?: Seg; right: Seg[]; words: number; speakers: number; pairs: string[] }
export interface SpeakerMap {
  counts: Record<string, Record<string, number>>; // right speaker -> left speaker -> aligned words (ok and wrong word)
  words: Record<string, number>; // right speaker -> all its words
  match: Record<string, string>; // right speaker -> left speaker (1 to 1)
  problem: Record<string, "merged" | "split" | "no match">;
  missed: Record<string, number>; // left speaker -> missed words
  hasSpeakers: boolean;
}

const MAX_CELLS = 40_000_000; // shortcut: the backtrace table is n x m bytes; use a banded alignment for longer files
const ONLY_RUN = 4; // this many extra words in a run get their own row
const MERGED_SHARE = 0.2;
const SPLIT_SHARE = 0.5;

/** 1 word as norm_words() of the scoring code: lowercase, no apostrophes, no punctuation. */
export const normWord = (w: string) => w.toLowerCase().replace(/['’]/g, "").replace(/[^\p{L}\p{N}_]+/gu, "");

export function refSide(r: Reference): Side {
  const toks: Tok[] = [];
  const turns = r.turns.map((t, i) => {
    const start = t.start === undefined ? undefined : refSeconds(t.start);
    const end = t.end === undefined ? undefined : refSeconds(t.end);
    for (const text of t.text.split(/\s+/)) if (normWord(text)) toks.push({ text, norm: normWord(text), speaker: t.speaker, turn: i });
    return { speaker: t.speaker, start, end };
  });
  return { turns, toks };
}

export function versionSide(words: WordInfo[]): Side {
  const turns: Side["turns"] = [];
  const toks: Tok[] = [];
  for (const x of words) {
    const speaker = x.speaker ?? "";
    const [start, end] = [parseFloat(x.start_offset), parseFloat(x.end_offset)];
    const last = turns.at(-1);
    if (last && last.speaker === speaker) last.end = end;
    else turns.push({ speaker, start, end });
    if (normWord(x.text)) toks.push({ text: x.text, norm: normWord(x.text), speaker, turn: turns.length - 1, start, end });
  }
  return { turns, toks };
}

/** Word edit distance with a backtrace. Ties prefer the diagonal, then a missed word, then an extra word. */
export function align(a: string[], b: string[]): { op: Op; a?: number; b?: number }[] {
  const n = a.length, m = b.length, W = m + 1;
  if ((n + 1) * W > MAX_CELLS) throw new Error(`too long to compare: ${n} x ${m} words`);
  const dir = new Uint8Array((n + 1) * W); // 1 diagonal, 2 missed (up), 3 extra (left)
  let prev = new Uint32Array(W), cur = new Uint32Array(W);
  for (let j = 0; j <= m; j++) (prev[j] = j), (dir[j] = 3);
  for (let i = 1; i <= n; i++) {
    cur[0] = i;
    dir[i * W] = 2;
    for (let j = 1; j <= m; j++) {
      const diag = prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1), up = prev[j] + 1, left = cur[j - 1] + 1;
      if (diag <= up && diag <= left) (cur[j] = diag), (dir[i * W + j] = 1);
      else if (up <= left) (cur[j] = up), (dir[i * W + j] = 2);
      else (cur[j] = left), (dir[i * W + j] = 3);
    }
    [prev, cur] = [cur, prev];
  }
  const out: { op: Op; a?: number; b?: number }[] = [];
  for (let i = n, j = m; i > 0 || j > 0; ) {
    const d = dir[i * W + j];
    if (i > 0 && j > 0 && d === 1) out.push({ op: a[i - 1] === b[j - 1] ? "ok" : "sub", a: --i, b: --j });
    else if (i > 0 && (d === 2 || j === 0)) out.push({ op: "del", a: --i });
    else out.push({ op: "ins", b: --j });
  }
  return out.reverse();
}

function speakerMap(A: Side, B: Side, ops: ReturnType<typeof align>): SpeakerMap {
  const hasSpeakers = A.toks.some((t) => t.speaker) && B.toks.some((t) => t.speaker);
  const counts: SpeakerMap["counts"] = {}, words: SpeakerMap["words"] = {}, missed: SpeakerMap["missed"] = {};
  for (const t of B.toks) words[t.speaker] = (words[t.speaker] ?? 0) + 1;
  for (const o of ops) {
    if (o.op === "del") missed[A.toks[o.a!].speaker] = (missed[A.toks[o.a!].speaker] ?? 0) + 1;
    if (o.op !== "ok" && o.op !== "sub") continue;
    const [bs, as] = [B.toks[o.b!].speaker, A.toks[o.a!].speaker];
    (counts[bs] ??= {})[as] = (counts[bs][as] ?? 0) + 1;
  }
  // shortcut: a greedy 1-to-1 match by the largest count, not Hungarian; the same result for 2 to 8 clear speakers
  const match: Record<string, string> = {}, taken = new Set<string>();
  const pairs = Object.entries(counts).flatMap(([bs, row]) => Object.entries(row).map(([as, c]) => [bs, as, c] as const));
  for (const [bs, as] of pairs.sort((x, y) => y[2] - x[2])) if (bs && as && !match[bs] && !taken.has(as)) (match[bs] = as), taken.add(as);
  const problem: SpeakerMap["problem"] = {};
  if (hasSpeakers)
    for (const bs of Object.keys(words).filter(Boolean)) {
      const row = counts[bs] ?? {};
      const total = Object.values(row).reduce((s, c) => s + c, 0);
      const shares = Object.values(row).map((c) => c / (total || 1));
      if (shares.filter((s) => s >= MERGED_SHARE).length >= 2) problem[bs] = "merged";
      else if (!match[bs]) problem[bs] = Math.max(0, ...shares) >= SPLIT_SHARE ? "split" : "no match";
    }
  return { counts, words, match, problem, missed, hasSpeakers };
}

/** 2 sides -> rows (1 per left turn, plus "only in B" rows for long extra runs) and the speaker map. */
export function compare(A: Side, B: Side): { rows: Row[]; map: SpeakerMap } {
  const ops = align(A.toks.map((t) => t.norm), B.toks.map((t) => t.norm));
  const map = speakerMap(A, B, ops);
  const rows: Row[] = [];
  let cur: Row | undefined;
  let curTurn = -1;
  let lead: Seg[] = []; // extra words before the first left word
  const addRight = (row: { right: Seg[] }, t: Tok, cell: Cell) => {
    const last = row.right.at(-1);
    if (last && last.speaker === t.speaker) (last.cells.push(cell), t.end !== undefined && (last.end = t.end));
    else row.right.push({ speaker: t.speaker, start: t.start, end: t.end, cells: [cell] });
  };
  for (let i = 0; i < ops.length; i++) {
    const o = ops[i];
    if (o.op === "ins") {
      let r = 0;
      while (ops[i + r]?.op === "ins") r++;
      if (r >= ONLY_RUN) {
        const row: Row = { kind: "onlyB", right: [], words: r, speakers: 0, pairs: [] };
        for (const x of ops.slice(i, i + r)) addRight(row, B.toks[x.b!], { text: B.toks[x.b!].text, op: "ins" });
        rows.push(row);
        i += r - 1;
        continue;
      }
      const t = B.toks[o.b!];
      if (cur) (addRight(cur, t, { text: t.text, op: "ins" }), cur.words++);
      else addRight({ right: lead }, t, { text: t.text, op: "ins" });
      continue;
    }
    const at = A.toks[o.a!];
    // A new left turn, or the rest of a turn after an "only in B" row (keeps the reading order).
    if (!cur || curTurn !== at.turn || rows.at(-1) !== cur) {
      const turn = A.turns[at.turn];
      const cont = curTurn === at.turn; // continued turn: its times come from its right words
      cur = { kind: "pair", left: { speaker: turn.speaker, start: cont ? undefined : turn.start, end: cont ? undefined : turn.end, cells: [] }, right: [], words: 0, speakers: 0, pairs: [] };
      if (lead.length) (cur.right.push(...lead), (cur.words += lead.reduce((s, g) => s + g.cells.length, 0)), (lead = []));
      curTurn = at.turn;
      rows.push(cur);
    }
    const row = cur;
    row.left!.cells.push({ text: at.text, op: o.op });
    if (o.op !== "ok") row.words++;
    if (o.op === "del") continue;
    const bt = B.toks[o.b!];
    const wrongSpk = map.hasSpeakers && !!bt.speaker && map.match[bt.speaker] !== at.speaker;
    if (wrongSpk) row.speakers++;
    const pair = `${bt.speaker}|${at.speaker}`;
    if (!row.pairs.includes(pair)) row.pairs.push(pair);
    addRight(row, bt, { text: bt.text, op: o.op, ...(wrongSpk ? { wrongSpk } : {}) });
  }
  if (lead.length) rows.unshift({ kind: "onlyB", right: lead, words: lead.reduce((s, g) => s + g.cells.length, 0), speakers: 0, pairs: [] });
  for (const r of rows) {
    if (!r.left || r.left.start !== undefined) continue;
    const ts = r.right.flatMap((s) => [s.start, s.end]).filter((x): x is number => x !== undefined);
    if (ts.length) (r.left.start = Math.min(...ts)), (r.left.end = Math.max(...ts));
  }
  return { rows, map };
}

/** The n longest parts of 1 speaker that have times: the samples of the speaker box. */
export function samples<T extends { speaker: string; start?: number; end?: number }>(segs: T[], speaker: string, n = 3): T[] {
  return segs
    .filter((s) => s.speaker === speaker && s.start !== undefined && s.end !== undefined)
    .sort((x, y) => y.end! - y.start! - (x.end! - x.start!))
    .slice(0, n);
}

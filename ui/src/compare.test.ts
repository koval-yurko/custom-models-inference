import { describe, expect, it } from "vitest";
import { align, compare, normWord, refSide, samples, versionSide } from "./panels/stt/align";

const w = (text: string, speaker: string | undefined, s: number, e = s + 0.4) => ({ type: "word_info", text, speaker, start_offset: `${s}s`, end_offset: `${e}s` });
const words = (speaker: string | undefined, text: string, t0: number) => text.split(" ").map((x, i) => w(x, speaker, t0 + i * 0.5));
const ref = (...turns: [string, string, number?, number?][]) => ({ language: "en", turns: turns.map(([speaker, text, start, end]) => ({ speaker, text, ...(start !== undefined ? { start, end } : {}) })) });

describe("normWord", () => {
  it("matches norm_words of the scoring code", () => {
    expect(["Don't", "Bob!", "100%", "—", "It’s"].map(normWord)).toEqual(["dont", "bob", "100", "", "its"]);
  });
});

describe("align", () => {
  it("marks ok, wrong, missed and extra words", () => {
    expect(align(["a", "b", "c"], ["a", "x", "c"]).map((o) => o.op)).toEqual(["ok", "sub", "ok"]);
    expect(align(["a", "b", "c"], ["a", "c"]).map((o) => o.op)).toEqual(["ok", "del", "ok"]);
    expect(align(["a", "c"], ["a", "b", "c"]).map((o) => o.op)).toEqual(["ok", "ins", "ok"]);
  });
  it("finds its way back after a shift at the start", () => {
    const ops = align(["x", "y", "z", "w"], ["p", "q", "r", "s", "t", "x", "y", "z", "w"]);
    expect(ops.map((o) => o.op).join(" ")).toBe("ins ins ins ins ins ok ok ok ok");
  });
  it("refuses a table that is too big", () => {
    expect(() => align(new Array(7000).fill("a"), new Array(7000).fill("a"))).toThrow("too long");
  });
});

describe("compare", () => {
  it("puts 4 or more extra words at the start in their own row and keeps the next rows clean", () => {
    const a = refSide(ref(["Alice", "it is only god", 0, 3], ["Bob", "yeah i get it", 3, 6]));
    const b = versionSide([...words("spk_9", "can you hear me okay", 0), ...words("spk_1", "it is only god", 3), ...words("spk_2", "yeah i get it", 6)]);
    const { rows } = compare(a, b);
    expect(rows.map((r) => r.kind)).toEqual(["onlyB", "pair", "pair"]);
    expect(rows[0].right[0].cells.map((c) => c.op)).toEqual(["ins", "ins", "ins", "ins", "ins"]);
    expect(rows.slice(1).map((r) => r.words + r.speakers)).toEqual([0, 0]);
  });

  it("continues a left turn in a new row after a long extra run in its middle, so the order stays right", () => {
    const a = refSide(ref(["Alice", "one two three four", 0, 4]));
    const b = versionSide(words("spk_1", "one two x y z w three four", 0));
    const { rows } = compare(a, b);
    expect(rows.map((r) => r.kind)).toEqual(["pair", "onlyB", "pair"]);
    expect(rows.map((r) => r.left?.cells.map((c) => c.text).join(" ") ?? "")).toEqual(["one two", "", "three four"]);
    expect(rows[2].right[0].cells.map((c) => c.text)).toEqual(["three", "four"]);
  });
  it("keeps fewer than 4 extra words in the row of the previous left word", () => {
    const a = refSide(ref(["Alice", "one two three", 0, 2]));
    const b = versionSide(words("spk_1", "one two really three", 0));
    const { rows } = compare(a, b);
    expect(rows).toHaveLength(1);
    expect(rows[0].right[0].cells.map((c) => c.op)).toEqual(["ok", "ok", "ins", "ok"]);
    expect(rows[0].words).toBe(1);
  });

  it("finds merged speakers and marks the words of the lost speaker", () => {
    const a = refSide(ref(["Alice", "a b c d", 0, 2], ["Bob", "e f g h m", 2, 4], ["Carol", "i j k l", 4, 6]));
    const b = versionSide([...words("spk_1", "a b c d", 0), ...words("spk_2", "e f g h m i j k l", 2)]);
    const { rows, map } = compare(a, b);
    expect(map.match).toEqual({ spk_1: "Alice", spk_2: "Bob" });
    expect(map.problem.spk_2).toBe("merged");
    expect(map.counts.spk_2).toEqual({ Bob: 5, Carol: 4 });
    const carol = rows[2];
    expect(carol.right[0].cells.every((c) => c.wrongSpk)).toBe(true);
    expect(carol.speakers).toBe(4);
    expect(carol.pairs).toContain("spk_2|Carol");
  });

  it("finds a split speaker and starts a new segment at the speaker change", () => {
    const a = refSide(ref(["Alice", "a b c d e f g h", 0, 4]));
    const b = versionSide([...words("spk_4", "a b", 0), ...words("spk_1", "c d e f g h", 1)]);
    const { rows, map } = compare(a, b);
    expect(map.match).toEqual({ spk_1: "Alice" });
    expect(map.problem.spk_4).toBe("split");
    expect(rows[0].right.map((s) => s.speaker)).toEqual(["spk_4", "spk_1"]);
    expect(rows[0].speakers).toBe(2);
  });

  it("counts missed words per left speaker and shows a fully missed turn with an empty right side", () => {
    const a = refSide(ref(["Alice", "hello there", 0, 1], ["Bob", "yes", 1, 2]));
    const b = versionSide(words("spk_1", "hello there", 0));
    const { rows, map } = compare(a, b);
    expect(map.missed).toEqual({ Bob: 1 });
    expect(rows[1].right).toEqual([]);
    expect(rows[1].left?.cells[0].op).toBe("del");
  });

  it("compares only words when a side has no speakers", () => {
    const a = refSide(ref(["Alice", "a b", 0, 1], ["Bob", "c d", 1, 2]));
    const b = versionSide(words(undefined, "a b c d", 0));
    const { rows, map } = compare(a, b);
    expect(map.hasSpeakers).toBe(false);
    expect(rows.every((r) => r.speakers === 0 && r.right.every((s) => s.cells.every((c) => !c.wrongSpk)))).toBe(true);
  });

  it("gives a reference turn without times the times of its aligned words", () => {
    const a = refSide(ref(["Alice", "one two"]));
    const b = versionSide([w("one", "spk_1", 5, 5.4), w("two", "spk_1", 5.5, 6)]);
    const { rows } = compare(a, b);
    expect([rows[0].left?.start, rows[0].left?.end]).toEqual([5, 6]);
  });
});

describe("samples", () => {
  it("picks the 3 longest parts of 1 speaker that have times", () => {
    const segs = [
      { speaker: "A", start: 0, end: 1 },
      { speaker: "A", start: 2, end: 6 },
      { speaker: "B", start: 6, end: 20 },
      { speaker: "A", start: 7, end: 9 },
      { speaker: "A", start: 10, end: 10.5 },
      { speaker: "A" },
    ];
    expect(samples(segs, "A")).toEqual([segs[1], segs[3], segs[0]]);
  });
});

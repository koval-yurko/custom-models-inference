import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { call } from "./api";
import { pcm16ToFloat32, wavFromPcm } from "./audio";
import { parseHash, parseModels } from "./config";
import { parseSchema } from "./panels/LlmRoutes";
import { clock, draftFromVersion, formatReference, gatewayTimedOut, groupTurns, namesBody, parseReference, refTime, speakerCount, speakerName } from "./panels/Stt";
import { voiceIds } from "./panels/Tts";
import { parseSse, readSse } from "./sse";

describe("parseSse", () => {
  it("keeps an unfinished event for the next chunk", () => {
    expect(parseSse('data: {"a":1}\n\ndata: {"b"')).toEqual({ events: ['{"a":1}'], rest: 'data: {"b"' });
  });
  it("handles CRLF, comments and multi-line data", () => {
    expect(parseSse(": ping\r\n\r\ndata: x\r\ndata: y\r\n\r\n").events).toEqual(["x\ny"]);
  });
});

describe("readSse", () => {
  it("joins events split across chunks and stops at [DONE]", async () => {
    const parts = ['data: {"n":', '1}\n\nda', 'ta: {"n":2}\n\ndata: [DONE]\n\n', 'data: {"n":3}\n\n'];
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        parts.forEach((p) => c.enqueue(new TextEncoder().encode(p)));
        c.close();
      },
    });
    const out: string[] = [];
    for await (const e of readSse(body)) out.push(e);
    expect(out).toEqual(['{"n":1}', '{"n":2}']);
  });
});

describe("audio", () => {
  it("converts 16-bit LE PCM to floats", () => {
    expect(Array.from(pcm16ToFloat32(new Uint8Array([0x00, 0x80, 0xff, 0x7f, 0, 0])))).toEqual([-1, 32767 / 32768, 0]);
  });
  it("writes a valid WAV header", async () => {
    const wav = wavFromPcm([new Uint8Array(4), new Uint8Array(6)], 24000);
    const v = new DataView(await wav.arrayBuffer());
    expect(wav.size).toBe(54);
    expect(v.getUint32(4, true)).toBe(46); // RIFF size
    expect(v.getUint32(24, true)).toBe(24000);
    expect(v.getUint32(40, true)).toBe(10); // data size
  });
});

describe("parseModels", () => {
  const ok = { id: "a", title: "A", type: "tts", base_url: "https://x.dev/", model: "m" };
  it("trims the trailing slash and defaults features", () => {
    expect(parseModels({ models: [ok] })[0]).toMatchObject({ base_url: "https://x.dev", features: {} });
  });
  it("rejects a missing field and a non-https URL", () => {
    expect(() => parseModels({ models: [{ ...ok, id: "" }] })).toThrow(/models\[0\]\.id/);
    expect(() => parseModels({ models: [{ ...ok, base_url: "http://x" }] })).toThrow(/https/);
    expect(() => parseModels({})).toThrow();
  });
});

describe("voiceIds", () => {
  it("accepts Kokoro voice objects and plain strings", () => {
    expect(voiceIds([{ id: "af_alloy", name: "af_alloy" }, "am_adam", { name: "x" }, 5])).toEqual(["af_alloy", "am_adam", "x"]);
    expect(voiceIds(undefined)).toEqual([]);
  });
});

describe("call (Vertex 429 retry)", () => {
  const model = { base_url: "https://gw", features: { cold_start: "vertex-429" } } as never;
  beforeEach(() => vi.stubGlobal("localStorage", { getItem: () => "k" })); // the Node test environment has none
  afterEach(() => (vi.unstubAllGlobals(), vi.useRealTimers()));

  it("does not retry a network error", async () => {
    const f = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", f);
    const onRetry = vi.fn();
    await expect(call(model, "/x", {}, onRetry)).rejects.toThrow(/failed/);
    expect(f).toHaveBeenCalledTimes(1);
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("retries a real 429 after 30 s and returns the next answer", async () => {
    vi.useFakeTimers();
    const f = vi.fn().mockResolvedValueOnce(new Response("", { status: 429 })).mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", f);
    const onRetry = vi.fn();
    const p = call(model, "/x", {}, onRetry);
    await vi.advanceTimersByTimeAsync(30_000);
    expect((await p).status).toBe(200);
    expect(onRetry).toHaveBeenCalledWith(1);
  });
});

describe("parseSchema", () => {
  it("treats empty text as the app.py default schema", () => {
    expect(parseSchema("  ")).toEqual({});
  });
  it("parses a JSON object", () => {
    expect(parseSchema('{"type":"object"}')).toEqual({ schema: { type: "object" } });
  });
  it("rejects invalid JSON and non-objects", () => {
    expect(parseSchema("{bad").error).toMatch(/not valid JSON/);
    expect(parseSchema("[1]").error).toMatch(/JSON object/);
    expect(parseSchema("null").error).toMatch(/JSON object/);
  });
});

describe("groupTurns", () => {
  const w = (text: string, speaker: string | undefined, start: string, end = start) => ({ type: "word_info", text, speaker, start_offset: start, end_offset: end });
  it("joins words of 1 speaker in a row and starts a new group at a speaker change", () => {
    expect(groupTurns([w("Hello", "spk_1", "0.100s", "0.300s"), w("there.", "spk_1", "0.400s", "0.800s"), w("Hi.", "spk_2", "1.000s", "1.200s"), w("Bye.", "spk_1", "2.000s", "2.500s")])).toEqual([
      { speaker: "spk_1", text: "Hello there.", start: "0.100s", end: "0.800s" },
      { speaker: "spk_2", text: "Hi.", start: "1.000s", end: "1.200s" },
      { speaker: "spk_1", text: "Bye.", start: "2.000s", end: "2.500s" },
    ]);
  });
  it("gives 1 group without a speaker when diarization is off, and none for no words", () => {
    expect(groupTurns([w("a", undefined, "0.000s"), w("b", undefined, "0.500s", "0.900s")])).toEqual([{ speaker: "", text: "a b", start: "0.000s", end: "0.900s" }]);
    expect(groupTurns([])).toEqual([]);
  });
});

describe("parseHash", () => {
  it("splits the tab and the file id", () => {
    expect(parseHash("#/stt-mock/0b8e3f6a-1c2d-4e5f-8a9b-0c1d2e3f4a5b")).toEqual({ tab: "stt-mock", file: "0b8e3f6a-1c2d-4e5f-8a9b-0c1d2e3f4a5b" });
    expect(parseHash("#/tts-mock")).toEqual({ tab: "tts-mock" });
    expect(parseHash("")).toEqual({ tab: "" });
    expect(parseHash("#/a%20b")).toEqual({ tab: "a b" });
  });
});

describe("speakerCount", () => {
  const w = (speaker?: string) => ({ type: "word_info", text: "x", speaker, start_offset: "0s", end_offset: "0s" });
  it("counts distinct speakers", () => {
    expect(speakerCount([w("spk_1"), w("spk_2"), w("spk_1")])).toBe(2);
    expect(speakerCount([w(), w()])).toBe(0);
  });
});

describe("gatewayTimedOut", () => {
  it("is a 504, or a blocked answer (no status) after about 300 s", () => {
    expect(gatewayTimedOut(504, 1000)).toBe(true);
    expect(gatewayTimedOut(undefined, 295_000)).toBe(true);
    expect(gatewayTimedOut(undefined, 5_000)).toBe(false);
    expect(gatewayTimedOut(200, 400_000)).toBe(false);
  });
});

describe("clock", () => {
  it("turns a Gemini offset into hh:mm:ss", () => {
    expect(clock("8.958s")).toBe("00:00:08");
    expect(clock("0.031s")).toBe("00:00:00");
    expect(clock("125.5s")).toBe("00:02:05");
    expect(clock("3725s")).toBe("01:02:05");
  });
});

describe("speaker names", () => {
  it("shows the given name, else the label, else text", () => {
    expect(speakerName({ spk_1: "Alice" }, "spk_1")).toBe("Alice");
    expect(speakerName({ spk_1: "Alice" }, "spk_2")).toBe("spk_2");
    expect(speakerName(undefined, "")).toBe("text");
  });
  it("trims the draft and drops empty names", () => {
    expect(namesBody({ spk_1: " Alice ", spk_2: "  " })).toEqual({ spk_1: "Alice" });
  });
});

describe("reference text", () => {
  it("reads 'Name: text' lines, with optional times, and skips empty lines", () => {
    expect(parseReference("[00:00:00.0 - 00:00:04.9] Alice: Hello: there.\n\n Bob:  Hi. \n", "en")).toEqual({
      language: "en",
      turns: [
        { speaker: "Alice", text: "Hello: there.", start: "00:00:00.0", end: "00:00:04.9" },
        { speaker: "Bob", text: "Hi." },
      ],
    });
  });
  it("takes JSON as it is and names the bad line", () => {
    expect(parseReference('{"language":"de","turns":[{"speaker":"A","text":"x"}]}', "en")).toEqual({ language: "de", turns: [{ speaker: "A", text: "x" }] });
    expect(() => parseReference("Alice: ok\nno speaker here", "")).toThrow("Line 2");
  });
  it("formats back to the same lines", () => {
    const text = "[00:00:00.0 - 00:00:04.9] Alice: Hello.\nBob: Hi.";
    expect(formatReference(parseReference(text, ""))).toBe(text);
  });
  it("writes times as hh:mm:ss.s", () => {
    expect([refTime(0), refTime(8.958), refTime(69), refTime(3725.04)]).toEqual(["00:00:00.0", "00:00:09.0", "00:01:09.0", "01:02:05.0"]);
  });
  it("drafts a reference from a version with the given names", () => {
    const w = (text: string, speaker: string | undefined, start: string, end: string) => ({ type: "word_info", text, speaker, start_offset: start, end_offset: end });
    const draft = draftFromVersion([w("Hello", "spk_1", "0.100s", "0.300s"), w("there.", "spk_1", "0.400s", "4.900s"), w("Hi.", "spk_2", "5.040s", "6.000s")], "", { spk_1: "Alice" });
    expect(draft).toBe("[00:00:00.1 - 00:00:04.9] Alice: Hello there.\n[00:00:05.0 - 00:00:06.0] spk_2: Hi.");
    expect(parseReference(draft, "").turns).toHaveLength(2);
    expect(draftFromVersion([], "Hello\nthere.", undefined)).toBe("Speaker: Hello there.");
  });
});

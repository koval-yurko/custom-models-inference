import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { call, retriesOn429, retryPlan, waitText } from "./api";
import { pcm16ToFloat32, wavFromPcm } from "./audio";
import { choosePlatform, hashPick, parseHash, parseModels, parseStatus, platformLabel, sttHash, withPlatform } from "./config";
import { parseSchema } from "./panels/LlmRoutes";
import {
  bestCpwer, hasUnsavedEdits, insertTurn, mergeTurns, resolveView, clock, draftFromVersion, formatReference, gatewayTimedOut, groupTurns, importReference, namesBody, nearestTurn, parseReference, previousScore, refSeconds,
  refSummary, refTime, renameRefSpeaker, scoreTone, speakerCount, speakerName, speechTime, speechmaticsToReference, type Score, type Summary,
} from "./panels/stt/lib";
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
    expect(onRetry).toHaveBeenCalledWith(1, "429");
  });

  it("retries a real 429 for cold_start retry-429 (Vertex AI, Runpod)", async () => {
    vi.useFakeTimers();
    const f = vi.fn().mockResolvedValueOnce(new Response("", { status: 429 })).mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", f);
    const onRetry = vi.fn();
    const p = call({ base_url: "https://gw", features: { cold_start: "retry-429" } } as never, "/x", {}, onRetry);
    await vi.advanceTimersByTimeAsync(30_000);
    expect((await p).status).toBe(200);
    expect(onRetry).toHaveBeenCalledWith(1, "429");
  });

  it("returns a 429 at once for cold_start hold (the platform keeps the request open)", async () => {
    const f = vi.fn().mockResolvedValue(new Response("", { status: 429 }));
    vi.stubGlobal("fetch", f);
    const onRetry = vi.fn();
    expect((await call({ base_url: "https://gw", features: { cold_start: "hold" } } as never, "/x", {}, onRetry)).status).toBe(429);
    expect(f).toHaveBeenCalledTimes(1);
    expect(onRetry).not.toHaveBeenCalled();
  });
});

describe("call (gateway timeout retry, opt-in)", () => {
  const hold = { base_url: "https://gw", features: { cold_start: "hold" } } as never;
  beforeEach(() => vi.stubGlobal("localStorage", { getItem: () => "k" }));
  afterEach(() => (vi.unstubAllGlobals(), vi.useRealTimers()));

  it("retries a network error that comes after 30 s (the gateway 504 has no CORS) and returns the next answer", async () => {
    vi.useFakeTimers();
    const f = vi.fn()
      .mockImplementationOnce(() => new Promise((_, rej) => setTimeout(() => rej(new TypeError("Failed to fetch")), 300_000)))
      .mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", f);
    const onRetry = vi.fn();
    const p = call(hold, "/x", {}, onRetry, { retryTimeouts: true });
    await vi.advanceTimersByTimeAsync(302_000);
    expect((await p).status).toBe(200);
    expect(onRetry).toHaveBeenCalledWith(1, "timeout");
  });

  it("retries a 504 after a long wait", async () => {
    vi.useFakeTimers();
    const f = vi.fn()
      .mockImplementationOnce(() => new Promise((res) => setTimeout(() => res(new Response("", { status: 504 })), 60_000)))
      .mockResolvedValueOnce(new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", f);
    const p = call(hold, "/x", {}, undefined, { retryTimeouts: true });
    await vi.advanceTimersByTimeAsync(63_000);
    expect((await p).status).toBe(200);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("does not retry a fast network error (a wrong key)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(call(hold, "/x", {}, undefined, { retryTimeouts: true })).rejects.toThrow(/API key/);
  });

  it("does not retry a timeout without the option (STT: a second POST would start a second run)", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise((_, rej) => setTimeout(() => rej(new TypeError("x")), 300_000))));
    const p = call(hold, "/x", {});
    const done = expect(p).rejects.toThrow(/failed/);
    await vi.advanceTimersByTimeAsync(300_000);
    await done;
  });
});

describe("retryPlan", () => {
  it("429 retries in 30 s for retry-429 only", () => {
    expect(retryPlan(429, 0, "retry-429", false)).toEqual({ reason: "429", waitMs: 30_000 });
    expect(retryPlan(429, 0, "hold", true)).toBeNull();
  });
  it("a timeout retries in 2 s on a cold-start platform after 30 s, when the panel allows it", () => {
    expect(retryPlan(undefined, 31_000, "hold", true)).toEqual({ reason: "timeout", waitMs: 2_000 });
    expect(retryPlan(504, 31_000, "retry-429", true)).toEqual({ reason: "timeout", waitMs: 2_000 });
    expect(retryPlan(502, 31_000, "hold", true)?.reason).toBe("timeout");
    expect(retryPlan(undefined, 5_000, "hold", true)).toBeNull();
    expect(retryPlan(undefined, 31_000, "hold", false)).toBeNull();
    expect(retryPlan(undefined, 31_000, undefined, true)).toBeNull(); // TTS on Cloud Run: no cold-start rule
    expect(retryPlan(500, 31_000, "hold", true)).toBeNull();
  });
});

describe("waitText", () => {
  it("says nothing for a fast answer", () => {
    expect(waitText({ elapsedMs: 2_000, coldStart: "hold", label: "Runpod" })).toBeNull();
  });
  it("shows the time, then the cold start hint", () => {
    expect(waitText({ elapsedMs: 5_000, coldStart: "hold", label: "Runpod" })).toBe("Waiting for Runpod… 0:05. Press Stop to cancel.");
    expect(waitText({ elapsedMs: 75_000, coldStart: "hold", label: "Runpod" })).toBe(
      "Waiting for Runpod… 1:15. Probably a cold start: a replica starts, this takes about 3 to 10 minutes. Press Stop to cancel.",
    );
  });
  it("names the retry reason and the attempt", () => {
    expect(waitText({ elapsedMs: 40_000, coldStart: "retry-429", label: "Runpod", attempt: 2, reason: "429" })).toBe(
      "Waiting for Runpod… 0:40. The model is starting (HTTP 429): retry 2, every 30 s. Press Stop to cancel.",
    );
    expect(waitText({ elapsedMs: 310_000, coldStart: "hold", attempt: 1, reason: "timeout" })).toBe(
      "Waiting for the model… 5:10. The gateway stopped after its time limit, but the replica is still starting: attempt 2. Press Stop to cancel.",
    );
  });
});

describe("retriesOn429", () => {
  it("retries for retry-429 and the old vertex-429 only", () => {
    expect([retriesOn429("retry-429"), retriesOn429("vertex-429"), retriesOn429("hold"), retriesOn429(undefined)]).toEqual([true, true, false, false]);
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
  it("reads the row, the view and the working version", () => {
    expect(parseHash("#/stt-mock/f1/ref/edit?v=20261124T101200")).toEqual({ tab: "stt-mock", file: "f1", row: "ref", view: "edit", v: "20261124T101200" });
    expect(parseHash("#/stt-mock@runpod/f1/20261124T101200")).toEqual({ tab: "stt-mock", platform: "runpod", file: "f1", row: "20261124T101200" });
    expect(parseHash("#/stt-mock/all")).toEqual({ tab: "stt-mock", file: "all" });
  });
  it("reads and builds the compare link", () => {
    expect(parseHash("#/stt-mock/f1/compare?a=ref&b=v2")).toEqual({ tab: "stt-mock", file: "f1", row: "compare", a: "ref", b: "v2" });
    expect(sttHash("stt-mock", undefined, "f1", "compare", undefined, undefined, { a: "ref", b: "v2" })).toBe("#/stt-mock/f1/compare?a=ref&b=v2");
  });
  it("builds an STT hash and leaves out empty parts", () => {
    expect(sttHash("stt-mock", undefined, "f1", "ref", "speakers", "v9")).toBe("#/stt-mock/f1/ref/speakers?v=v9");
    expect(sttHash("stt-mock", "runpod", "f1")).toBe("#/stt-mock@runpod/f1");
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

describe("parseModels platforms", () => {
  const p = (id: string, base_url = `https://gw/${id}/`) => ({ id, label: id.toUpperCase(), base_url, cold_start: "retry-429" });
  const ok = { id: "a", title: "A", type: "llm", base_url: "https://gw/vertex", model: "m" };
  it("keeps the platforms in order and trims each base_url", () => {
    const m = parseModels({ models: [{ ...ok, platforms: [p("vertex"), p("runpod")] }] })[0];
    expect(m.platforms?.map((x) => [x.id, x.base_url])).toEqual([["vertex", "https://gw/vertex"], ["runpod", "https://gw/runpod"]]);
  });
  it("rejects an empty list, a duplicate id and an http URL", () => {
    expect(() => parseModels({ models: [{ ...ok, platforms: [] }] })).toThrow(/models\[0\]\.platforms/);
    expect(() => parseModels({ models: [{ ...ok, platforms: [p("vertex"), p("vertex")] }] })).toThrow(/duplicate/);
    expect(() => parseModels({ models: [{ ...ok, platforms: [p("vertex", "http://x")] }] })).toThrow(/platforms\[0\]\.base_url/);
    expect(() => parseModels({ models: [{ ...ok, platforms: [{ id: "vertex", base_url: "https://gw" }] }] })).toThrow(/platforms\[0\]\.label/);
  });
  it("accepts an entry without platforms (old models.json)", () => {
    expect(parseModels({ models: [ok] })[0].platforms).toBeUndefined();
  });
});

describe("parseHash platform", () => {
  it("reads @<platform> and keeps the STT file link", () => {
    expect(parseHash("#/llm-a@runpod")).toEqual({ tab: "llm-a", platform: "runpod" });
    expect(parseHash("#/stt@vertex/f1")).toEqual({ tab: "stt", platform: "vertex", file: "f1" });
    expect(parseHash("#/stt/f1")).toEqual({ tab: "stt", file: "f1" });
    expect(parseHash("#/a@")).toEqual({ tab: "a" });
  });
});

describe("choosePlatform and withPlatform", () => {
  const V = { id: "vertex", label: "Vertex AI", base_url: "https://gw/vertex", cold_start: "retry-429" };
  const R = { id: "runpod", label: "Runpod", base_url: "https://gw/runpod", cold_start: "retry-429" };
  const m = { id: "a", title: "A", type: "llm", base_url: V.base_url, model: "x", features: { stream: true }, platforms: [V, R] };
  it("hash wins, then the stored choice, then the first platform", () => {
    expect(choosePlatform(m, "runpod", "vertex")).toBe(R);
    expect(choosePlatform(m, "modal", "runpod")).toBe(R); // unknown hash id: not deployed
    expect(choosePlatform(m, undefined, "runpod")).toBe(R); // STT file link without @platform
    expect(choosePlatform(m, undefined, "gone")).toBe(V);
    expect(choosePlatform({ ...m, platforms: undefined })).toBeUndefined();
  });
  it("gives the panel the base_url and cold_start of the platform, and keeps the rest", () => {
    expect(withPlatform(m, R)).toMatchObject({ id: "a", base_url: R.base_url, features: { stream: true, cold_start: "retry-429" } });
    const old = { ...m, platforms: undefined, features: { cold_start: "vertex-429" } };
    expect(withPlatform(old, undefined)).toBe(old);
  });
});

describe("hashPick", () => {
  const V = { id: "vertex", label: "Vertex AI", base_url: "https://gw/vertex" };
  const R = { id: "runpod", label: "Runpod", base_url: "https://gw/runpod" };
  const models = [{ id: "a", title: "A", type: "llm", base_url: V.base_url, model: "x", features: {}, platforms: [V, R] }];
  it("saves a platform that comes from a link, so the tab link keeps it", () => {
    expect(hashPick(models, parseHash("#/a@runpod"))).toEqual({ model: "a", platform: "runpod" });
  });
  it("ignores a link without a platform, an unknown platform and an unknown tab", () => {
    expect(hashPick(models, parseHash("#/a"))).toBeUndefined();
    expect(hashPick(models, parseHash("#/a@modal"))).toBeUndefined();
    expect(hashPick(models, parseHash("#/b@runpod"))).toBeUndefined();
  });
});

describe("speechmaticsToReference", () => {
  const item = (content: string, speaker: string | undefined, start: number, end: number, type = "word") => ({
    type,
    start_time: start,
    end_time: end,
    ...(type === "punctuation" ? { attaches_to: "previous" } : {}),
    alternatives: [{ content, ...(speaker ? { speaker } : {}) }],
  });
  it("joins items of 1 speaker, attaches punctuation, keeps entity text", () => {
    const doc = {
      metadata: { transcription_config: { language: "en" } },
      results: [item("It's", "S1", 0.4, 0.88), item("100%", "S1", 0.9, 1.2, "entity"), item(",", "S1", 1.2, 1.2, "punctuation"), item("Yeah", "S2", 2, 2.3), item(".", "S2", 2.3, 2.3, "punctuation"), item("Ok", "S1", 3, 3.5)],
    };
    expect(speechmaticsToReference(doc)).toEqual({
      language: "en",
      turns: [
        { speaker: "S1", start: 0.4, end: 1.2, text: "It's 100%," },
        { speaker: "S2", start: 2, end: 2.3, text: "Yeah." },
        { speaker: "S1", start: 3, end: 3.5, text: "Ok" },
      ],
    });
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
  it("finds the score of the next older version that has one", () => {
    const v = (id: string) => ({ id }) as Summary;
    const s = (cpwer: number) => ({ cpwer }) as Score;
    const scores = { v3: s(0.1), v1: s(0.3) };
    expect(previousScore([v("v3"), v("v2"), v("v1")], scores, "v3")).toBe(scores.v1);
    expect(previousScore([v("v3"), v("v2"), v("v1")], scores, "v1")).toBeUndefined();
  });
});

describe("nearestTurn", () => {
  it("finds the last turn that starts at or before t", () => {
    expect(nearestTurn([0, 5, 10], 7)).toBe(1);
    expect(nearestTurn([2, 5], 1)).toBe(0);
    expect(nearestTurn([], 3)).toBe(-1);
  });
});

describe("resolveView", () => {
  const vs = [{ id: "v2" }, { id: "v1" }];
  it("opens the reference Edit view when the file has no versions", () => {
    expect(resolveView([], {}, false)).toEqual({ row: "ref", working: undefined, view: "edit", noVersions: true });
  });
  it("selects the newest version for an old link or an unknown id", () => {
    expect(resolveView(vs, {}, true)).toEqual({ row: "v2", working: "v2", view: "transcript", noVersions: false });
    expect(resolveView(vs, { row: "gone" }, true).row).toBe("v2");
  });
  it("keeps the working version on the reference row; Edit only without a reference", () => {
    expect(resolveView(vs, { row: "ref", view: "speakers", v: "v1" }, true)).toEqual({ row: "ref", working: "v1", view: "speakers", noVersions: false });
    expect(resolveView(vs, { row: "ref", view: "speakers", v: "x" }, false)).toEqual({ row: "ref", working: "v2", view: "edit", noVersions: false });
  });
});

describe("resolveView, reference row", () => {
  const vs = [{ id: "v2" }, { id: "v1" }];
  it("opens Evaluation by default when the file has a reference, and the edit page only on request", () => {
    expect(resolveView(vs, { row: "ref" }, true).view).toBe("evaluation");
    expect(resolveView(vs, { row: "ref", view: "edit" }, true).view).toBe("edit");
    expect(resolveView(vs, { row: "ref", view: "transcript" }, true).view).toBe("evaluation");
  });
});

describe("turn editing", () => {
  const ts = [
    { speaker: "A", text: "one", start: "00:00:00.0", end: "00:00:01.0" },
    { speaker: "B", text: "two", start: "00:00:01.5", end: "00:00:02.0" },
    { speaker: "A", text: "three" },
  ];
  it("merges a turn with the next one: its speaker and start, the next end", () => {
    expect(mergeTurns(ts, 0)).toEqual([{ speaker: "A", text: "one two", start: "00:00:00.0", end: "00:00:02.0" }, ts[2]]);
    expect(mergeTurns(ts, 1)).toEqual([ts[0], { speaker: "B", text: "two three", start: "00:00:01.5", end: "00:00:02.0" }]);
    expect(mergeTurns(ts, 2)).toBe(ts); // the last turn has no next turn
  });
  it("inserts an empty turn of the same speaker after a turn, starting at its end", () => {
    expect(insertTurn(ts, 0)[1]).toEqual({ speaker: "A", text: "", start: "00:00:01.0", end: "00:00:01.0" });
    expect(insertTurn(ts, 2)[3]).toEqual({ speaker: "A", text: "" });
    expect(insertTurn([], -1)).toEqual([{ speaker: "Speaker 1", text: "" }]);
  });
});

describe("hasUnsavedEdits", () => {
  const saved = { language: "en", turns: [{ speaker: "A", text: "Hi" }] };
  it("is false when the editor shows the saved reference or is empty without one", () => {
    expect(hasUnsavedEdits("A: Hi", saved)).toBe(false);
    expect(hasUnsavedEdits("", undefined)).toBe(false);
  });
  it("is true for typed or imported text", () => {
    expect(hasUnsavedEdits("A: Hi there", saved)).toBe(true);
    expect(hasUnsavedEdits("B: new", undefined)).toBe(true);
  });
});

describe("parseStatus", () => {
  const row = { id: "a", title: "A", type: "llm", version: "img:1", tab: true, platforms: [{ id: "vertex", state: "off" }, { id: "runpod", state: "parked" }, { id: "modal", state: "serving" }] };
  it("reads the rows", () => {
    expect(parseStatus({ status: [row] })).toEqual([row]);
  });
  it("is empty for an old models.json without status", () => {
    expect(parseStatus({ models: [] })).toEqual([]);
  });
  it("defaults a missing version and tab", () => {
    expect(parseStatus({ status: [{ ...row, version: undefined, tab: undefined }] })[0]).toMatchObject({ version: "", tab: false });
  });
  it("rejects an unknown state", () => {
    expect(() => parseStatus({ status: [{ ...row, platforms: [{ id: "vertex", state: "up" }] }] })).toThrow(/state/);
  });
  it("labels the platforms", () => {
    expect([platformLabel("vertex"), platformLabel("cloudrun"), platformLabel("x")]).toEqual(["Vertex AI", "Cloud Run", "x"]);
  });
});

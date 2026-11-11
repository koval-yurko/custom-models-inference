import { describe, expect, it } from "vitest";
import { pcm16ToFloat32, wavFromPcm } from "./audio";
import { parseModels } from "./config";
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

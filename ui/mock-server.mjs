// Local stand-in for the model gateways (TTS, LLM, STT; every route also with a /vertex or /runpod prefix), for UI work without GCP: npm run mock (port 5181 or MOCK_PORT, key "test").
// It answers the CORS preflight like Kokoro and vLLM do. Extend it when you add a panel for a new type.
import http from "node:http";
import { execFileSync } from "node:child_process";
// Scores come from the real STT API service code (services/stt_api/stt_api/evaluation, standard library), so the mock
// and GCP give the same numbers.
const FILES_DIR = new URL("../deployments/stt-a-qwen3-asr-diar/services/stt_api/", import.meta.url).pathname;
function py(fn, ...args) { // fn(*args) from the evaluation package; a ValueError comes back as {error}
  const code = `import json, sys; sys.path.insert(0, ${JSON.stringify(FILES_DIR)})
from stt_api.evaluation import reference, scoring
fns = {"score": scoring.score, "summarize": scoring.summarize, "check_reference": reference.check_reference}
a = json.load(sys.stdin)
try: print(json.dumps({"ok": fns[a[0]](*a[1])}))
except ValueError as e: print(json.dumps({"error": str(e)}))`;
  return JSON.parse(execFileSync("python3", ["-c", code], { input: JSON.stringify([fn, args]) }));
}
const MOCK_SETUP = { asr: "mock-asr", aligner: "mock-aligner", diarization: "mock/diarization", image_tag: "mock" };
const files = new Map(); // STT-A mock store: id -> {meta..., audio, versions}
// A fixed 2-speaker answer in the speech engine shape (services/speech_engine/speech_engine/logic.py). run > 0 marks a saved version, so 2 versions differ.
function gemini(j, run = 0) {
  const diar = j.generation_config?.transcription_config?.mode?.diarization_mode === "speaker";
  const turns = [["spk_1", 0.1, `Hello there, this is the mock${run ? ` run ${run}` : ""}.`], ["spk_2", 2.5, `Hi! The input was ${j.input?.[0]?.type}.`], ["spk_1", 5.0, "Goodbye."]];
  const annotations = turns.flatMap(([spk, t0, text]) => text.split(" ").map((w, i) => ({ type: "word_info", text: w, ...(diar ? { speaker: spk } : {}), start_offset: `${(t0 + i * 0.4).toFixed(3)}s`, end_offset: `${(t0 + i * 0.4 + 0.35).toFixed(3)}s` })));
  const text = turns.map((x) => x[2]).join("\n");
  return { id: crypto.randomUUID(), status: "completed", model: "qwen3-asr-diar", output_text: text, audio_seconds: 6.5, setup: MOCK_SETUP, steps: [{ type: "model_output", content: [{ type: "text", text, annotations }] }] };
}
// Cold start of a platform (only with these env vars): the first chat call on /runpod waits MOCK_DROP_MS and
// then answers 504 without CORS headers (like the API Gateway time limit; the browser sees a network error), the next call waits MOCK_COLD_MS and answers.
const DROP_MS = Number(process.env.MOCK_DROP_MS ?? 0), COLD_MS = Number(process.env.MOCK_COLD_MS ?? 0);
const coldCalls = new Map(); // platform -> chat calls so far
const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*" };
http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") { res.writeHead(200, cors); return res.end(); }
  const rawUrl = req.url; // the log keeps the platform prefix: proof of the platform the UI called
  req.url = req.url.replace(/^\/(vertex|runpod)(?=\/)/, ""); // platform path prefix (gateway /<platform><route>): same answers
  if (req.method === "PUT" && req.url.startsWith("/mock-upload/")) { // the signed URL of /v1beta/uploads: no API key, like GCS
    const chunks = []; for await (const c of req) chunks.push(c);
    const n = chunks.reduce((s, c) => s + c.length, 0);
    const f = files.get(req.url.split("/")[2]); if (f) f.audio = Buffer.concat(chunks);
    console.log(new Date().toISOString(), req.method, req.url, `${n} bytes`, req.headers["content-type"]);
    res.writeHead(200, cors); return res.end();
  }
  if (req.method === "GET" && req.url.startsWith("/mock-audio/")) { // the signed GET URL of /v1beta/files/<id>/audio: no API key, like GCS
    const f = files.get(req.url.split("/")[2]);
    if (!f?.audio) { res.writeHead(404, cors); return res.end(); }
    const r = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? ""); // the <audio> element seeks with Range requests
    const a = f.audio, from = r?.[1] ? +r[1] : 0, to = r?.[2] ? Math.min(+r[2], a.length - 1) : a.length - 1;
    console.log(new Date().toISOString(), req.method, req.url, req.headers.range ?? "");
    res.writeHead(r ? 206 : 200, { ...cors, "Content-Type": f.mime_type, "Accept-Ranges": "bytes", "Content-Length": to - from + 1, ...(r ? { "Content-Range": `bytes ${from}-${to}/${a.length}` } : {}) });
    return res.end(a.subarray(from, to + 1));
  }
  if (req.headers["x-api-key"] !== "test") {
    console.log(new Date().toISOString(), req.method, rawUrl, "403 bad key");
    res.writeHead(403, cors); return res.end("bad key");
  }
  let body = ""; for await (const c of req) body += c; const j = body ? JSON.parse(body) : {};
  console.log(new Date().toISOString(), req.method, rawUrl, body.length > 2000 ? `${body.slice(0, 200)}… (${body.length} chars)` : body); // request log: proof that the UI call reached the mock
  if (req.url === "/v1/audio/voices") { // Kokoro shape
    res.writeHead(200, { ...cors, "Content-Type": "application/json" });
    return res.end(JSON.stringify({ voices: [{ id: "af_heart", name: "af_heart" }, { id: "am_adam", name: "am_adam" }] }));
  }
  if (req.url === "/v1/audio/speech") {
    res.writeHead(200, { ...cors, "Content-Type": "audio/pcm" });
    for (let k = 0; k < 5; k++) { // 5 x 0.5 s of 440 Hz at 24 kHz, odd-sized chunks
      const b = Buffer.alloc(24000); for (let i = 0; i < 12000; i++) b.writeInt16LE(Math.round(8000 * Math.sin((k * 12000 + i) * 2 * Math.PI * 440 / 24000)), i * 2);
      res.write(b.subarray(0, 11001)); res.write(b.subarray(11001)); await new Promise(r => setTimeout(r, 300));
    }
    return res.end();
  }
  if (req.url === "/v1/chat/completions") {
    const platform = rawUrl.match(/^\/(runpod)\//)?.[1];
    const n = platform ? (coldCalls.get(platform) ?? 0) : 9;
    if (platform) coldCalls.set(platform, n + 1);
    if (n === 0 && DROP_MS) { await new Promise(r => setTimeout(r, DROP_MS)); console.log(new Date().toISOString(), "mock cold start: 504 without CORS", rawUrl); res.writeHead(504); return res.end("upstream request timeout"); }
    if (n <= 1 && COLD_MS) { console.log(new Date().toISOString(), "mock cold start: hold", COLD_MS, "ms", rawUrl); await new Promise(r => setTimeout(r, COLD_MS)); }
    const words = `Echo: ${j.messages.at(-1).content}. The sea is wide and deep.`.split(" ");
    if (!j.stream) { res.writeHead(200, { ...cors, "Content-Type": "application/json" }); return res.end(JSON.stringify({ choices: [{ message: { content: words.join(" ") } }], usage: { completion_tokens: words.length } })); }
    res.writeHead(200, { ...cors, "Content-Type": "text/event-stream" });
    for (const w of words) { res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: w + " " } }] })}\n\n`); await new Promise(r => setTimeout(r, 80)); }
    res.write(`data: ${JSON.stringify({ choices: [], usage: { completion_tokens: words.length } })}\n\ndata: [DONE]\n\n`); return res.end();
  }
  if (req.url === "/extract") { // LLM-B app.py shape
    res.writeHead(200, { ...cors, "Content-Type": "application/json" });
    return res.end(JSON.stringify({ data: { people: ["Ada Lovelace", "Charles Babbage"], organizations: ["Royal Society"], places: ["London"], dates: ["5 June 1833"], schema_given: !!j.schema } }));
  }
  if (req.url === "/generate") {
    res.writeHead(200, { ...cors, "Content-Type": "application/json" });
    return res.end(JSON.stringify({ text: `Echo: ${j.prompt}` }));
  }
  const json = (code, obj) => (res.writeHead(code, { ...cors, "Content-Type": "application/json" }), res.end(JSON.stringify(obj)));
  if (req.url === "/v1beta/uploads") { // STT-A STT API service shape
    const id = crypto.randomUUID(), port = process.env.MOCK_PORT ?? 5181;
    files.set(id, { id, name: j.name, mime_type: j.mime_type, size_bytes: j.size_bytes, created: new Date().toISOString().slice(0, 19) + "Z", audio: false, versions: [] });
    return json(200, { id, upload_url: `http://localhost:${port}/mock-upload/${id}`, method: "PUT",
      headers: { "Content-Type": j.mime_type, "x-goog-content-length-range": `0,${j.size_bytes}` }, file_uri: `gs://mock-stt-audio/files/${id}/audio`, expires_in: 900 });
  }
  if (req.url === "/v1beta/interactions") return json(200, gemini(j)); // the direct route: nothing is saved
  if (req.url === "/v1beta/scores") { // all versions of all files with a reference, as scoring.all_scores
    const rows = [...files.values()].filter((f) => f.reference).flatMap((f) => f.versions.map((v) => ({ file_id: f.id, file_name: f.name, ...py("score", f.reference, v).ok })));
    return json(200, { rows, setups: py("summarize", rows).ok });
  }
  const m = req.url.match(/^\/v1beta\/files(?:\/([^/]+)(?:\/(transcribe|versions|audio|reference)(?:\/([^/]+)(\/names|\/score)?)?)?)?$/);
  if (m) { // STT-A STT API service: list, 1 file, 1 version, names, audio URL, transcribe again, delete (kept in memory)
    const [, id, op, vid, names] = m, f = files.get(id);
    if (!id) return json(200, { files: [...files.values()].filter((x) => x.audio).reverse().map(({ audio, versions, reference, ...x }) => ({ ...x, versions: versions.length, latest: versions.at(-1)?.id ?? null, reference: !!reference })) });
    if (!f || !f.audio) return json(404, { error: { code: 404, message: "file not found", status: "NOT_FOUND" } });
    if (req.method === "DELETE" && !op) return files.delete(id), json(200, { deleted: id });
    if (req.method === "DELETE" && op === "reference") return f.reference ? (delete f.reference, json(200, { deleted: "reference" })) : json(404, { error: { code: 404, message: "this file has no reference", status: "NOT_FOUND" } });
    if (req.method === "DELETE" && op === "versions" && vid && !names) {
      const n = f.versions.length;
      f.versions = f.versions.filter((x) => x.id !== vid);
      return n === f.versions.length ? json(404, { error: { code: 404, message: "version not found", status: "NOT_FOUND" } }) : json(200, { deleted: vid });
    }
    if (op === "reference" && req.method === "GET") return f.reference ? json(200, f.reference) : json(404, { error: { code: 404, message: "this file has no reference", status: "NOT_FOUND" } });
    if (op === "reference" && req.method === "PUT") {
      const r = py("check_reference", j);
      if (r.error) return json(400, { error: { code: 400, message: r.error, status: "INVALID_ARGUMENT" } });
      return (f.reference = r.ok), json(200, r.ok);
    }
    if (!op) { const { audio, versions, reference, ...file } = f; return json(200, { file, versions: [...versions].reverse().map(({ response, names, ...v }) => ({ ...v, text_chars: response.output_text.length, speakers: 2 })) }); }
    if (op === "audio") return json(200, { url: `http://localhost:${process.env.MOCK_PORT ?? 5181}/mock-audio/${id}`, mime_type: f.mime_type, expires_in: 900 });
    const ver = f.versions.find((x) => x.id === vid);
    if (op === "versions" && !ver) return json(404, { error: { code: 404, message: "version not found", status: "NOT_FOUND" } });
    if (op === "versions" && names === "/names" && req.method === "PUT") { // the real service also checks: max 8 keys spk_<n>, names 1 to 40 chars
      const bad = typeof j !== "object" || Array.isArray(j) || Object.keys(j).length > 8 || Object.entries(j).some(([k, x]) => !/^spk_\d{1,2}$/.test(k) || typeof x !== "string" || !x.trim() || x.trim().length > 40);
      if (bad) return json(400, { error: { code: 400, message: "bad names", status: "INVALID_ARGUMENT" } });
      ver.names = Object.fromEntries(Object.entries(j).map(([k, x]) => [k, x.trim()]));
      return json(200, { names: ver.names });
    }
    if (op === "versions" && names === "/score" && req.method === "GET") return f.reference ? json(200, py("score", f.reference, ver).ok) : json(404, { error: { code: 404, message: "this file has no reference", status: "NOT_FOUND" } });
    if (op === "versions" && !names && req.method === "GET") { const { names: n = {}, ...rest } = ver; return json(200, { ...rest, names: n }); }
    if (op !== "transcribe" || req.method !== "POST") return json(404, { error: { code: 404, message: "not found", status: "NOT_FOUND" } });
    const now = new Date(), stamp = now.toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
    const v = { id: `${stamp}-${crypto.randomUUID().slice(0, 4)}`, file_id: id, created: now.toISOString().slice(0, 19) + "Z", label: j.label ?? "", image_tag: "mock",
      settings: { language_codes: j.language_codes ?? [], diarization: !!j.diarization }, run_seconds: 0.3, setup: MOCK_SETUP,
      response: gemini({ input: [{ type: "file" }], generation_config: { transcription_config: { mode: j.diarization ? { diarization_mode: "speaker" } : {} } } }, f.versions.length + 1) };
    f.versions.push(v);
    return json(201, v);
  }
  res.writeHead(404, cors); res.end();
}).listen(Number(process.env.MOCK_PORT ?? 5181), () => console.log(`mock ready on ${process.env.MOCK_PORT ?? 5181}`));

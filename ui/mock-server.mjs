// Local stand-in for the model gateways (TTS, LLM), for UI work without GCP: npm run mock (port 5181, key "test").
// It answers the CORS preflight like Kokoro and vLLM do. Extend it when you add a panel for a new type.
import http from "node:http";
const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*" };
http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") { res.writeHead(200, cors); return res.end(); }
  if (req.headers["x-api-key"] !== "test") { res.writeHead(403, cors); return res.end("bad key"); }
  let body = ""; for await (const c of req) body += c; const j = body ? JSON.parse(body) : {};
  if (req.url === "/v1/audio/voices") { res.writeHead(200, { ...cors, "Content-Type": "application/json" }); return res.end(JSON.stringify({ voices: [{ id: "af_heart", name: "af_heart" }, { id: "am_adam", name: "am_adam" }] }) // Kokoro shape); }
  if (req.url === "/v1/audio/speech") {
    res.writeHead(200, { ...cors, "Content-Type": "audio/pcm" });
    for (let k = 0; k < 5; k++) { // 5 x 0.5 s of 440 Hz at 24 kHz, odd-sized chunks
      const b = Buffer.alloc(24000); for (let i = 0; i < 12000; i++) b.writeInt16LE(Math.round(8000 * Math.sin((k * 12000 + i) * 2 * Math.PI * 440 / 24000)), i * 2);
      res.write(b.subarray(0, 11001)); res.write(b.subarray(11001)); await new Promise(r => setTimeout(r, 300));
    }
    return res.end();
  }
  if (req.url === "/v1/chat/completions") {
    const words = `Echo: ${j.messages.at(-1).content}. The sea is wide and deep.`.split(" ");
    if (!j.stream) { res.writeHead(200, { ...cors, "Content-Type": "application/json" }); return res.end(JSON.stringify({ choices: [{ message: { content: words.join(" ") } }], usage: { completion_tokens: words.length } })); }
    res.writeHead(200, { ...cors, "Content-Type": "text/event-stream" });
    for (const w of words) { res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: w + " " } }] })}\n\n`); await new Promise(r => setTimeout(r, 80)); }
    res.write(`data: ${JSON.stringify({ choices: [], usage: { completion_tokens: words.length } })}\n\ndata: [DONE]\n\n`); return res.end();
  }
  res.writeHead(404, cors); res.end();
}).listen(5181);

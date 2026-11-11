/** Split an SSE text buffer into complete events. Returns the data of each event and the unfinished rest. */
export function parseSse(buffer: string): { events: string[]; rest: string } {
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  const events = blocks
    .map((b) =>
      b
        .split(/\r?\n/)
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).replace(/^ /, ""))
        .join("\n"),
    )
    .filter((d) => d !== "");
  return { events, rest };
}

/** The data of each event in an SSE response body, until "[DONE]" or the end. */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const reader = body.pipeThrough(new TextDecoderStream() as ReadableWritablePair<string, Uint8Array>).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const { events, rest } = parseSse(buffer + value);
    buffer = rest;
    for (const e of events) {
      if (e === "[DONE]") return;
      yield e;
    }
  }
}

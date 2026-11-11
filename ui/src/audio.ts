/** 16-bit little-endian mono PCM -> float samples in [-1, 1). The byte count must be even. */
export function pcm16ToFloat32(bytes: Uint8Array): Float32Array<ArrayBuffer> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const out = new Float32Array(bytes.byteLength >> 1);
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true) / 32768;
  return out;
}

/** WAV file (16-bit mono) around raw PCM chunks, so a PCM stream can be played and downloaded later. */
export function wavFromPcm(chunks: Uint8Array[], sampleRate: number): Blob {
  const size = chunks.reduce((n, c) => n + c.byteLength, 0);
  const h = new DataView(new ArrayBuffer(44));
  const str = (o: number, s: string) => [...s].forEach((ch, i) => h.setUint8(o + i, ch.charCodeAt(0)));
  str(0, "RIFF");
  h.setUint32(4, 36 + size, true);
  str(8, "WAVE");
  str(12, "fmt ");
  h.setUint32(16, 16, true); // fmt chunk size
  h.setUint16(20, 1, true); // PCM
  h.setUint16(22, 1, true); // mono
  h.setUint32(24, sampleRate, true);
  h.setUint32(28, sampleRate * 2, true); // byte rate
  h.setUint16(32, 2, true); // block align
  h.setUint16(34, 16, true); // bits per sample
  str(36, "data");
  h.setUint32(40, size, true);
  return new Blob([h.buffer, ...chunks.map((c) => c.slice())], { type: "audio/wav" });
}

/** Plays PCM chunks as they arrive (Web Audio). Works in every browser, also iOS Safari.
 *  Make it in the click handler: browsers start audio only after a user gesture. */
export class PcmPlayer {
  private ctx = new AudioContext();
  private next = 0;
  private odd: Uint8Array | null = null; // a chunk can end in the middle of a 2-byte sample

  constructor(private sampleRate: number) {
    void this.ctx.resume();
  }

  push(chunk: Uint8Array) {
    let bytes = chunk;
    if (this.odd) {
      bytes = new Uint8Array(this.odd.length + chunk.length);
      bytes.set(this.odd);
      bytes.set(chunk, this.odd.length);
      this.odd = null;
    }
    if (bytes.length % 2) {
      this.odd = bytes.slice(-1);
      bytes = bytes.subarray(0, -1);
    }
    if (!bytes.length) return;
    const samples = pcm16ToFloat32(bytes);
    const buf = this.ctx.createBuffer(1, samples.length, this.sampleRate);
    buf.copyToChannel(samples, 0);
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctx.destination);
    this.next = Math.max(this.next, this.ctx.currentTime + 0.05);
    src.start(this.next);
    this.next += buf.duration;
  }

  stop() {
    void this.ctx.close();
  }
}

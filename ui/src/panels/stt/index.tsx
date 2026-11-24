import { useEffect, useRef, useState } from "react";
import { call, curlFor, errorText } from "../../api";
import { Curl, Status, Timings, type Timing } from "../../components";
import { parseHash, sttHash, type ModelConfig } from "../../config";
import AllFiles from "./AllFiles";
import Compare from "./Compare";
import Evaluation from "./Evaluation";
import Files from "./Files";
import History, { type NewRun } from "./History";
import Player from "./Player";
import RefEditor from "./RefEditor";
import Speakers from "./Speakers";
import Transcript from "./Transcript";
import {
  JSON_HDR, TIMEOUT_MSG, bestCpwer, hasUnsavedEdits, resolveView, draftFromVersion, formatReference, gatewayTimedOut, groupTurns, importReference, mimeOf, parseReference, refSeconds, refTime, renameRefSpeaker, when, words,
  type FileRow, type Names, type RefTurn, type Reference, type Score, type SetupRow, type Summary, type Version, type View,
} from "./lib";

// STT-A with stored files and transcript history (specs: docs/specs/2026-11-21-stt-a-design.md, layout:
// docs/specs/2026-11-24-stt-ui-layout-design.md). 3 columns: files | history (the reference of the file, then the
// versions) | work area. A version shows its Transcript. The reference (optional, 1 per file) has Edit, Evaluation and
// Speakers. Every file goes through POST /v1beta/uploads (signed PUT); each POST /v1beta/files/<id>/transcribe is a version.

const REF_VIEWS: View[] = ["evaluation", "speakers"]; // the edit page ("edit") is a full-width page of its own
const VIEW_TITLE: Record<View, string> = { transcript: "Transcript", edit: "Edit", evaluation: "Evaluation", speakers: "Speakers" };

export default function Stt({ model }: { model: ModelConfig }) {
  const [h, setH] = useState(() => {
    const x = parseHash(location.hash);
    return x.tab === model.id ? x : { tab: model.id };
  });
  const hRef = useRef(h);
  hRef.current = h;
  const all = h.file === "all";
  const fileId = all ? undefined : h.file;

  const [files, setFiles] = useState<FileRow[]>([]);
  const [setups, setSetups] = useState<SetupRow[]>([]);
  const [best, setBest] = useState<Record<string, number>>({});
  const [detail, setDetail] = useState<{ file: FileRow; versions: Summary[] }>();
  const [full, setFull] = useState<Record<string, Version>>({});
  const [scores, setScores] = useState<Record<string, Score>>({});
  const [reference, setReference] = useState<Reference>();
  const [refText, setRefText] = useState("");
  const [refLang, setRefLang] = useState("");
  const [ticked, setTicked] = useState<string[]>([]);
  const [newRun, setNewRun] = useState<NewRun>({ lang: "", diarize: true, label: "" });
  const [busy, setBusy] = useState("");
  const [startedAt, setStartedAt] = useState<number>();
  const [runError, setRunError] = useState<string>();
  const [t, setT] = useState<Timing>({});
  const [retry, setRetry] = useState<number>();
  const [error, setError] = useState<string>();
  const [note, setNote] = useState<string>();
  const [curl, setCurl] = useState("");
  const abort = useRef<AbortController>(null);
  // 1 <audio> for the file. The signed GET URL lasts 15 minutes, so it is fetched again after 10 minutes.
  const audio = useRef<HTMLAudioElement>(null);
  const audioSrc = useRef<{ file: string; at: number }>(null);
  const stopAt = useRef(Infinity);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(NaN);
  const [playing, setPlaying] = useState(false);
  const [playingTurn, setPlayingTurn] = useState<{ version: string; turn: number }>();
  const [rate, setRate] = useState(1);
  const [follow, setFollow] = useState(true);
  const current = useRef(fileId); // the selected file: a late answer for another file must not show
  current.current = fileId;

  // The row, the view and the working version come from the URL, with fallbacks (spec: "URL").
  // detail of the previous file can still be in place in the first render after a file change: ignore it.
  const versions = detail && detail.file.id === fileId ? detail.versions : [];
  const { row, working, view, noVersions } = resolveView(versions, h, !!reference);
  // The compare page: a = "ref" or a version, b = a version (defaults: the reference or the second newest | the working version).
  const cmp = h.row === "compare" && !!fileId;
  const known = (id?: string) => !!id && versions.some((v) => v.id === id);
  const cmpB = known(h.b) ? h.b! : (working ?? "");
  const cmpA = h.a === "ref" && reference ? "ref" : known(h.a) ? h.a! : reference ? "ref" : (versions.find((v) => v.id !== cmpB)?.id ?? "");
  const canCompare = versions.length > 0 && (!!reference || versions.length > 1);

  /** Change the URL. A new file adds a history entry; a row or view change replaces it. */
  const go = (p: { file?: string; row?: string; view?: string; v?: string; a?: string; b?: string }, push = false) => {
    const c = hRef.current;
    const n = { file: c.file, row: c.row, view: c.view, v: c.v, a: c.a, b: c.b, ...p };
    const hash = sttHash(model.id, c.platform, n.file, n.row, n.view, n.v, n.row === "compare" ? { a: n.a, b: n.b } : undefined);
    if (push) location.hash = hash;
    else history.replaceState(null, "", hash), setH(parseHash(hash));
  };
  const open = (id: string) => go({ file: id, row: undefined, view: undefined, v: undefined }, true);
  const select = (r: string) => (r === "ref" ? go({ row: "ref", view: hRef.current.row === "ref" && hRef.current.view !== "edit" ? hRef.current.view : reference ? "evaluation" : "edit", v: working }) : go({ row: r, view: undefined, v: undefined }));

  const get = async <T,>(path: string): Promise<T> => {
    const res = await call(model, path, { method: "GET" });
    if (!res.ok) throw new Error(await errorText(res));
    return res.json();
  };
  const loadFiles = () => get<{ files: FileRow[] }>("/v1beta/files").then((d) => setFiles(d.files), (e) => setError(String(e)));
  const loadSetups = () =>
    get<{ rows: { file_id: string; cpwer: number }[]; setups: SetupRow[] }>("/v1beta/scores").then(
      (d) => (setSetups(d.setups), setBest(bestCpwer(d.rows))),
      (e) => setError(`Scores: ${e}`),
    );
  const loadScores = (id: string, vs: Summary[]) =>
    Promise.all(vs.map((v) => get<Score>(`/v1beta/files/${id}/versions/${v.id}/score`).then((s) => [v.id, s] as const))).then(
      (list) => current.current === id && setScores(Object.fromEntries(list)),
      (e) => setError(`Scores: ${e}`),
    );
  const draft = useRef({ text: refText, saved: reference });
  draft.current = { text: refText, saved: reference };
  /** force: a file change or a reference save. Else (a run, a Refresh) unsaved editor text stays. */
  const showReference = (r?: Reference, force = true) => {
    const keep = !force && hasUnsavedEdits(draft.current.text, draft.current.saved);
    setReference(r);
    if (!keep) setRefText(r ? formatReference(r) : ""), setRefLang(r?.language ?? "");
  };
  const loadReference = async (id: string, force: boolean) => {
    const res = await call(model, `/v1beta/files/${id}/reference`, { method: "GET" });
    if (current.current !== id) return false;
    if (res.status === 404) return (showReference(undefined, force), setScores({}), false);
    if (!res.ok) return (setError(`Reference: ${await errorText(res)}`), false);
    const r: Reference = await res.json();
    if (current.current !== id) return false;
    showReference(r, force);
    return true;
  };
  const loadDetail = (id: string, forceRef = false) =>
    get<{ file: FileRow; versions: Summary[] }>(`/v1beta/files/${id}`).then(
      (d) => {
        if (current.current !== id) return;
        setDetail(d);
        void loadReference(id, forceRef).then((ok) => ok && loadScores(id, d.versions));
      },
      (e) => setError(String(e)),
    );
  const fetchVersion = async (id: string): Promise<Version> => {
    const v = full[id] ?? (await get<Version>(`/v1beta/files/${fileId}/versions/${id}`));
    if (current.current === fileId) setFull((f) => ({ ...f, [id]: v }));
    return v;
  };

  useEffect(() => {
    void loadFiles();
    void loadSetups();
    const onHash = () => {
      const x = parseHash(location.hash);
      if (x.tab !== model.id) return;
      // The nav link has no file id: keep the selected file and put it back in the URL.
      const c = hRef.current;
      if (!x.file && c.file) history.replaceState(null, "", sttHash(model.id, x.platform, c.file, c.row, c.view, c.v));
      else setH(x);
    };
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, [model.base_url]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    audio.current?.pause();
    audio.current?.removeAttribute("src");
    audioSrc.current = null;
    setTime(0);
    setDuration(NaN);
    setDetail(undefined);
    setFull({});
    setTicked([]);
    setScores({});
    showReference(undefined);
    setNote(undefined);
    setError(undefined);
    if (fileId) void loadDetail(fileId, true);
  }, [fileId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Full versions are fetched only when shown: the working version and the ticked ones.
  useEffect(() => {
    if (!fileId) return;
    const ids = cmp ? [cmpA, cmpB] : [working, ...ticked];
    for (const id of [...new Set(ids)].filter((x): x is string => !!x && x !== "ref" && !full[x])) fetchVersion(id).catch((e) => setError(String(e)));
  }, [working, ticked.join(), fileId, cmp, cmpA, cmpB]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (audio.current) audio.current.playbackRate = rate;
  }, [rate]);

  // --- audio ---
  const ensureAudio = async () => {
    const a = audio.current;
    if (!a || !fileId) return false;
    if (audioSrc.current?.file !== fileId || performance.now() - audioSrc.current.at > 600_000) {
      const d = await get<{ url: string }>(`/v1beta/files/${fileId}/audio`);
      const at = a.currentTime;
      a.src = d.url;
      a.playbackRate = rate;
      if (audioSrc.current?.file === fileId) a.currentTime = at;
      audioSrc.current = { file: fileId, at: performance.now() };
    }
    return true;
  };
  const startAt = async (start: number, end: number, turn?: { version: string; turn: number }) => {
    const a = audio.current;
    try {
      if (!a || !(await ensureAudio())) return;
      stopAt.current = end;
      a.currentTime = start;
      setTime(start);
      setPlayingTurn(turn);
      await a.play();
    } catch (e) {
      setPlayingTurn(undefined);
      setError(String(e));
    }
  };
  const playTurn = (version: string, turn: number, start: number, end: number) =>
    playingTurn?.version === version && playingTurn.turn === turn ? audio.current?.pause() : void startAt(start, end, { version, turn });
  /** Play 1 part of the compare page (key: which part), only that part. A second click stops it. */
  const playRange = (key: string, start: number, end: number) => (playingTurn?.version === key ? audio.current?.pause() : void startAt(start, end, { version: key, turn: -1 }));
  const toggle = () => (playing ? audio.current?.pause() : void startAt(audio.current?.currentTime ?? time, Infinity));
  const seek = async (s: number) => {
    const a = audio.current;
    if (!a) return;
    try {
      if (!(await ensureAudio())) return;
      a.currentTime = s;
      setTime(s);
      if (playingTurn) stopAt.current = Infinity; // a seek ends the "1 turn only" play
    } catch (e) {
      setError(String(e));
    }
  };
  const playFirst = (label: string) => {
    const v = working ? full[working] : undefined;
    if (!v) return;
    const groups = groupTurns(words(v));
    const i = groups.findIndex((g) => g.speaker === label);
    if (i >= 0) playTurn(v.id, i, parseFloat(groups[i].start), parseFloat(groups[i].end));
  };
  // timeupdate comes about every 250 ms in Chrome, so a frame loop stops the turn on time; timeupdate covers a hidden tab.
  const cmpRef = useRef(false);
  cmpRef.current = cmp;
  const tick = () => {
    const a = audio.current;
    if (!a) return;
    if (!cmpRef.current) setTime(a.currentTime); // the compare page shows no time: no re-render 60 times per second
    if (!a.paused && a.currentTime >= stopAt.current) a.pause();
  };
  const watch = () => {
    tick();
    if (audio.current && !audio.current.paused) requestAnimationFrame(watch);
  };

  // --- names and reference ---
  const putNames = async (version: string, names: Names) => {
    const res = await call(model, `/v1beta/files/${fileId}/versions/${version}/names`, { method: "PUT", headers: JSON_HDR, body: JSON.stringify(names) });
    if (!res.ok) throw new Error(`Names: ${await errorText(res)}`);
    const d: { names: Names } = await res.json();
    setFull((f) => (f[version] ? { ...f, [version]: { ...f[version], names: d.names } } : f));
  };
  const saveNames = (version: string, names: Names) => putNames(version, names).catch((e) => setError(String(e)));
  const putReference = async (body: Reference) => {
    const res = await call(model, `/v1beta/files/${fileId}/reference`, { method: "PUT", headers: JSON_HDR, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`Reference: ${await errorText(res)}`);
    setError(undefined);
    void loadFiles();
    void loadSetups();
    if (fileId) void loadDetail(fileId, true);
  };
  const saveReference = async () => {
    try {
      await putReference(parseReference(refText, refLang));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const renameRef = async (renames: [string, string][]) => {
    if (!reference) return;
    const froms = new Set(renames.map(([a]) => a));
    if (renames.some(([, b]) => froms.has(b))) return setError("A new name is the ID of another renamed speaker. Rename in 2 steps.");
    try {
      await putReference(renames.reduce((r, [a, b]) => renameRefSpeaker(r, a, b), reference));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const draftReference = () => {
    const v = working ? full[working] : undefined;
    if (!v) return setError("Select a version first: its turns become the draft.");
    if (refText.trim() && !confirm("Replace the text in the editor with the working version?")) return;
    setRefText(draftFromVersion(words(v), v.response.output_text ?? "", v.names));
    setRefLang(v.settings.language_codes[0] ?? refLang);
  };
  const importRef = (f: File) =>
    void f.text().then((text) => {
      try {
        const isSm = /^\s*\{/.test(text) && "results" in JSON.parse(text);
        if (!isSm) return setRefText(text);
        const r = importReference(text, refLang);
        const clockTimes = (x: RefTurn) => (x.start === undefined || x.end === undefined ? x : { ...x, start: refTime(refSeconds(x.start)), end: refTime(refSeconds(x.end)) });
        setRefText(formatReference({ ...r, turns: r.turns.map(clockTimes) }));
        setRefLang(r.language);
      } catch (e) {
        setError(`Import: ${e instanceof Error ? e.message : e}`);
      }
    });

  // --- runs ---
  const transcribe = async (id: string, signal: AbortSignal, timing: Timing) => {
    const body = { ...(newRun.lang ? { language_codes: [newRun.lang] } : {}), diarization: newRun.diarize, ...(newRun.label ? { label: newRun.label } : {}) };
    const path = `/v1beta/files/${id}/transcribe`;
    setCurl(curlFor(model, path, body));
    setBusy("Transcribing…");
    setStartedAt(Date.now());
    let res: Response;
    const sent = performance.now();
    try {
      res = await call(model, path, { method: "POST", headers: JSON_HDR, body: JSON.stringify(body), signal }, (n) => (setRetry(n), (timing.retries = n)));
    } catch (e) {
      // shortcut: the time includes 429 retries, so a network error late in a retry loop also reads as a timeout.
      if (!signal.aborted && gatewayTimedOut(undefined, performance.now() - sent)) throw new Error(TIMEOUT_MSG);
      throw e;
    }
    setRetry(undefined);
    timing.status = res.status;
    if (gatewayTimedOut(res.status, 0)) throw new Error(TIMEOUT_MSG);
    if (!res.ok) throw new Error(await errorText(res));
    const v: Version = await res.json();
    if (current.current === id) setFull((f) => ({ ...f, [v.id]: v }));
    return v.id;
  };
  const run = async (work: (signal: AbortSignal, timing: Timing) => Promise<{ file: string; version?: string } | void>) => {
    abort.current?.abort();
    abort.current = new AbortController();
    const signal = abort.current.signal;
    setError(undefined);
    setRunError(undefined);
    const t0 = performance.now();
    const timing: Timing = { retries: 0 };
    try {
      const r = await work(signal, timing);
      timing.totalMs = performance.now() - t0;
      void loadFiles();
      void loadSetups();
      if (r && r.file === current.current) {
        void loadDetail(r.file);
        if (r.version) go({ row: r.version, view: undefined, v: undefined });
      }
    } catch (e) {
      if (!signal.aborted) (setError(String(e)), setRunError(String(e)));
    } finally {
      setT({ ...timing });
      setBusy("");
      setStartedAt(undefined);
      setRetry(undefined);
    }
  };
  const again = () => fileId && void run(async (signal, timing) => ({ file: fileId, version: await transcribe(fileId, signal, timing) }));
  const upload = (file: File) =>
    void run(async (signal, timing) => {
      setBusy("Uploading…");
      setStartedAt(Date.now());
      const start = performance.now();
      const mime = mimeOf(file);
      const up = await call(model, "/v1beta/uploads", { method: "POST", headers: JSON_HDR, body: JSON.stringify({ name: file.name, mime_type: mime, size_bytes: file.size }), signal });
      if (!up.ok) throw new Error(`Upload URL: ${await errorText(up)}`);
      const u = (await up.json()) as { id: string; upload_url: string; method: string; headers: Record<string, string> };
      // The signed URL needs no API key: plain fetch, not call().
      const put = await fetch(u.upload_url, { method: u.method, headers: u.headers, body: file, signal });
      if (!put.ok) throw new Error(`Upload: ${await errorText(put)}`);
      timing.firstMs = performance.now() - start;
      void loadFiles();
      open(u.id);
      current.current = u.id; // the hash change applies after this tick; the run result is for this file
      return { file: u.id, version: await transcribe(u.id, signal, timing) };
    });

  const tickVersion = (id: string) => setTicked((old) => (old.includes(id) ? old.filter((x) => x !== id) : [...old, id].slice(-2)));
  const partner = ticked.find((id) => id !== working);
  const shown = [working, partner].map((id) => (id ? full[id] : undefined)).filter((v): v is Version => !!v);
  const tabs: View[] = row !== "ref" ? ["transcript"] : REF_VIEWS;
  const editPage = !!detail && row === "ref" && view === "edit"; // the reference editor: full width, no files and history columns
  const wide = cmp || editPage;

  return (
    <section className={`stt${all ? " stt-all-view" : ""}${wide ? " stt-compare-view" : ""}`}>
      {!wide && <Files files={files} selected={h.file} best={best} busy={!!busy} onOpen={open} onAll={() => go({ file: "all", row: undefined, view: undefined, v: undefined }, true)} onUpload={upload} onRefresh={() => void (setError(undefined), loadFiles(), loadSetups(), fileId && loadDetail(fileId))} />}
      {!all && !wide && (
        <div className="stt-col">
          {detail ? (
            <History
              versions={versions}
              scores={scores}
              reference={reference}
              row={row}
              ticked={ticked}
              run={{ busy, startedAt, error: runError }}
              newRun={newRun}
              onNewRun={setNewRun}
              onSelect={select}
              onTick={tickVersion}
              onRun={again}
              onStop={() => abort.current?.abort()}
            />
          ) : (
            <p className="muted">{fileId ? "Loading…" : "Pick a file."}</p>
          )}
        </div>
      )}
      <div className="stt-work">
        {all ? (
          <AllFiles setups={setups} />
        ) : cmp && detail ? (
          <>
            <Status error={error} retry={retry} />
            <Compare
              reference={reference}
              versions={versions}
              a={cmpA}
              b={cmpB}
              va={cmpA !== "ref" ? full[cmpA] : undefined}
              vb={full[cmpB]}
              playing={playingTurn?.turn === -1 ? playingTurn.version : undefined}
              onAB={(a, b) => go({ a, b })}
              onBack={() => go({ row: cmpB || undefined, view: undefined, v: undefined })}
              onPlay={playRange}
              onRenameRef={renameRef}
              onSaveNames={putNames}
            />
          </>
        ) : editPage && detail ? (
          <>
            <Status error={error} retry={retry} />
            <RefEditor
              fileName={detail.file.name}
              text={refText}
              language={refLang}
              saved={reference}
              version={working ? full[working] : undefined}
              playing={playingTurn?.turn === -1 ? playingTurn.version : undefined}
              onText={setRefText}
              onLanguage={setRefLang}
              onSave={() => void saveReference()}
              onDraft={draftReference}
              onImport={importRef}
              onBack={() => go(reference ? { row: "ref", view: "evaluation" } : { row: working, view: undefined, v: undefined })}
              onPlay={playRange}
            />
          </>
        ) : !detail ? (
          <>
            <p className="muted">{fileId ? "Loading the file…" : "Upload a file or pick one from the list."}</p>
            <Status error={error} retry={retry} />
            {busy && !retry && <p className="info">{busy}</p>}
          </>
        ) : (
          <>
            <div className="stt-filehead">
              <b>{detail.file.name}</b>{" "}
              <span className="muted">
                {(detail.file.size_bytes / 1e6).toFixed(1)} MB · {when(detail.file.created)}
              </span>{" "}
              {canCompare && (
                <button title="Compare 2 transcripts on a full-width page" onClick={() => go({ row: "compare", view: undefined, v: undefined, a: cmpA, b: cmpB }, true)}>
                  ⇆ Compare
                </button>
              )}
            </div>
            <Status error={error} retry={retry} />
            {busy && !retry && <p className="info">{busy}</p>}
            {note && <p className="info">{note}</p>}
            {noVersions && <p className="info">No versions yet. Use "New run".</p>}
            <div className="stt-tabs" role="tablist">
              <span className="muted">{row === "ref" ? "File reference:" : "Version:"}</span>
              {tabs.map((x) => (
                <button key={x} role="tab" aria-selected={view === x} className={view === x ? "active" : ""} onClick={() => go({ view: x })}>
                  {VIEW_TITLE[x]}
                </button>
              ))}
              {row === "ref" && <button onClick={() => go({ view: "edit" })}>✎ Edit reference</button>}
            </div>
            <Player time={time} duration={duration} playing={playing} rate={rate} follow={follow} onToggle={toggle} onSeek={(s) => void seek(s)} onRate={setRate} onFollow={setFollow} />
            {view === "transcript" && (
              <>
                <div className={shown.length === 2 ? "compare" : ""}>
                  {shown.map((v) => (
                    <Transcript
                      key={v.id}
                      v={v}
                      time={time}
                      active={playing}
                      playingTurn={playingTurn?.version === v.id ? playingTurn.turn : undefined}
                      follow={follow}
                      editNames={!reference}
                      onPlayTurn={(turn, start, end) => playTurn(v.id, turn, start, end)}
                      onSeek={(s) => void seek(s)}
                      onNames={(n) => saveNames(v.id, n)}
                      onRenameLink={() => go({ row: "ref", view: "speakers", v: v.id })}
                    />
                  ))}
                </div>
                <details className="stt-request">
                  <summary>Request details</summary>
                  <Timings t={t} firstLabel="Upload done" />
                  <Curl text={curl} />
                </details>
              </>
            )}
            {view === "evaluation" && <Evaluation versions={versions} scores={scores} working={working} />}
            {view === "speakers" && reference && (
              <Speakers
                reference={reference}
                version={working ? full[working] : undefined}
                score={working ? scores[working] : undefined}
                onRenameRef={renameRef}
                onSaveNames={(n) => (working ? saveNames(working, n) : Promise.resolve())}
                onPlayFirst={playFirst}
              />
            )}
          </>
        )}
      </div>
      <audio
        ref={audio}
        hidden
        onPlaying={() => (setPlaying(true), watch())}
        onTimeUpdate={tick}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onEmptied={() => setPlaying(false)} // a new src stops playback without a pause event
        onPause={() => (setPlaying(false), setPlayingTurn(undefined))}
        onEnded={() => (setPlaying(false), setPlayingTurn(undefined))}
        onError={() => (setPlaying(false), setPlayingTurn(undefined), audio.current?.src && setError("The audio cannot play in this browser."))}
      />
    </section>
  );
}

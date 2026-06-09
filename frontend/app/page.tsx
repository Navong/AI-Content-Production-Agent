"use client";

import { type ReactElement } from "react";
import Link from "next/link";
import { useGeneration, type AppStatus, type NodeKey } from "./generation-context";

// ── Pipeline definition ───────────────────────────────────────────────────────

const PIPELINE: { key: NodeKey; label: string; sub: string; icon: ReactElement }[] = [
  { key: "supervisor", label: "Supervisor", sub: "router", icon: <IconRoute /> },
  { key: "prompt_engineer", label: "Prompt", sub: "Sonnet 4.6", icon: <IconSpark /> },
  { key: "image_gen", label: "Image", sub: "FLUX 2 Pro", icon: <IconImage /> },
  { key: "quality_eval", label: "Quality", sub: "Opus 4.8 vision", icon: <IconScan /> },
  { key: "hitl_gate", label: "Human", sub: "approval", icon: <IconUserCheck /> },
];
const ORDER = PIPELINE.map((n) => n.key);

type NodeVisual = "idle" | "pending" | "active" | "done" | "approved" | "rejected";

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Home() {
  const {
    brief, setBrief, status, activeNode, iteration, image, score, feedback,
    results, errorMsg, notice, setNotice, mode, setMode, productImage,
    uploading, uploadErr, composerOpen, setComposerOpen, caption, setCaption,
    captionLoading, publishing, tweetUrl, publishErr, xEnabled, fileRef,
    selectResult, onUpload, onGenerate, onAction, openComposer, publish,
  } = useGeneration();

  function nodeState(key: NodeKey): NodeVisual {
    if (status === "idle") return "idle";
    if (status === "approved" || status === "rejected") {
      if (key === "hitl_gate") return status;
      return "done";
    }
    if (key === "hitl_gate" && status === "paused") return "active";
    const ai = activeNode ? ORDER.indexOf(activeNode) : 0;
    const ki = ORDER.indexOf(key);
    if (ki < ai) return "done";
    if (ki === ai) return key === "supervisor" ? "done" : "active";
    return "pending";
  }

  const issues = feedback.split(/suggested fix:/i)[0]?.trim();
  const suggestedFix = feedback.split(/suggested fix:/i)[1]?.trim();

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col px-5 pb-24 sm:px-8">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-20 -mx-5 mb-8 flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg)]/70 px-5 py-4 backdrop-blur-xl sm:-mx-8 sm:px-8">
        <div className="flex items-center gap-3">
          <div className="accent-grad flex h-9 w-9 items-center justify-center rounded-xl shadow-lg shadow-violet-500/20">
            <IconSpark />
          </div>
          <div className="leading-tight">
            <h1 className="text-[15px] font-semibold tracking-tight">AI Content Studio</h1>
            <p className="text-[11px] text-neutral-500">Multi-agent production pipeline</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <StatusChip status={status} />
          <Link
            href="/dashboard"
            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs text-neutral-300 transition hover:border-[var(--border-strong)] hover:bg-white/5"
          >
            Dashboard
          </Link>
        </div>
      </header>

      {/* ── Command bar ───────────────────────────────────────────────────────── */}
      <section className="panel animate-fade-up rounded-2xl p-5">
        {/* mode toggle */}
        <div className="mb-4 inline-flex rounded-lg border border-[var(--border)] p-0.5 text-xs">
          {(["ad", "text"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              disabled={status === "running"}
              className={`rounded-md px-3 py-1.5 font-medium transition ${
                mode === m
                  ? "bg-white/10 text-neutral-100"
                  : "text-neutral-500 hover:text-neutral-300"
              }`}
            >
              {m === "ad" ? "📦 Product ad" : "✏️ Text brief"}
            </button>
          ))}
        </div>

        {mode === "ad" ? (
          <div className="flex flex-col gap-3 sm:flex-row">
            {/* product upload */}
            <div className="shrink-0 sm:w-44">
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onUpload(f);
                  e.target.value = "";
                }}
              />
              {productImage ? (
                <div className="group relative h-44 w-full overflow-hidden rounded-xl border border-[var(--border)]">
                  <img src={productImage} alt="product" className="h-full w-full object-cover" />
                  <button
                    onClick={() => fileRef.current?.click()}
                    disabled={status === "running"}
                    className="absolute inset-0 flex items-center justify-center bg-black/60 text-xs font-medium text-white opacity-0 transition group-hover:opacity-100"
                  >
                    Replace photo
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={uploading || status === "running"}
                  className="flex h-44 w-full flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed border-[var(--border-strong)] text-neutral-500 transition hover:border-violet-500/50 hover:text-neutral-300 disabled:opacity-40"
                >
                  {uploading ? <Spinner big /> : <IconUpload />}
                  <span className="text-xs font-medium">
                    {uploading ? "Uploading…" : "Upload product photo"}
                  </span>
                  <span className="px-3 text-center text-[10px] text-neutral-600">
                    plain background works best
                  </span>
                </button>
              )}
              {uploadErr && <p className="mt-1 text-xs text-red-400">{uploadErr}</p>}
            </div>
            {/* description + generate */}
            <div className="flex flex-1 flex-col gap-3">
              <textarea
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") onGenerate();
                }}
                placeholder="Describe your product — name, material, scent/feel, the vibe you want… (⌘/Ctrl+Enter)"
                rows={5}
                className="flex-1 resize-none rounded-xl border border-[var(--border)] bg-black/30 p-3 text-sm outline-none transition placeholder:text-neutral-600 focus:border-violet-500/60"
                disabled={status === "running"}
              />
              <button
                onClick={onGenerate}
                disabled={!brief.trim() || !productImage || uploading || status === "running"}
                className="accent-grad flex h-[44px] items-center justify-center gap-2 rounded-xl px-6 text-sm font-semibold text-white shadow-lg shadow-violet-500/25 transition hover:brightness-110 disabled:opacity-40 disabled:saturate-50"
              >
                {status === "running" ? (
                  <><Spinner /> Producing ad…</>
                ) : (
                  <><IconSpark /> Generate ad</>
                )}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-3 sm:flex-row">
              <textarea
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") onGenerate();
                }}
                placeholder="Describe the content you want… (⌘/Ctrl + Enter to run)"
                rows={2}
                className="flex-1 resize-none rounded-xl border border-[var(--border)] bg-black/30 p-3 text-sm outline-none transition placeholder:text-neutral-600 focus:border-violet-500/60"
                disabled={status === "running"}
              />
              <button
                onClick={onGenerate}
                disabled={!brief.trim() || status === "running"}
                className="accent-grad group flex h-[52px] items-center justify-center gap-2 self-stretch rounded-xl px-6 text-sm font-semibold text-white shadow-lg shadow-violet-500/25 transition hover:brightness-110 disabled:opacity-40 disabled:saturate-50 sm:self-auto"
              >
                {status === "running" ? (
                  <><Spinner /> Generating</>
                ) : (
                  <><IconPlay /> Generate</>
                )}
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {[
                "Minimalist ceramic mug on linen, soft daylight product shot",
                "Luxury skincare bottle on marble with eucalyptus, editorial lighting",
                "Neon-lit Seoul street at night, cinematic, ultra-detailed",
                "Cute mascot logo of a fox barista, flat vector style",
                "Scandinavian living room, natural light, interior magazine style",
                "something bold for a streetwear brand",
              ].map((b) => (
                <button
                  key={b}
                  onClick={() => setBrief(b)}
                  disabled={status === "running"}
                  className="rounded-full border border-[var(--border)] px-3 py-1 text-xs text-neutral-400 transition hover:border-violet-500/40 hover:text-neutral-200 disabled:opacity-40"
                >
                  {b.length > 42 ? b.slice(0, 42) + "…" : b}
                </button>
              ))}
            </div>
          </>
        )}
      </section>

      {notice && (
        <div className="mt-5 flex items-center justify-between rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <span>{notice}</span>
          <button
            onClick={() => setNotice("")}
            className="ml-4 shrink-0 text-amber-400/70 transition hover:text-amber-200"
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Pipeline graph ────────────────────────────────────────────────────── */}
      <section className="panel mt-5 rounded-2xl p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[11px] font-medium uppercase tracking-widest text-neutral-500">
            Agent pipeline
          </h2>
          {iteration > 0 && (
            <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-medium text-amber-300">
              {mode === "ad" ? `✨ variation ${iteration + 1} of 3` : `↻ retry · iteration ${iteration}`}
            </span>
          )}
        </div>
        <div className="flex items-stretch gap-1 overflow-x-auto pb-1">
          {PIPELINE.map((n, i) => (
            <div key={n.key} className="flex flex-1 items-center gap-1">
              <PipelineNode node={n} state={nodeState(n.key)} />
              {i < PIPELINE.length - 1 && (
                <Edge active={nodeState(PIPELINE[i + 1].key) === "active"} />
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ── Output ────────────────────────────────────────────────────────────── */}
      {status === "error" ? (
        <div className="panel mt-5 rounded-2xl border-red-500/30 bg-red-500/5 p-5 text-sm text-red-300">
          <span className="font-medium">Error:</span> {errorMsg}
        </div>
      ) : status === "idle" ? (
        <EmptyState />
      ) : (
        <section className="mt-5 grid gap-5 lg:grid-cols-[1.4fr_1fr]">
          {/* Canvas */}
          <div className="panel relative overflow-hidden rounded-2xl">
            <div className="flex aspect-square w-full items-center justify-center bg-black/40">
              {image ? (
                <img
                  key={image}
                  src={image}
                  alt="Generated content"
                  className="animate-fade-up h-full w-full object-contain"
                />
              ) : (
                <div className="shimmer flex h-full w-full flex-col items-center justify-center gap-3 text-neutral-600">
                  <Spinner big />
                  <p className="text-xs">
                    {activeNode === "prompt_engineer"
                      ? mode === "ad"
                        ? "Directing the scene…"
                        : "Engineering the prompt…"
                      : mode === "ad"
                      ? "Staging your product…"
                      : "Rendering image…"}
                  </p>
                </div>
              )}
            </div>
            {score > 0 && (
              <div className="absolute right-3 top-3">
                <ScorePill score={score} />
              </div>
            )}
          </div>

          {/* Side panel */}
          <div className="flex flex-col gap-5">
            {/* Critique */}
            <div className="panel rounded-2xl p-5">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-[11px] font-medium uppercase tracking-widest text-neutral-500">
                  Quality review
                </h3>
                {score > 0 && <ScoreDonut score={score} />}
              </div>
              {feedback ? (
                <div className="space-y-3 text-sm leading-relaxed">
                  {issues && <p className="text-neutral-300">{issues}</p>}
                  {suggestedFix && (
                    <div className="rounded-lg border border-[var(--border)] bg-black/20 p-3">
                      <p className="mb-1 text-[11px] font-medium uppercase tracking-wider text-violet-300">
                        Suggested fix
                      </p>
                      <p className="text-xs text-neutral-400">{suggestedFix}</p>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm text-neutral-600">
                  {status === "running"
                    ? "Awaiting the vision model's critique…"
                    : "—"}
                </p>
              )}
            </div>

            {/* Decision */}
            {status === "paused" && (
              <div className="panel animate-fade-up rounded-2xl border-amber-500/20 p-5">
                <p className="mb-3 text-sm text-neutral-300">
                  The agent paused for human approval.
                  <span className="block text-xs text-neutral-500">
                    Approve to ship, regenerate for a fresh take, or reject.
                  </span>
                </p>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    onClick={() => onAction("approve")}
                    className="flex items-center justify-center gap-1.5 rounded-xl bg-emerald-500/90 py-2.5 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400"
                  >
                    <IconCheck /> Approve
                  </button>
                  <button
                    onClick={() => onAction("regenerate")}
                    className="rounded-xl border border-[var(--border-strong)] py-2.5 text-sm font-medium text-neutral-200 transition hover:bg-white/5"
                  >
                    ↻ Regenerate
                  </button>
                  <button
                    onClick={() => onAction("reject")}
                    className="rounded-xl border border-red-500/20 py-2.5 text-sm font-medium text-red-300 transition hover:bg-red-500/10"
                  >
                    ✕ Reject
                  </button>
                </div>
              </div>
            )}

            {(status === "approved" || status === "rejected") && (
              <div
                className={`animate-fade-up rounded-2xl border p-5 text-sm font-medium ${
                  status === "approved"
                    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                    : "border-red-500/30 bg-red-500/10 text-red-300"
                }`}
              >
                {status === "approved"
                  ? "✓ Approved — content package ready for delivery."
                  : "✕ Rejected — run closed."}
              </div>
            )}

            {/* Publish to X */}
            {status === "approved" && xEnabled && (
              <div className="panel animate-fade-up rounded-2xl p-5">
                {tweetUrl ? (
                  <a
                    href={tweetUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-sm font-medium text-sky-300 hover:text-sky-200"
                  >
                    🐦 Posted to X — View tweet ↗
                  </a>
                ) : composerOpen ? (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <p className="text-[11px] font-medium uppercase tracking-widest text-neutral-500">
                        Compose tweet
                      </p>
                      {captionLoading ? (
                        <span className="flex items-center gap-1.5 text-xs font-medium text-sky-300">
                          <Spinner /> ✨ AI is writing a caption…
                        </span>
                      ) : (
                        <span className={`text-xs ${caption.length > 280 ? "text-red-400" : "text-neutral-600"}`}>
                          {caption.length}/280
                        </span>
                      )}
                    </div>
                    <div className="relative">
                      <textarea
                        value={caption}
                        onChange={(e) => setCaption(e.target.value)}
                        rows={3}
                        disabled={captionLoading}
                        placeholder={captionLoading ? "" : "What should the tweet say?"}
                        className="w-full resize-none rounded-xl border border-[var(--border)] bg-black/30 p-3 text-sm outline-none transition placeholder:text-neutral-600 focus:border-sky-500/60 disabled:opacity-60"
                      />
                      {captionLoading && (
                        <div className="pointer-events-none absolute inset-0 flex items-center justify-center gap-2 rounded-xl bg-black/20 text-sm text-sky-300">
                          <Spinner /> Generating caption with Claude…
                        </div>
                      )}
                    </div>
                    {publishErr && <p className="text-xs text-red-400">{publishErr}</p>}
                    <div className="flex gap-2">
                      <button
                        onClick={publish}
                        disabled={publishing || captionLoading || !caption.trim() || caption.length > 280}
                        className="flex items-center gap-1.5 rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-400 disabled:opacity-40"
                      >
                        {publishing ? <Spinner /> : "🐦"} Publish to X
                      </button>
                      <button
                        onClick={() => setComposerOpen(false)}
                        className="rounded-xl border border-[var(--border-strong)] px-4 py-2 text-sm text-neutral-300 transition hover:bg-white/5"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={openComposer}
                    className="flex w-full items-center justify-center gap-2 rounded-xl border border-sky-500/30 bg-sky-500/10 py-2.5 text-sm font-medium text-sky-300 transition hover:bg-sky-500/20"
                  >
                    🐦 Post to X
                  </button>
                )}
              </div>
            )}

            {/* Iterations / variations filmstrip */}
            {results.length > 1 && (
              <div className="panel rounded-2xl p-5">
                <p className="mb-3 text-[11px] font-medium uppercase tracking-widest text-neutral-500">
                  {mode === "ad" ? "Variations — pick your favorite" : "Iterations"}
                </p>
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {results.map((r) => (
                    <button
                      key={r.iteration}
                      onClick={() => selectResult(r)}
                      className={`relative shrink-0 overflow-hidden rounded-lg border transition ${
                        image === r.imageUrl
                          ? "border-violet-500"
                          : "border-[var(--border)] hover:border-[var(--border-strong)]"
                      }`}
                    >
                      <img src={r.imageUrl} alt={`iteration ${r.iteration}`} className="h-16 w-16 object-cover" />
                      <span className="absolute bottom-0 right-0 bg-black/70 px-1 text-[10px] text-neutral-200">
                        {r.score}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
      )}
    </main>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function PipelineNode({
  node,
  state,
}: {
  node: { key: NodeKey; label: string; sub: string; icon: ReactElement };
  state: NodeVisual;
}) {
  const ring =
    state === "active"
      ? "border-violet-500/70 bg-violet-500/10 animate-node-glow"
      : state === "done"
      ? "border-emerald-500/40 bg-emerald-500/5"
      : state === "approved"
      ? "border-emerald-500/60 bg-emerald-500/15"
      : state === "rejected"
      ? "border-red-500/50 bg-red-500/10"
      : state === "pending"
      ? "border-[var(--border)] bg-transparent opacity-50"
      : "border-[var(--border)] bg-transparent opacity-70";

  const iconColor =
    state === "active"
      ? "text-violet-300"
      : state === "done" || state === "approved"
      ? "text-emerald-300"
      : state === "rejected"
      ? "text-red-300"
      : "text-neutral-500";

  return (
    <div className="flex min-w-[64px] flex-1 flex-col items-center gap-1.5 text-center">
      <div
        className={`flex h-12 w-12 items-center justify-center rounded-xl border transition-all duration-300 ${ring} ${iconColor}`}
      >
        {state === "done" || state === "approved" ? <IconCheck /> : node.icon}
      </div>
      <div className="leading-tight">
        <p
          className={`text-[11px] font-medium ${
            state === "pending" || state === "idle" ? "text-neutral-600" : "text-neutral-200"
          }`}
        >
          {node.label}
        </p>
        <p className="text-[9px] text-neutral-600">{node.sub}</p>
      </div>
    </div>
  );
}

function Edge({ active }: { active: boolean }) {
  return (
    <div className="relative mb-6 h-[2px] min-w-[12px] flex-1 overflow-hidden rounded-full bg-white/10">
      {active && <div className="edge-flow absolute inset-0" />}
    </div>
  );
}

function StatusChip({ status }: { status: AppStatus }) {
  const map: Record<AppStatus, { label: string; cls: string; dot: string }> = {
    idle: { label: "Ready", cls: "text-neutral-400 border-[var(--border)]", dot: "bg-neutral-500" },
    running: { label: "Generating", cls: "text-violet-300 border-violet-500/30 bg-violet-500/10", dot: "bg-violet-400 animate-pulse" },
    paused: { label: "Awaiting approval", cls: "text-amber-300 border-amber-500/30 bg-amber-500/10", dot: "bg-amber-400 animate-pulse" },
    approved: { label: "Approved", cls: "text-emerald-300 border-emerald-500/30 bg-emerald-500/10", dot: "bg-emerald-400" },
    rejected: { label: "Rejected", cls: "text-red-300 border-red-500/30 bg-red-500/10", dot: "bg-red-400" },
    error: { label: "Error", cls: "text-red-300 border-red-500/30 bg-red-500/10", dot: "bg-red-400" },
  };
  const s = map[status];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${s.cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

function scoreColor(score: number) {
  if (score >= 8) return { text: "text-emerald-300", ring: "#34d399", label: "Production ready" };
  if (score >= 5) return { text: "text-amber-300", ring: "#fbbf24", label: "Needs review" };
  return { text: "text-red-300", ring: "#f87171", label: "Low quality" };
}

function ScorePill({ score }: { score: number }) {
  const c = scoreColor(score);
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-black/60 px-3 py-1 text-xs font-semibold backdrop-blur ${c.text}`}>
      {score}/10 · {c.label}
    </span>
  );
}

function ScoreDonut({ score }: { score: number }) {
  const c = scoreColor(score);
  const r = 16;
  const circ = 2 * Math.PI * r;
  const off = circ * (1 - score / 10);
  return (
    <div className="relative h-12 w-12">
      <svg viewBox="0 0 40 40" className="h-12 w-12 -rotate-90">
        <circle cx="20" cy="20" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="4" />
        <circle
          cx="20"
          cy="20"
          r={r}
          fill="none"
          stroke={c.ring}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={off}
          style={{ transition: "stroke-dashoffset 0.6s ease" }}
        />
      </svg>
      <span className={`absolute inset-0 flex items-center justify-center text-sm font-semibold ${c.text}`}>
        {score}
      </span>
    </div>
  );
}

function EmptyState() {
  return (
    <section className="panel mt-5 flex flex-col items-center justify-center gap-4 rounded-2xl px-6 py-16 text-center">
      <div className="accent-grad flex h-12 w-12 items-center justify-center rounded-2xl opacity-90">
        <IconSpark />
      </div>
      <div>
        <p className="text-sm font-medium text-neutral-200">
          Upload a product, get an ad-ready post
        </p>
        <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-neutral-500">
          A creative-director agent stages your product into a scene, an Opus-vision quality gate
          scores it (looping until it&apos;s ad-ready or hits the cap), then it pauses for your
          approval — and one click ships it to X.
        </p>
      </div>
    </section>
  );
}

// ── Icons (inline, dependency-free) ───────────────────────────────────────────

function IconRoute() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="6" cy="19" r="2" /><circle cx="18" cy="5" r="2" />
      <path d="M8 19h6a3 3 0 0 0 3-3V8" />
    </svg>
  );
}
function IconSpark() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-white">
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />
    </svg>
  );
}
function IconImage() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="1.5" />
      <path d="m21 15-5-5L5 21" />
    </svg>
  );
}
function IconScan() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}
function IconUserCheck() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="8" r="4" /><path d="M2 21a7 7 0 0 1 13-3.5M16 11l2 2 4-4" />
    </svg>
  );
}
function IconCheck() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}
function IconPlay() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}
function IconUpload() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
    </svg>
  );
}
function Spinner({ big }: { big?: boolean }) {
  const s = big ? "h-7 w-7" : "h-4 w-4";
  return (
    <svg className={`${s} animate-spin`} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-20" />
      <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

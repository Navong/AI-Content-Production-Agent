"use client";

import { useState, useRef, useCallback } from "react";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ─────────────────────────────────────────────────────────────────

type AppStatus = "idle" | "running" | "paused" | "approved" | "rejected" | "error";

interface NodeEvent {
  iteration: number;
  node: "prompt_engineer" | "image_gen" | "quality_eval";
  detail?: string;
}

interface IterationResult {
  iteration: number;
  imageUrl: string;
  score: number;
  feedback: string;
}

// ── SSE parser ────────────────────────────────────────────────────────────

async function* parseSSE(response: Response) {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6));
        } catch {
          // skip malformed line
        }
      }
    }
  }
}

// ── Score badge ───────────────────────────────────────────────────────────

function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 8
      ? "bg-emerald-900 text-emerald-300 border-emerald-700"
      : score >= 5
      ? "bg-amber-900 text-amber-300 border-amber-700"
      : "bg-red-900 text-red-300 border-red-700";
  const label = score >= 8 ? "Production ready" : score >= 5 ? "Needs review" : "Low quality";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-medium ${color}`}>
      {score}/10 · {label}
    </span>
  );
}

// ── Node pill ─────────────────────────────────────────────────────────────

const NODE_LABELS: Record<string, string> = {
  prompt_engineer: "PromptEngineer",
  image_gen: "ImageGen",
  quality_eval: "QualityEval",
};

function NodePill({ node, detail }: { node: string; detail?: string }) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-800 text-xs text-emerald-200">
        ✓
      </span>
      <div>
        <span className="text-sm font-medium text-neutral-200">{NODE_LABELS[node] ?? node}</span>
        {detail && (
          <p className="mt-0.5 line-clamp-2 text-xs text-neutral-500">{detail}</p>
        )}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function Home() {
  const [brief, setBrief] = useState("");
  const [status, setStatus] = useState<AppStatus>("idle");
  const [threadId, setThreadId] = useState("");
  const [nodeEvents, setNodeEvents] = useState<NodeEvent[]>([]);
  const [currentImage, setCurrentImage] = useState("");
  const [currentScore, setCurrentScore] = useState(0);
  const [currentFeedback, setCurrentFeedback] = useState("");
  const [currentIteration, setCurrentIteration] = useState(0);
  const [results, setResults] = useState<IterationResult[]>([]);
  const [finalStatus, setFinalStatus] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  const abortRef = useRef<AbortController | null>(null);

  const pushNode = useCallback((evt: NodeEvent) => {
    setNodeEvents((prev) => [...prev, evt]);
  }, []);

  // ── consume SSE stream ──────────────────────────────────────────────────

  async function consumeStream(response: Response) {
    for await (const msg of parseSSE(response)) {
      switch (msg.event) {
        case "session":
          setThreadId(msg.thread_id);
          break;

        case "node_done":
          pushNode({
            iteration: msg.iteration ?? 0,
            node: msg.node,
            detail: msg.prompt ? msg.prompt.slice(0, 100) + "…" : undefined,
          });
          break;

        case "image_ready":
          setCurrentImage(msg.url);
          pushNode({ iteration: currentIteration, node: "image_gen" });
          break;

        case "score_ready":
          setCurrentScore(msg.score);
          setCurrentFeedback(msg.feedback ?? "");
          pushNode({
            iteration: currentIteration,
            node: "quality_eval",
            detail: `${msg.score}/10`,
          });
          setResults((prev) => {
            const existing = prev.findIndex((r) => r.iteration === currentIteration);
            const entry: IterationResult = {
              iteration: currentIteration,
              imageUrl: currentImage,
              score: msg.score,
              feedback: msg.feedback ?? "",
            };
            if (existing >= 0) {
              const next = [...prev];
              next[existing] = entry;
              return next;
            }
            return [...prev, entry];
          });
          break;

        case "awaiting_approval":
          setCurrentImage(msg.image_url);
          setCurrentScore(msg.score);
          setCurrentIteration(msg.iteration ?? 0);
          setStatus("paused");
          break;

        case "done":
          setFinalStatus(msg.status ?? "done");
          setStatus(msg.status === "approved" ? "approved" : "rejected");
          break;

        case "error":
          setErrorMsg(msg.message ?? "Unknown error");
          setStatus("error");
          break;
      }
    }
  }

  // ── generate ────────────────────────────────────────────────────────────

  async function onGenerate() {
    if (!brief.trim()) return;
    abortRef.current?.abort();
    abortRef.current = new AbortController();

    setStatus("running");
    setNodeEvents([]);
    setCurrentImage("");
    setCurrentScore(0);
    setCurrentFeedback("");
    setCurrentIteration(0);
    setResults([]);
    setFinalStatus("");
    setErrorMsg("");

    try {
      const res = await fetch(`${API_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brief }),
        signal: abortRef.current.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await consumeStream(res);
    } catch (e: unknown) {
      if (e instanceof Error && e.name !== "AbortError") {
        setErrorMsg(e.message);
        setStatus("error");
      }
    }
  }

  // ── approve / reject / regenerate ───────────────────────────────────────

  async function onAction(action: "approve" | "reject" | "regenerate") {
    if (action === "regenerate") {
      // Start a brand-new run with the same brief
      return onGenerate();
    }

    try {
      const res = await fetch(`${API_URL}/api/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId, action }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await consumeStream(res);
    } catch (e: unknown) {
      if (e instanceof Error) {
        setErrorMsg(e.message);
        setStatus("error");
      }
    }
  }

  // ── group events by iteration ────────────────────────────────────────────

  const iterations = Array.from(new Set(nodeEvents.map((e) => e.iteration))).sort();

  // ── render ───────────────────────────────────────────────────────────────

  return (
    <main className="flex min-h-screen flex-col bg-neutral-950 text-neutral-100">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-neutral-800 px-8 py-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">AI Content Production Agent</h1>
          <p className="text-xs text-neutral-500">
            Brief → prompt engineering → image generation → quality scoring → human approval
          </p>
        </div>
        <Link
          href="/dashboard"
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-lg border border-neutral-700 px-4 py-2 text-sm transition hover:border-neutral-500"
        >
          Dashboard ↗
        </Link>
      </header>

      <div className="flex flex-1 gap-0">
        {/* ── Left: input panel ── */}
        <aside className="flex w-80 shrink-0 flex-col gap-4 border-r border-neutral-800 p-6">
          <label className="text-xs font-medium uppercase tracking-widest text-neutral-500">
            Creative brief
          </label>
          <textarea
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            placeholder="Describe your content brief…"
            rows={8}
            className="resize-none rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-sm outline-none focus:border-neutral-600 disabled:opacity-50"
            disabled={status === "running"}
          />

          <button
            onClick={onGenerate}
            disabled={!brief.trim() || status === "running"}
            className="rounded-lg bg-emerald-600 py-2.5 text-sm font-medium transition hover:bg-emerald-500 disabled:opacity-40"
          >
            {status === "running" ? "Generating…" : "Generate"}
          </button>

          {/* Demo briefs */}
          <div className="mt-2 space-y-1">
            <p className="text-xs text-neutral-600">Demo briefs:</p>
            {[
              "K-pop idol portrait, dreamy pastel background, ultra-detailed, studio lighting",
              "something cool for a fashion brand",
              "make a good picture",
            ].map((b) => (
              <button
                key={b}
                onClick={() => setBrief(b)}
                className="block w-full truncate rounded px-2 py-1 text-left text-xs text-neutral-500 transition hover:bg-neutral-800 hover:text-neutral-300"
              >
                {b}
              </button>
            ))}
          </div>
        </aside>

        {/* ── Right: live progress + output ── */}
        <section className="flex flex-1 flex-col gap-6 overflow-auto p-6">
          {status === "idle" && (
            <div className="flex flex-1 items-center justify-center text-neutral-700">
              Enter a brief and hit Generate to start.
            </div>
          )}

          {status === "error" && (
            <div className="rounded-lg border border-red-800 bg-red-950 p-4 text-sm text-red-300">
              Error: {errorMsg}
            </div>
          )}

          {status !== "idle" && status !== "error" && (
            <div className="flex flex-col gap-6 lg:flex-row">
              {/* Progress timeline */}
              <div className="w-full space-y-4 lg:w-64 lg:shrink-0">
                <h2 className="text-xs font-medium uppercase tracking-widest text-neutral-500">
                  Progress
                </h2>

                {iterations.map((iter) => (
                  <div key={iter} className="space-y-2">
                    <p className="text-xs text-neutral-600">Iteration {iter}</p>
                    <div className="space-y-2 border-l border-neutral-800 pl-3">
                      {nodeEvents
                        .filter((e) => e.iteration === iter)
                        .map((e, i) => (
                          <NodePill key={i} node={e.node} detail={e.detail} />
                        ))}
                    </div>
                  </div>
                ))}

                {status === "running" && (
                  <div className="flex items-center gap-2 text-xs text-neutral-500">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                    Running…
                  </div>
                )}
              </div>

              {/* Image + controls */}
              <div className="flex flex-1 flex-col gap-4">
                {currentImage && (
                  <img
                    src={currentImage}
                    alt="Generated content"
                    className="max-h-[480px] w-full rounded-xl object-contain"
                  />
                )}

                {currentScore > 0 && <ScoreBadge score={currentScore} />}

                {currentFeedback && (
                  <p className="rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-xs leading-relaxed text-neutral-400">
                    {currentFeedback.split("\n\nSuggested fix:")[0]}
                  </p>
                )}

                {/* HITL controls */}
                {status === "paused" && (
                  <div className="flex gap-3">
                    <button
                      onClick={() => onAction("approve")}
                      className="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-medium transition hover:bg-emerald-500"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => onAction("regenerate")}
                      className="rounded-lg border border-neutral-700 px-5 py-2.5 text-sm font-medium transition hover:border-neutral-500 hover:bg-neutral-800"
                    >
                      Regenerate
                    </button>
                    <button
                      onClick={() => onAction("reject")}
                      className="rounded-lg px-5 py-2.5 text-sm font-medium text-neutral-500 transition hover:text-red-400"
                    >
                      Reject
                    </button>
                  </div>
                )}

                {/* Final state banner */}
                {(status === "approved" || status === "rejected") && (
                  <div
                    className={`rounded-lg border px-4 py-3 text-sm font-medium ${
                      status === "approved"
                        ? "border-emerald-800 bg-emerald-950 text-emerald-300"
                        : "border-red-800 bg-red-950 text-red-300"
                    }`}
                  >
                    {status === "approved"
                      ? "Approved — image package ready for delivery."
                      : "Rejected."}
                  </div>
                )}

                {/* Iteration history strip */}
                {results.length > 1 && (
                  <div className="mt-2">
                    <p className="mb-2 text-xs text-neutral-600">All iterations</p>
                    <div className="flex gap-2 overflow-x-auto pb-2">
                      {results.map((r) => (
                        <div
                          key={r.iteration}
                          className="shrink-0 cursor-pointer space-y-1"
                          onClick={() => {
                            setCurrentImage(r.imageUrl);
                            setCurrentScore(r.score);
                            setCurrentFeedback(r.feedback);
                          }}
                        >
                          <img
                            src={r.imageUrl}
                            alt={`iter ${r.iteration}`}
                            className="h-20 w-20 rounded-lg object-cover"
                          />
                          <ScoreBadge score={r.score} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

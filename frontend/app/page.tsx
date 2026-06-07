"use client";

import { useState } from "react";

export default function Home() {
  const [brief, setBrief] = useState("");

  // TODO(day4): POST /api/generate and consume the SSE stream (node events,
  // image_ready, score_ready, awaiting_approval, done). For now the form just
  // captures the brief.
  function onGenerate() {
    console.log("brief:", brief);
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-neutral-950 p-8 text-neutral-100">
      <div className="w-full max-w-2xl space-y-6">
        <header className="space-y-1">
          <h1 className="text-2xl font-semibold">AI Content Production Agent</h1>
          <p className="text-sm text-neutral-400">
            Brief in → prompt → image → quality score → human approval. Every run
            traced in LangSmith.
          </p>
        </header>

        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          placeholder="Describe your content brief…"
          className="h-40 w-full resize-none rounded-lg border border-neutral-800 bg-neutral-900 p-4 outline-none focus:border-neutral-600"
        />

        <button
          onClick={onGenerate}
          disabled={!brief.trim()}
          className="rounded-lg bg-emerald-600 px-5 py-2.5 font-medium transition hover:bg-emerald-500 disabled:opacity-40"
        >
          Generate
        </button>
      </div>
    </main>
  );
}

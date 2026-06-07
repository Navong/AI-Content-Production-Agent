"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

interface Run {
  thread_id: string;
  brief: string;
  brief_length: number;
  final_score: number;
  iterations_used: number;
  status: string;
  timestamp: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────

function scoreColor(score: number) {
  if (score >= 8) return "text-emerald-400";
  if (score >= 5) return "text-amber-400";
  return "text-red-400";
}

function statusBadge(status: string) {
  const base = "rounded-full px-2 py-0.5 text-xs font-medium";
  if (status === "approved") return `${base} bg-emerald-900 text-emerald-300`;
  if (status === "rejected") return `${base} bg-red-900 text-red-300`;
  return `${base} bg-neutral-800 text-neutral-400`;
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// ── Score distribution bar chart (CSS only) ────────────────────────────────

function ScoreChart({ runs }: { runs: Run[] }) {
  const buckets: Record<number, number> = {};
  for (let i = 1; i <= 10; i++) buckets[i] = 0;
  runs.forEach((r) => {
    const s = Math.min(10, Math.max(1, r.final_score));
    buckets[s] = (buckets[s] ?? 0) + 1;
  });
  const max = Math.max(...Object.values(buckets), 1);

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900 p-5">
      <h2 className="mb-4 text-xs font-medium uppercase tracking-widest text-neutral-500">
        Score distribution
      </h2>
      <div className="flex h-28 items-end gap-1.5">
        {Array.from({ length: 10 }, (_, i) => i + 1).map((s) => {
          const count = buckets[s] ?? 0;
          const pct = Math.round((count / max) * 100);
          const color =
            s >= 8 ? "bg-emerald-600" : s >= 5 ? "bg-amber-600" : "bg-red-700";
          return (
            <div key={s} className="flex flex-1 flex-col items-center gap-1">
              <span className="text-xs text-neutral-600">{count || ""}</span>
              <div
                className={`w-full rounded-t ${color} transition-all`}
                style={{ height: `${pct}%`, minHeight: count ? 4 : 0 }}
              />
              <span className="text-xs text-neutral-600">{s}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main ───────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`${API_URL}/api/runs?limit=50`)
      .then((r) => r.json())
      .then((data: Run[]) => { setRuns(data); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  }, []);

  const approved = runs.filter((r) => r.status === "approved");
  const avgScore =
    runs.length > 0
      ? (runs.reduce((s, r) => s + r.final_score, 0) / runs.length).toFixed(1)
      : "—";
  const approvalRate =
    runs.length > 0 ? Math.round((approved.length / runs.length) * 100) : 0;
  const avgIterations =
    runs.length > 0
      ? (runs.reduce((s, r) => s + r.iterations_used, 0) / runs.length).toFixed(1)
      : "—";

  return (
    <main className="min-h-screen bg-neutral-950 p-8 text-neutral-100">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Run Dashboard</h1>
          <p className="text-sm text-neutral-500">
            AI Content Production Agent · observability
          </p>
        </div>
        <Link
          href="/"
          className="rounded-lg border border-neutral-700 px-4 py-2 text-sm transition hover:border-neutral-500"
        >
          ← Back to generator
        </Link>
      </div>

      {loading && (
        <p className="text-neutral-600">Loading runs…</p>
      )}
      {error && (
        <p className="text-red-400">Error: {error}</p>
      )}

      {!loading && !error && (
        <div className="space-y-6">
          {/* Stats row */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { label: "Total runs", value: runs.length },
              { label: "Avg quality score", value: avgScore },
              { label: "Approval rate", value: `${approvalRate}%` },
              { label: "Avg iterations", value: avgIterations },
            ].map(({ label, value }) => (
              <div
                key={label}
                className="rounded-xl border border-neutral-800 bg-neutral-900 p-4"
              >
                <p className="text-xs text-neutral-500">{label}</p>
                <p className="mt-1 text-2xl font-semibold">{value}</p>
              </div>
            ))}
          </div>

          {/* Chart */}
          {runs.length > 0 && <ScoreChart runs={runs} />}

          {/* Runs table */}
          <div className="rounded-xl border border-neutral-800 bg-neutral-900">
            <div className="border-b border-neutral-800 px-5 py-3">
              <h2 className="text-xs font-medium uppercase tracking-widest text-neutral-500">
                Recent runs
              </h2>
            </div>

            {runs.length === 0 ? (
              <p className="p-5 text-sm text-neutral-600">
                No runs yet — go generate something!
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-neutral-800 text-xs text-neutral-500">
                    <th className="px-5 py-2 text-left font-medium">Brief</th>
                    <th className="px-4 py-2 text-left font-medium">Score</th>
                    <th className="px-4 py-2 text-left font-medium">Iterations</th>
                    <th className="px-4 py-2 text-left font-medium">Status</th>
                    <th className="px-5 py-2 text-left font-medium">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr
                      key={r.thread_id}
                      className="border-b border-neutral-800/60 last:border-0 hover:bg-neutral-800/40"
                    >
                      <td className="max-w-xs truncate px-5 py-3 text-neutral-300">
                        {r.brief || "—"}
                      </td>
                      <td className={`px-4 py-3 font-semibold ${scoreColor(r.final_score)}`}>
                        {r.final_score}/10
                      </td>
                      <td className="px-4 py-3 text-neutral-400">{r.iterations_used}</td>
                      <td className="px-4 py-3">
                        <span className={statusBadge(r.status)}>{r.status}</span>
                      </td>
                      <td className="whitespace-nowrap px-5 py-3 text-neutral-600">
                        {fmtDate(r.timestamp)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </main>
  );
}

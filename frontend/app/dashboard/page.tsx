"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Run {
  thread_id: string;
  brief: string;
  mode: string;
  status: string;
  score: number;
  iterations: number;
  image: string;
  published_url: string;
  timestamp: string;
}

type Filter = "all" | "approved" | "published" | "pending";

function scoreColor(s: number) {
  if (s >= 8) return "text-emerald-300";
  if (s >= 5) return "text-amber-300";
  return "text-red-300";
}

function statusStyle(status: string) {
  switch (status) {
    case "approved":
      return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
    case "rejected":
      return "bg-red-500/15 text-red-300 border-red-500/30";
    case "regenerated":
      return "bg-violet-500/15 text-violet-300 border-violet-500/30";
    case "awaiting_approval":
      return "bg-amber-500/15 text-amber-300 border-amber-500/30";
    default:
      return "bg-white/10 text-neutral-300 border-[var(--border)]";
  }
}

function statusLabel(status: string) {
  return status === "awaiting_approval" ? "pending" : status || "—";
}

function fmtDate(iso: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Dashboard() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    fetch(`${API_URL}/api/runs?limit=60`)
      .then((r) => r.json())
      .then((data: Run[]) => {
        setRuns(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  const stats = useMemo(() => {
    const approved = runs.filter((r) => r.status === "approved");
    const published = runs.filter((r) => r.published_url);
    const scored = runs.filter((r) => r.score > 0);
    const ads = runs.filter((r) => r.mode === "ad");
    const avg =
      scored.length > 0
        ? (scored.reduce((s, r) => s + r.score, 0) / scored.length).toFixed(1)
        : "—";
    return {
      total: runs.length,
      approved: approved.length,
      published: published.length,
      avg,
      ads: ads.length,
      approvalRate: runs.length ? Math.round((approved.length / runs.length) * 100) : 0,
    };
  }, [runs]);

  const filtered = useMemo(() => {
    if (filter === "approved") return runs.filter((r) => r.status === "approved");
    if (filter === "published") return runs.filter((r) => r.published_url);
    if (filter === "pending") return runs.filter((r) => r.status === "awaiting_approval");
    return runs;
  }, [runs, filter]);

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col px-5 pb-24 sm:px-8">
      {/* Header */}
      <header className="sticky top-0 z-20 -mx-5 mb-8 flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg)]/70 px-5 py-4 backdrop-blur-xl sm:-mx-8 sm:px-8">
        <div className="flex items-center gap-3">
          <div className="accent-grad flex h-9 w-9 items-center justify-center rounded-xl text-white shadow-lg shadow-violet-500/20">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" />
              <rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" />
            </svg>
          </div>
          <div className="leading-tight">
            <h1 className="text-[15px] font-semibold tracking-tight">Production Dashboard</h1>
            <p className="text-[11px] text-neutral-500">Every run, durable · stored in R2</p>
          </div>
        </div>
        <Link
          href="/"
          className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs text-neutral-300 transition hover:border-[var(--border-strong)] hover:bg-white/5"
        >
          ← Studio
        </Link>
      </header>

      {loading && <p className="text-neutral-600">Loading runs…</p>}
      {error && <p className="text-red-400">Error: {error}</p>}

      {!loading && !error && (
        <>
          {/* Stats */}
          <section className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
            <Stat label="Runs" value={stats.total} />
            <Stat label="Ads produced" value={stats.ads} />
            <Stat label="Approved" value={stats.approved} sub={`${stats.approvalRate}%`} />
            <Stat label="Published to X" value={stats.published} accent="text-sky-300" />
            <Stat label="Avg score" value={`${stats.avg}`} accent={scoreColor(Number(stats.avg) || 0)} />
          </section>

          {/* Filters */}
          <div className="mt-6 flex flex-wrap gap-2">
            {([
              ["all", "All"],
              ["approved", "Approved"],
              ["published", "Published"],
              ["pending", "Pending review"],
            ] as [Filter, string][]).map(([f, label]) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                  filter === f
                    ? "border-violet-500/50 bg-violet-500/15 text-violet-200"
                    : "border-[var(--border)] text-neutral-400 hover:text-neutral-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Gallery */}
          {filtered.length === 0 ? (
            <div className="panel mt-6 rounded-2xl px-6 py-16 text-center text-sm text-neutral-500">
              {runs.length === 0
                ? "No runs yet — go produce an ad in the studio."
                : "Nothing matches this filter."}
            </div>
          ) : (
            <section className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
              {filtered.map((r) => (
                <RunCard key={r.thread_id} run={r} />
              ))}
            </section>
          )}
        </>
      )}
    </main>
  );
}

function Stat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="panel rounded-2xl p-4">
      <p className="text-[11px] uppercase tracking-wider text-neutral-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${accent ?? "text-neutral-100"}`}>
        {value}
        {sub && <span className="ml-1.5 text-xs font-normal text-neutral-500">{sub}</span>}
      </p>
    </div>
  );
}

function RunCard({ run }: { run: Run }) {
  return (
    <div className="panel group overflow-hidden rounded-2xl">
      <div className="relative aspect-square bg-black/40">
        {run.image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={run.image} alt={run.brief} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-xs text-neutral-700">
            no image
          </div>
        )}
        <span
          className={`absolute left-2 top-2 rounded-full border px-2 py-0.5 text-[10px] font-medium capitalize backdrop-blur ${statusStyle(
            run.status
          )}`}
        >
          {statusLabel(run.status)}
        </span>
        {run.score > 0 && (
          <span
            className={`absolute right-2 top-2 rounded-full border border-white/10 bg-black/60 px-2 py-0.5 text-[10px] font-semibold backdrop-blur ${scoreColor(
              run.score
            )}`}
          >
            {run.score}/10
          </span>
        )}
        <span className="absolute bottom-2 left-2 rounded-full bg-black/60 px-2 py-0.5 text-[10px] text-neutral-300 backdrop-blur">
          {run.mode === "ad" ? "📦 Ad" : "✏️ Text"}
        </span>
      </div>
      <div className="p-3">
        <p className="line-clamp-2 min-h-[2.5rem] text-xs leading-relaxed text-neutral-300">
          {run.brief || "—"}
        </p>
        <div className="mt-2 flex items-center justify-between text-[10px] text-neutral-600">
          <span>{fmtDate(run.timestamp)}</span>
          <div className="flex items-center gap-2">
            {run.published_url && (
              <a
                href={run.published_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sky-400 hover:text-sky-300"
              >
                🐦 tweet
              </a>
            )}
            <Link
              href={`/?thread=${run.thread_id}`}
              className="text-violet-400 hover:text-violet-300"
            >
              open ↗
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

"use client";

import {
  createContext,
  useContext,
  useState,
  useRef,
  useEffect,
  type ReactNode,
} from "react";
import Link from "next/link";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type AppStatus =
  | "idle"
  | "running"
  | "paused"
  | "approved"
  | "rejected"
  | "error";

export type NodeKey =
  | "supervisor"
  | "prompt_engineer"
  | "image_gen"
  | "quality_eval"
  | "hitl_gate";

export interface IterationResult {
  iteration: number;
  imageUrl: string;
  score: number;
  feedback: string;
}

type Toast = { title: string; body: string; kind: "ready" | "approved" | "rejected" | "error" } | null;

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
          /* skip keepalive / malformed */
        }
      }
    }
  }
}

// The whole generation engine, lifted out of the page so it keeps running while
// the user navigates between the studio and the dashboard (it lives in the
// layout). Fires a toast + browser notification when a run finishes.
function useEngine() {
  const [brief, setBrief] = useState("");
  const [status, setStatus] = useState<AppStatus>("idle");
  const [, setThreadId] = useState("");
  const [activeNode, setActiveNode] = useState<NodeKey | null>(null);
  const [iteration, setIteration] = useState(0);
  const [image, setImage] = useState("");
  const [score, setScore] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [results, setResults] = useState<IterationResult[]>([]);
  const [errorMsg, setErrorMsg] = useState("");
  const [notice, setNotice] = useState("");
  const [mode, setMode] = useState<"ad" | "text">("ad");
  const [productImage, setProductImage] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadErr, setUploadErr] = useState("");
  const [composerOpen, setComposerOpen] = useState(false);
  const [caption, setCaption] = useState("");
  const [captionLoading, setCaptionLoading] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [tweetUrl, setTweetUrl] = useState("");
  const [publishErr, setPublishErr] = useState("");
  const [xEnabled, setXEnabled] = useState(false);
  const [toast, setToast] = useState<Toast>(null);

  const abortRef = useRef<AbortController | null>(null);
  const iterRef = useRef(0);
  const imageRef = useRef("");
  const threadRef = useRef("");
  const resultsRef = useRef<IterationResult[]>([]);
  const scoreRef = useRef(0);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function dismissToast() {
    setToast(null);
  }

  function notify(t: NonNullable<Toast>) {
    setToast(t);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 9000);
    try {
      if (
        typeof Notification !== "undefined" &&
        Notification.permission === "granted" &&
        typeof document !== "undefined" &&
        document.hidden
      ) {
        new Notification(t.title, { body: t.body });
      }
    } catch {
      /* notifications unsupported / blocked */
    }
  }

  // Deep link from Slack's "Review in app" button.
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("thread");
    if (!t) return;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/session/${t}`);
        if (res.status === 404) {
          setNotice("That review link has expired — the run is no longer available.");
          return;
        }
        if (!res.ok) return;
        const s = await res.json();
        threadRef.current = t;
        setBrief(s.brief ?? "");
        scoreRef.current = s.score ?? 0;
        setScore(s.score ?? 0);
        setFeedback(s.feedback ?? "");
        setIteration(s.iteration ?? 0);
        if (s.image) {
          imageRef.current = s.image;
          setImage(s.image);
        }
        if (s.status === "awaiting_approval") {
          setActiveNode("hitl_gate");
          setStatus("paused");
        } else if (s.status === "approved" || s.status === "rejected") {
          setStatus(s.status);
        }
      } catch {
        /* leave idle */
      }
    })();
  }, []);

  useEffect(() => {
    fetch(`${API_URL}/api/config`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setXEnabled(!!d.x_enabled))
      .catch(() => {});
  }, []);

  // Poll while paused so a decision made elsewhere reflects here.
  useEffect(() => {
    if (status !== "paused") return;
    const id = setInterval(async () => {
      const t = threadRef.current;
      if (!t) return;
      try {
        const res = await fetch(`${API_URL}/api/session/${t}`);
        if (!res.ok) return;
        const s = await res.json();
        if (s.status === "approved" || s.status === "rejected") setStatus(s.status);
      } catch {
        /* keep polling */
      }
    }, 3000);
    return () => clearInterval(id);
  }, [status]);

  function recordResult(iter: number, img: string, sc: number, fb: string) {
    setResults((prev) => {
      const idx = prev.findIndex((r) => r.iteration === iter);
      const entry: IterationResult = { iteration: iter, imageUrl: img, score: sc, feedback: fb };
      const next = idx >= 0 ? prev.map((r, i) => (i === idx ? entry : r)) : [...prev, entry];
      resultsRef.current = next;
      return next;
    });
  }

  function selectResult(r: IterationResult) {
    imageRef.current = r.imageUrl;
    scoreRef.current = r.score;
    setImage(r.imageUrl);
    setScore(r.score);
    setFeedback(r.feedback);
  }

  async function consumeStream(response: Response) {
    for await (const msg of parseSSE(response)) {
      switch (msg.event) {
        case "session":
          threadRef.current = msg.thread_id;
          setThreadId(msg.thread_id);
          break;
        case "node_done":
          iterRef.current = msg.iteration ?? 0;
          setIteration(iterRef.current);
          setActiveNode("image_gen");
          break;
        case "image_ready":
          imageRef.current = msg.url;
          setImage(msg.url);
          setActiveNode("quality_eval");
          break;
        case "score_ready":
          scoreRef.current = msg.score;
          setScore(msg.score);
          setFeedback(msg.feedback ?? "");
          recordResult(iterRef.current, imageRef.current, msg.score, msg.feedback ?? "");
          break;
        case "awaiting_approval": {
          setIteration(msg.iteration ?? 0);
          const all = resultsRef.current;
          const best = all.length ? all.reduce((a, b) => (b.score >= a.score ? b : a)) : null;
          if (best) {
            selectResult(best);
          } else {
            imageRef.current = msg.image_url;
            scoreRef.current = msg.score;
            setImage(msg.image_url);
            setScore(msg.score);
          }
          setActiveNode("hitl_gate");
          setStatus("paused");
          notify({
            title: "✨ Your content is ready to review",
            body: "Open the studio to approve or pick a variation.",
            kind: "ready",
          });
          break;
        }
        case "done":
          if (msg.status === "approved") {
            setStatus("approved");
            notify({ title: "✅ Approved", body: "Ready to publish.", kind: "approved" });
          } else {
            setStatus("rejected");
            notify({ title: "Rejected", body: "Run closed.", kind: "rejected" });
          }
          break;
        case "error":
          setErrorMsg(msg.message ?? "Unknown error");
          setStatus("error");
          notify({ title: "Generation failed", body: msg.message ?? "Unknown error", kind: "error" });
          break;
      }
    }
  }

  async function onUpload(file: File) {
    setUploading(true);
    setUploadErr("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${API_URL}/api/upload`, { method: "POST", body: fd });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail ?? `HTTP ${res.status}`);
      }
      const d = await res.json();
      setProductImage(d.url ?? "");
    } catch (e: unknown) {
      setUploadErr(e instanceof Error ? e.message : "upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function onGenerate() {
    if (!brief.trim()) return;
    if (mode === "ad" && !productImage) return;
    abortRef.current?.abort();
    abortRef.current = new AbortController();

    // ask for notification permission so we can ping when it's done in the bg
    try {
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        Notification.requestPermission();
      }
    } catch {
      /* ignore */
    }

    threadRef.current = "";
    resultsRef.current = [];
    scoreRef.current = 0;
    if (typeof window !== "undefined" && window.location.search) {
      window.history.replaceState(null, "", window.location.pathname);
    }

    setStatus("running");
    setActiveNode("prompt_engineer");
    setIteration(0);
    setImage("");
    setScore(0);
    setFeedback("");
    setResults([]);
    setErrorMsg("");
    setNotice("");
    setComposerOpen(false);
    setCaption("");
    setTweetUrl("");
    setPublishErr("");
    setToast(null);
    iterRef.current = 0;
    imageRef.current = "";

    try {
      const res = await fetch(`${API_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          mode === "ad"
            ? { brief, mode: "ad", product_image_url: productImage }
            : { brief, mode: "text" }
        ),
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

  async function onAction(action: "approve" | "reject" | "regenerate") {
    if (action === "regenerate") {
      const old = threadRef.current;
      if (old) {
        try {
          await fetch(`${API_URL}/api/approve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ thread_id: old, action: "regenerate", reviewer: "Studio" }),
          }).then((r) => r.text());
        } catch {
          /* non-fatal */
        }
      }
      return onGenerate();
    }
    setStatus("running");
    setActiveNode("hitl_gate");
    try {
      const res = await fetch(`${API_URL}/api/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          thread_id: threadRef.current,
          action,
          reviewer: "Studio",
          image: imageRef.current,
          score: scoreRef.current,
        }),
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

  async function openComposer() {
    setComposerOpen(true);
    setPublishErr("");
    if (!caption) {
      setCaptionLoading(true);
      try {
        const res = await fetch(`${API_URL}/api/caption`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ thread_id: threadRef.current }),
        });
        if (res.ok) {
          const d = await res.json();
          setCaption(d.caption ?? "");
        }
      } catch {
        /* manual entry */
      } finally {
        setCaptionLoading(false);
      }
    }
  }

  async function publish() {
    setPublishing(true);
    setPublishErr("");
    try {
      const res = await fetch(`${API_URL}/api/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadRef.current, image: imageRef.current, caption }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail ?? `HTTP ${res.status}`);
      }
      const d = await res.json();
      setTweetUrl(d.url ?? "");
      setComposerOpen(false);
    } catch (e: unknown) {
      setPublishErr(e instanceof Error ? e.message : "Failed to post");
    } finally {
      setPublishing(false);
    }
  }

  return {
    brief, setBrief, status, activeNode, iteration, image, score, feedback,
    results, errorMsg, notice, setNotice, mode, setMode, productImage,
    uploading, uploadErr, composerOpen, setComposerOpen, caption, setCaption,
    captionLoading, publishing, tweetUrl, publishErr, xEnabled, fileRef,
    selectResult, onUpload, onGenerate, onAction, openComposer, publish,
    toast, dismissToast,
  };
}

type Engine = ReturnType<typeof useEngine>;
const Ctx = createContext<Engine | null>(null);

export function useGeneration(): Engine {
  const c = useContext(Ctx);
  if (!c) throw new Error("useGeneration must be used within GenerationProvider");
  return c;
}

export function GenerationProvider({ children }: { children: ReactNode }) {
  const engine = useEngine();
  return (
    <Ctx.Provider value={engine}>
      {children}
      <ToastView toast={engine.toast} onClose={engine.dismissToast} />
    </Ctx.Provider>
  );
}

function ToastView({ toast, onClose }: { toast: Toast; onClose: () => void }) {
  if (!toast) return null;
  const accent =
    toast.kind === "approved"
      ? "border-emerald-500/40"
      : toast.kind === "rejected" || toast.kind === "error"
      ? "border-red-500/40"
      : "border-violet-500/40";
  return (
    <div className="fixed bottom-5 right-5 z-50 w-[320px] animate-fade-up">
      <div className={`panel rounded-2xl border ${accent} p-4 shadow-2xl shadow-black/40`}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-neutral-100">{toast.title}</p>
            <p className="mt-0.5 text-xs text-neutral-400">{toast.body}</p>
          </div>
          <button onClick={onClose} className="text-neutral-500 transition hover:text-neutral-200">
            ✕
          </button>
        </div>
        {toast.kind === "ready" && (
          <Link
            href="/"
            onClick={onClose}
            className="accent-grad mt-3 block rounded-lg py-1.5 text-center text-xs font-medium text-white"
          >
            Review in studio →
          </Link>
        )}
      </div>
    </div>
  );
}

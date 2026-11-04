"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Mark } from "@/components/brand";

/** Three slides, one minute, then the live demo. Keys: right arrow / space = next, left arrow = back,
 * F = full screen, N = speaker notes (hidden by default so a recording is clean). */
const BYLINE = "Built for Build North · Ship something real";

type Slide = { title: string; seconds: number; say: string; body: ReactNode };

const NODES = ["Planner", "Researcher", "Writer", "Critic"];

function Solution() {
  return (
    <div className="flex flex-col gap-10">
      <svg viewBox="0 0 1000 285" role="img" aria-label="Four agents in a line. The planner is marked as the likely cause. Below it, runs without the fix: 0 of 8 right. Runs with the fix: 8 of 8 right." className="w-full">
        <path d="M80 50h840" stroke="var(--line)" strokeWidth="2.5" />
        {NODES.map((n, i) => (
          <g key={n} className="deck-in" style={{ animationDelay: `${i * 120}ms` }}>
            <circle cx={80 + i * 280} cy="50" r={i === 0 ? 24 : 17} fill={i === 0 ? "var(--bad-tint)" : "var(--sheet)"} stroke={i === 0 ? "var(--bad)" : "var(--muted)"} strokeWidth="2.5" />
            <text x={80 + i * 280} y="102" textAnchor="middle" fontSize="23" fill="var(--ink)">{n}</text>
          </g>
        ))}
        <text x="80" y="14" textAnchor="middle" fontSize="19" fill="var(--bad)">likely cause</text>
        <path d="M80 122v38" stroke="var(--muted)" strokeWidth="2" strokeDasharray="5 5" />
        {[0, 1].map((row) =>
          Array.from({ length: 8 }, (_, i) => (
            <circle
              key={`${row}-${i}`} cx={104 + i * 34} cy={row === 0 ? 176 : 232} r="12" className="deck-in"
              style={{ animationDelay: `${600 + (row === 0 ? 0 : 500) + i * 70}ms` }}
              fill={row === 0 ? "none" : "var(--good)"} stroke={row === 0 ? "var(--bad)" : "none"} strokeWidth="2.5"
            />
          )),
        )}
        <text x="400" y="184" fontSize="24" fill="var(--ink)">without the fix: <tspan fill="var(--bad)">0 of 8</tspan> right</text>
        <text x="400" y="240" fontSize="24" fill="var(--ink)">with the fix: <tspan fill="var(--good)">8 of 8</tspan> right</text>
        <text x="80" y="280" fontSize="17" fill="var(--muted)">the same fork point, run live eight times each way</text>
      </svg>
      <ol className="grid gap-8 sm:grid-cols-3">
        {[
          ["Record", "from the harness she already uses: LangGraph, a Python loop, or OpenTelemetry."],
          ["Test", "Fork the suspect step and rerun everything after it, live, with and without the fix."],
          ["Know", "The result lands in Slack, and a CI gate guards the fix from then on."],
        ].map(([head, text], i) => (
          <li key={head} className="deck-in" style={{ animationDelay: `${300 + i * 200}ms` }}>
            <p className="font-serif text-[1.875rem] leading-tight">{head}</p>
            <p className="mt-1 max-w-[32ch] text-[1.125rem] text-muted">{text}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}

const SLIDES: Slide[] = [
  {
    title: "AgentTrace",
    seconds: 12,
    say: "Hi, I'm [your name]. This is AgentTrace. It finds the step that broke your AI agents, and proves whether the fix works.",
    body: (
      <div className="flex flex-col items-start gap-8">
        <div className="deck-in flex items-center gap-5">
          <span className="origin-left scale-[2.4]"><Mark /></span>
        </div>
        <h1 className="deck-in font-serif text-[clamp(4rem,10vw,8rem)] leading-none tracking-tight" style={{ animationDelay: "150ms" }}>AgentTrace</h1>
        <p className="deck-in max-w-[24ch] font-serif text-[clamp(1.75rem,3.2vw,2.75rem)] leading-tight text-muted" style={{ animationDelay: "300ms" }}>
          Find the step that broke your agents. Prove the fix.
        </p>
        <p className="deck-in text-[1.0625rem] text-muted" style={{ animationDelay: "450ms" }}>{BYLINE}</p>
      </div>
    ),
  },
  {
    title: "Meet Maya",
    seconds: 26,
    say: "Meet Maya, an AI engineer. Her renewal-brief agents just told a customer there were zero open tickets. There were five. Her traces show what happened, not why. Re-running is noisy and costs tokens, so one lucky run proves nothing. And she can't move her whole team to a new framework.",
    body: (
      <div className="grid items-center gap-12 lg:grid-cols-[auto_1fr]">
        <div className="deck-in flex flex-col items-start gap-4">
          <span className="flex h-28 w-28 items-center justify-center rounded-full bg-tile font-serif text-[3.5rem]">M</span>
          <div>
            <p className="font-serif text-[2.5rem] leading-none">Maya</p>
            <p className="mt-2 text-[1.0625rem] text-muted">AI engineer · a composite persona</p>
          </div>
          <p className="max-w-[26ch] text-[0.9375rem] text-muted">Runs her agents on LangGraph and plain Python. Lives in Slack and CI.</p>
        </div>
        <div className="flex flex-col gap-9">
          <p className="deck-in font-serif text-[clamp(1.75rem,3.4vw,3rem)] leading-[1.15]" style={{ animationDelay: "200ms" }}>
            &ldquo;The brief says <span className="text-bad">zero</span> open tickets. There are five. Which of my four agents broke it?&rdquo;
          </p>
          <ul className="flex flex-col gap-4 text-[1.1875rem]">
            {[
              "Traces show what happened, not what caused it.",
              "Re-running is noisy and costs tokens. One lucky run proves nothing.",
              "She can't move her team to a new framework.",
            ].map((t, i) => (
              <li key={t} className="deck-in flex gap-3" style={{ animationDelay: `${500 + i * 250}ms` }}>
                <span aria-hidden className="mt-[0.7em] h-1.5 w-1.5 flex-none rounded-full bg-muted" />
                {t}
              </li>
            ))}
          </ul>
        </div>
      </div>
    ),
  },
  {
    title: "Our solution",
    seconds: 22,
    say: "AgentTrace records the run, follows the data back to the step that caused it, then tests the fix: fork that step, rerun everything after it live, with and without the change. Zero of eight becomes eight of eight. It sits on top of the harness she already uses, and tells her in Slack when something breaks.",
    body: (
      <div className="flex flex-col gap-8">
        <h2 className="deck-in font-serif text-[clamp(2.25rem,4.5vw,3.5rem)] leading-none tracking-tight">Find the step. Prove the fix.</h2>
        <Solution />
        <p className="text-[0.9375rem] text-muted">Directional evidence, not proof: live steps are sampled, so every side is repeated.</p>
      </div>
    ),
  },
];

export function PitchDeck() {
  const [i, setI] = useState(0);
  const [notes, setNotes] = useState(false);
  const go = useCallback((n: number) => setI(Math.max(0, Math.min(SLIDES.length - 1, n))), []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (["ArrowRight", " ", "PageDown", "Enter"].includes(e.key)) { e.preventDefault(); setI((c) => Math.min(SLIDES.length - 1, c + 1)); }
      else if (["ArrowLeft", "PageUp", "Backspace"].includes(e.key)) { e.preventDefault(); setI((c) => Math.max(0, c - 1)); }
      else if (e.key === "Home") setI(0);
      else if (e.key === "End") setI(SLIDES.length - 1);
      else if (e.key.toLowerCase() === "n") setNotes((v) => !v);
      else if (e.key.toLowerCase() === "f") {
        if (document.fullscreenElement) void document.exitFullscreen();
        else void document.documentElement.requestFullscreen?.();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const slide = SLIDES[i];
  return (
    <div className="fixed inset-0 flex flex-col bg-frame text-ink">
      <header className="flex items-center justify-between px-8 py-6 sm:px-14">
        <span className="flex items-center gap-2.5 font-serif text-[1.25rem] leading-none"><Mark />AgentTrace</span>
        <nav aria-label="Slides" className="flex items-center gap-2">
          {SLIDES.map((s, n) => (
            <button
              key={s.title} type="button" onClick={() => go(n)} aria-label={`Slide ${n + 1}: ${s.title}`} aria-current={n === i}
              className={`h-1.5 rounded-full transition-all ${n === i ? "w-10 bg-ink" : "w-4 bg-line hover:bg-muted"}`}
            />
          ))}
        </nav>
      </header>

      <main key={i} aria-roledescription="slide" aria-label={`${slide.title}, slide ${i + 1} of ${SLIDES.length}`} className="mx-auto flex w-full max-w-6xl flex-1 flex-col justify-center px-8 pb-16 sm:px-14">
        {slide.body}
      </main>

      {notes && (
        <aside className="absolute inset-x-0 bottom-0 border-t border-line bg-sheet px-8 py-5 sm:px-14" aria-label="Speaker notes">
          <p className="text-[0.8125rem] text-muted">Slide {i + 1} · aim for {slide.seconds} s · running total {SLIDES.slice(0, i + 1).reduce((a, s) => a + s.seconds, 0)} s of 60</p>
          <p className="mt-1 max-w-[110ch] text-[1.0625rem]">{slide.say}</p>
        </aside>
      )}
      <p className="pointer-events-none absolute bottom-3 right-6 text-[0.75rem] text-muted/60">← → move · F full screen · N notes</p>
    </div>
  );
}

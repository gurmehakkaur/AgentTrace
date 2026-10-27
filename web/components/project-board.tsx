"use client";

import Link from "next/link";
import { useCallback, useMemo, useRef, useState } from "react";
import { buildBoard, countRight, findingOf, FILTERS, laneMatches, type Filter, type ForkItem } from "@/lib/board";
import { buildRows, domainOf, ticksOf, type ForkRow, type GroupRow, type Row, type RunRow } from "@/lib/gantt";
import type { Experiment, RunSummary } from "@/lib/types";

const ROW = 38; // one row, in the list and in the chart, so they line up
const HEAD = 58; // the two-line time axis
const MIN_BAR = 14;
const MIN_WIDTH = 640;

const RULE = "border-b border-line"; // taste-skill-ignore: a real table's row rules and its header edge
const SIDE = "border-r border-line"; // taste-skill-ignore: the edge between the run list and the chart
const FRAME = "border border-line"; // taste-skill-ignore: the frame of the sheet
const PICK = "border-b border-accent"; // taste-skill-ignore: the one selection mark, a 1px line as wide as its label
const NOPICK = "border-b border-transparent"; // taste-skill-ignore: keeps the label from jumping when it is picked

const shortTime = (ms: number) => new Date(ms).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function useWidth() {
  const [width, setWidth] = useState(900);
  const watcher = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: HTMLElement | null) => {
    watcher.current?.disconnect();
    watcher.current = null;
    if (!el) return;
    setWidth(el.clientWidth);
    watcher.current = new ResizeObserver(() => setWidth(el.clientWidth));
    watcher.current.observe(el);
  }, []);
  return [ref, width] as const;
}

/** All your runs on one sheet, by time. Each run is a numbered row with its own colour; the forks you tried on it are
 * markers on the rows beneath it. Click any row to open that run, or that fork on its run. */
export function ProjectBoard({ runs, experiments }: { runs: RunSummary[]; experiments: Experiment[] }) {
  const board = useMemo(() => buildBoard(runs, experiments), [runs, experiments]);
  const finding = findingOf(board);
  const [filter, setFilter] = useState<Filter>("all");
  const counts = Object.fromEntries(FILTERS.map((f) => [f.key, board.lanes.filter((l) => laneMatches(l, f.key)).length])) as Record<Filter, number>;
  const rows = useMemo(() => buildRows(board, filter), [board, filter]);

  return (
    <div className="flex flex-col gap-8">
      <section aria-label="Summary" className="flex flex-col gap-1">
        <h2 className="max-w-[28ch] font-serif text-[1.75rem] leading-[1.15] sm:text-[2rem]">{finding.first}</h2>
        <p className="max-w-[60ch] text-[1.0625rem] text-muted">{finding.second}</p>
      </section>

      <section aria-label="Runs by time" className="flex flex-col gap-4">
        <div className={`flex flex-wrap items-end justify-between gap-x-6 gap-y-2 ${RULE}`}>
          <div role="group" aria-label="Show" className="flex gap-6">
            {FILTERS.map((f) => (
              <button
                key={f.key} type="button" onClick={() => setFilter(f.key)} aria-pressed={filter === f.key}
                className={`pb-2.5 ${filter === f.key ? "text-ink" : "text-muted hover:text-ink"}`}
              >
                <span className={`inline-block pb-2.5 -mb-px ${filter === f.key ? PICK : NOPICK}`}>
                  {f.label} <span className="text-muted">{counts[f.key]}</span>
                </span>
              </button>
            ))}
          </div>
          <Legend />
        </div>
        {rows.length === 0
          ? <p className="py-8 text-muted">Nothing here yet. {filter === "fixed" ? "A run shows up here once a fork has fixed it." : "Try another filter."}</p>
          : <Sheet rows={rows} />}
      </section>
    </div>
  );
}

function Legend() {
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 pb-2.5 text-[0.8125rem] text-muted">
      <span className="flex items-center gap-1.5"><span aria-hidden className="h-2 w-5 rounded-sm bg-muted" />a run</span>
      <span className="flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rotate-45 bg-muted" />a fork that helped</span>
      <span className="flex items-center gap-1.5"><span aria-hidden className="h-2.5 w-2.5 rotate-45 border-[1.5px] border-muted" />a fork that did not</span>
    </p>
  );
}

function Sheet({ rows }: { rows: Row[] }) {
  const [ref, avail] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const width = Math.max(MIN_WIDTH, avail);
  const { min, max } = useMemo(() => domainOf(rows), [rows]);
  const x = (t: number) => ((t - min) / (max - min)) * width;
  const { ticks, days } = useMemo(() => ticksOf(min, max, width), [min, max, width]);
  const height = rows.length * ROW;
  const mid = (i: number) => i * ROW + ROW / 2;

  return (
    <div className={`flex overflow-hidden rounded-xl bg-sheet ${FRAME}`}>
      {/* the list: an index like a sheet, a colour strip for the run, then its name */}
      <div className={`w-[10.5rem] flex-none sm:w-[19rem] ${SIDE}`}>
        <div className={`flex items-end px-3 pb-2 text-[0.8125rem] text-muted ${RULE}`} style={{ height: HEAD }}>Runs and the forks tried on them</div>
        <ol>
          {rows.map((r, i) => (
            <li key={r.n} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} style={{ height: ROW }} className={`${RULE} ${hover === i ? "bg-tile/50" : r.kind === "group" ? "bg-tile/30" : ""}`}>
              <ListRow row={r} />
            </li>
          ))}
        </ol>
      </div>

      <div ref={ref} className="graph-scroll min-w-0 flex-1 overflow-x-auto">
        <div style={{ width }} className="relative">
          <div className={`relative ${RULE}`} style={{ height: HEAD }} aria-hidden>
            {days.map((d) => <span key={d.t} className="absolute top-2 whitespace-nowrap pl-2 text-[0.8125rem] text-ink" style={{ left: x(d.t) }}>{d.label}</span>)}
            {ticks.map((t) => <span key={t.t} className="absolute bottom-2 -translate-x-1/2 whitespace-nowrap text-[0.75rem] text-muted" style={{ left: x(t.t) }}>{t.label}</span>)}
          </div>

          <div className="relative" style={{ height }}>
            <svg className="absolute inset-0" width={width} height={height} aria-hidden>
              {ticks.map((t) => <line key={t.t} x1={x(t.t)} x2={x(t.t)} y1={0} y2={height} stroke="var(--line)" strokeOpacity={0.6} />)}
              {rows.map((r, i) => <line key={r.n} x1={0} x2={width} y1={(i + 1) * ROW} y2={(i + 1) * ROW} stroke="var(--line)" />)}
              {rows.map((r, i) => (r.kind === "fork" ? <Elbow key={r.n} row={r} index={i} rows={rows} x={x} mid={mid} /> : null))}
            </svg>
            {hover !== null && <div aria-hidden className="pointer-events-none absolute inset-x-0 bg-tile/50" style={{ top: hover * ROW, height: ROW }} />}
            {rows.map((r, i) => (
              <div key={r.n} className={`absolute inset-x-0 ${r.kind === "group" ? "bg-tile/30" : ""}`} style={{ top: i * ROW, height: ROW }} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                {r.kind === "group" ? <GroupBar row={r} x={x} /> : r.kind === "run" ? <RunBar row={r} x={x} width={width} /> : <ForkMark row={r} x={x} width={width} />}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ListRow({ row: r }: { row: Row }) {
  const gutter = <span className="flex h-full w-8 flex-none items-center justify-end bg-tile/40 pr-2 text-[0.75rem] text-muted" aria-hidden>{r.n}</span>;
  if (r.kind === "group") {
    return (
      <div className="flex h-full items-center">
        {gutter}
        <span className="min-w-0 truncate pl-3 pr-2"><b className="font-medium">{r.label}</b> <span className="text-[0.8125rem] text-muted">{r.sub}</span></span>
      </div>
    );
  }
  if (r.kind === "run") {
    const wrong = r.lane.run.outcome === "fail" || r.lane.run.outcome === "error";
    return (
      <Link href={r.href} className="flex h-full items-center hover:text-ink" aria-label={`Run from ${shortTime(r.from)}, ${wrong ? "wrong answer" : r.lane.run.outcome === "pass" ? "right answer" : "no result yet"}. Open it.`}>
        {gutter}
        <span className="h-full w-[3px] flex-none" style={{ background: r.color }} aria-hidden />
        <span className="min-w-0 flex-1 truncate pl-3 pr-2">{shortTime(r.from)}</span>
        <span className={`hidden flex-none pr-3 text-[0.8125rem] sm:inline ${wrong ? "text-bad" : "text-muted"}`}>{r.lane.run.outcome === "pass" ? "Right" : wrong ? "Wrong" : "…"}</span>
      </Link>
    );
  }
  return (
    <Link href={r.href} className="flex h-full items-center" aria-label={`Fork ${r.fork.number}, changed the ${r.fork.agent}. Open it.`}>
      {gutter}
      <span className="h-full w-[3px] flex-none opacity-50" style={{ background: r.color }} aria-hidden />
      <span className="min-w-0 flex-1 truncate pl-7 pr-2 text-[0.9rem] text-muted">{r.fork.nested ? "↳ " : ""}Fork {r.fork.number} · <span className="capitalize">{r.fork.agent}</span></span>
    </Link>
  );
}

/** A label next to a mark, on whichever side has room. */
function Label({ at, width, left, children, className = "" }: { at: number; width: number; left: number; children: React.ReactNode; className?: string }) {
  const flip = at > width - 190;
  return (
    <span className={`pointer-events-none absolute top-1/2 -translate-y-1/2 whitespace-nowrap text-[0.8125rem] ${className}`} style={flip ? { right: width - left + 8 } : { left: at + 8 }}>
      {children}
    </span>
  );
}

function GroupBar({ row: r, x }: { row: GroupRow; x: (t: number) => number }) {
  const a = x(r.from);
  const b = Math.max(x(r.to), a + MIN_BAR);
  return (
    <>
      <span aria-hidden className="absolute top-1/2 h-[5px] -translate-y-1/2 rounded-sm bg-muted/50" style={{ left: a, width: b - a }} />
    </>
  );
}

function RunBar({ row: r, x, width }: { row: RunRow; x: (t: number) => number; width: number }) {
  const a = x(r.from);
  const b = Math.max(x(r.to), a + MIN_BAR);
  const out = r.lane.run.outcome;
  const wrong = out === "fail" || out === "error";
  return (
    <>
      <Link
        href={r.href} aria-label={`Run from ${shortTime(r.from)}. Open it.`} title={`${shortTime(r.from)} · ${wrong ? "wrong answer" : out === "pass" ? "right answer" : "no result yet"}`}
        className="absolute top-1/2 h-4 -translate-y-1/2 rounded-[4px] hover:brightness-125" style={{ left: a, width: b - a, background: r.color }}
      />
      <Label at={b} left={a} width={width} className={wrong ? "text-bad" : "text-muted"}>{out === "pass" ? "Right answer" : wrong ? "Wrong answer" : "No verdict yet"}</Label>
    </>
  );
}

function outcomeOf(f: ForkItem): { text: string; tone: string } {
  const total = f.ballot.with.length;
  const right = `${countRight(f.ballot.without)} → ${countRight(f.ballot.with)} of ${total} right`;
  if (f.running) return { text: "Running…", tone: "text-muted" };
  if (f.tone === "good") return { text: `${right}, ${countRight(f.ballot.with) / (total || 1) >= 0.8 ? "fixed it" : "helped"}`, tone: "text-good" };
  if (f.tone === "bad") return { text: `${right}, no help`, tone: "text-bad" };
  return { text: `${right}, a hint only`, tone: "text-ink" };
}

function ForkMark({ row: r, x, width }: { row: ForkRow; x: (t: number) => number; width: number }) {
  const cx = x(r.at);
  const helped = r.fork.tone === "good";
  const o = outcomeOf(r.fork);
  return (
    <>
      <Link
        href={r.href} aria-label={`Fork ${r.fork.number}, changed the ${r.fork.agent}: ${o.text}. Open it.`} title={`${r.fork.agent}: ${o.text}`}
        className="absolute top-1/2 h-[18px] w-[18px] -translate-x-1/2 -translate-y-1/2" style={{ left: cx }}
      >
        <span
          aria-hidden className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 border-[1.5px]"
          style={{ borderColor: r.color, background: helped ? r.color : "var(--sheet)" }}
        />
      </Link>
      <Label at={cx + 6} left={cx - 6} width={width} className={o.tone}>{o.text}</Label>
    </>
  );
}

/** From the end of a run, down to the fork made from it. */
function Elbow({ row: r, index, rows, x, mid }: { row: ForkRow; index: number; rows: Row[]; x: (t: number) => number; mid: (i: number) => number }) {
  const parent = rows[r.parent];
  if (parent.kind !== "run") return null;
  const start = Math.max(x(parent.to), x(parent.from) + MIN_BAR);
  const end = x(r.at) - 9;
  const y0 = mid(r.parent) + 8;
  const y1 = mid(index);
  const d = end - start > 14 ? `M${start} ${mid(r.parent)} H${start + 7} V${y1} H${end}` : `M${start - 7} ${y0} V${y1 - 9}`;
  return <path d={d} fill="none" stroke={r.color} strokeOpacity={0.7} strokeWidth={1.5} />;
}

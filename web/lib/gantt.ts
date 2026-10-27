import { laneMatches } from "./board.ts";
import type { Board, Filter, ForkItem, Lane } from "./board";

/** The runs overview as a Gantt: one numbered row per run, time across, each run in its own colour. A fork is a
 * marker on its own row under the run it was made from. Rows are oldest first, so the chart steps down the page. */

// Hues for runs. None is red or green (those say wrong and right) and none is the accent.
export const RUN_COLORS = ["#6ea8fe", "#b69cf5", "#e6b45e", "#5fc9c4", "#e58fc0", "#a3b8cc"];

export type GroupRow = { kind: "group"; n: number; key: string; label: string; sub: string; from: number; to: number };
export type RunRow = { kind: "run"; n: number; lane: Lane; color: string; from: number; to: number; href: string };
export type ForkRow = { kind: "fork"; n: number; fork: ForkItem; color: string; at: number; parent: number; href: string };
export type Row = GroupRow | RunRow | ForkRow;

const ms = (iso?: string | null) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? null : t;
};

export function buildRows(board: Board, filter: Filter): Row[] {
  // Colours follow the run, not the row, so filtering never recolours anything.
  const colorOf = new Map(
    [...board.lanes].sort((a, b) => a.run.started_at.localeCompare(b.run.started_at)).map((l, i) => [l.run.id, RUN_COLORS[i % RUN_COLORS.length]]),
  );
  const byFlow = new Map<string, Lane[]>();
  for (const lane of board.lanes) {
    if (!laneMatches(lane, filter)) continue;
    byFlow.set(lane.run.workflow, [...(byFlow.get(lane.run.workflow) ?? []), lane]);
  }
  const groups = [...byFlow.entries()].map(([label, lanes]) => ({
    label, lanes: [...lanes].sort((a, b) => a.run.started_at.localeCompare(b.run.started_at)),
  })).sort((a, b) => a.lanes[0].run.started_at.localeCompare(b.lanes[0].run.started_at));

  const rows: Row[] = [];
  for (const g of groups) {
    const head: GroupRow = { kind: "group", n: rows.length + 1, key: g.label, label: g.label, sub: "", from: Infinity, to: -Infinity };
    rows.push(head);
    for (const lane of g.lanes) {
      const from = ms(lane.run.started_at) ?? 0;
      const to = Math.max(from, ms(lane.run.ended_at) ?? from);
      const color = colorOf.get(lane.run.id)!;
      const runIndex = rows.length;
      rows.push({ kind: "run", n: rows.length + 1, lane, color, from, to, href: `/runs/${lane.run.id}` });
      head.from = Math.min(head.from, from);
      head.to = Math.max(head.to, to);
      for (const fork of lane.forks) {
        const at = fork.at ?? to;
        rows.push({ kind: "fork", n: rows.length + 1, fork, color, at, parent: runIndex, href: fork.href });
        head.to = Math.max(head.to, at);
      }
    }
    const runs = g.lanes.length;
    const fixed = g.lanes.filter((l) => l.status === "fixed").length;
    const wrong = g.lanes.filter((l) => l.status === "open" || l.status === "none").length;
    head.sub = [`${runs} ${runs === 1 ? "run" : "runs"}`, fixed ? `${fixed} fixed` : "", wrong ? `${wrong} wrong` : ""].filter(Boolean).join(" · ");
  }
  return rows;
}

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

/** The time range to draw: everything on screen with a little air on both sides. */
export function domainOf(rows: Row[]): { min: number; max: number } {
  const times = rows.flatMap((r) => (r.kind === "fork" ? [r.at] : [r.from, r.to]));
  if (times.length === 0) {
    const now = Date.now();
    return { min: now - HOUR, max: now + HOUR };
  }
  let min = Math.min(...times);
  let max = Math.max(...times);
  if (max - min < 30 * MIN) {
    const mid = (min + max) / 2;
    min = mid - 15 * MIN;
    max = mid + 15 * MIN;
  }
  const pad = (max - min) * 0.06;
  return { min: min - pad, max: max + pad };
}

const STEPS = [MIN, 5 * MIN, 10 * MIN, 15 * MIN, 30 * MIN, HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY, 30 * DAY];
export type Tick = { t: number; label: string };

/** Axis ticks no closer than `gap` pixels, on round local times, and the day labels above them. */
export function ticksOf(min: number, max: number, width: number, gap = 84): { ticks: Tick[]; days: Tick[]; step: number } {
  const perMs = width / (max - min);
  const step = STEPS.find((s) => s * perMs >= gap) ?? STEPS[STEPS.length - 1];
  const off = new Date(min).getTimezoneOffset() * MIN; // local time = utc - off
  const ticks: Tick[] = [];
  for (let t = Math.ceil((min - off) / step) * step + off; t <= max; t += step) {
    const d = new Date(t);
    ticks.push({ t, label: step < DAY ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : d.toLocaleDateString([], { month: "short", day: "numeric" }) });
  }
  const days: Tick[] = [];
  if (step < DAY) {
    const d = new Date(min);
    d.setHours(0, 0, 0, 0);
    for (; d.getTime() <= max; d.setDate(d.getDate() + 1)) {
      days.push({ t: Math.max(d.getTime(), min), label: d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }) });
    }
  }
  return { ticks, days, step };
}

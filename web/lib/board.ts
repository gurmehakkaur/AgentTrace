import { verdictFor } from "./verdict.ts";
import type { Arm, Experiment, RunSummary, Tile } from "./types";

/** The project at a glance. One row per recorded run. A fork is drawn as a ballot: one dot for each live run it
 * made, the runs without the change on one row and the runs with it on the other, so a fix reads as a row of
 * hollow dots turning solid. */

export type Dot = "right" | "wrong" | "error" | "open";
export type Ballot = { without: Dot[]; with: Dot[] };

export type ForkItem = {
  id: string;
  number: number; // Fork 1, Fork 2... within its run
  agent: string; // the agent that was changed
  ballot: Ballot;
  result: string; // "8 of 8 right"
  without: string; // "without the change 0 of 8"
  tone: "neutral" | "good" | "bad";
  verdict: string; // one plain sentence, "" while it runs
  p: number | null;
  at: number | null; // when the fork was started, in ms
  running: boolean;
  nested: boolean; // made from one of another fork's runs
  href: string;
};
export type Lane = {
  run: RunSummary;
  forks: ForkItem[];
  status: "right" | "fixed" | "open" | "none";
  statusText: string;
};
export type Lead = { fork: ForkItem; workflow: string; fix: boolean };
export type Board = {
  lanes: Lane[];
  stats: { runs: number; forks: number; worked: number; fixedRuns: number; failedRuns: number };
  best: Lead | null; // the strongest fork that worked
  latest: Lead | null; // the newest finished fork, which is what to show when nothing has worked yet
};

type ForkExperiment = Experiment & { fork_agent?: string | null };

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

function dotOf(t: Tile): Dot {
  if (t.status !== "done" && t.status !== "skipped") return "open";
  if (t.outcome === "pass") return "right";
  if (t.outcome === "fail") return "wrong";
  return t.status === "skipped" ? "open" : "error";
}

/** One row of dots for an arm. Older experiments without tiles fall back to the arm's counts. */
function armDots(tiles: Tile[], arm: "control" | "treatment", counts: Arm): Dot[] {
  const mine = tiles.filter((t) => t.arm === arm).sort((a, b) => a.i - b.i);
  if (mine.length) return mine.map(dotOf);
  return [...Array(counts.pass).fill("right"), ...Array(Math.max(0, counts.total - counts.pass)).fill("wrong")];
}

export function ballotOf(e: Pick<Experiment, "tiles" | "control" | "treatment">): Ballot {
  return { without: armDots(e.tiles, "control", e.control), with: armDots(e.tiles, "treatment", e.treatment) };
}

export function buildBoard(runs: RunSummary[], experiments: ForkExperiment[]): Board {
  const recorded = runs.filter((r) => r.kind !== "fork").sort((a, b) => b.started_at.localeCompare(a.started_at));
  const known = new Set(recorded.map((r) => r.id));

  // A fork can be made from one of another fork's own runs; it still belongs to the run the chain started from.
  const byId = new Map(experiments.map((e) => [e.id, e]));
  const made = new Map<string, string>(); // run id made by a fork -> that fork
  for (const e of experiments) for (const t of e.tiles) if (t.run_id) made.set(t.run_id, e.id);
  const rootOf = (parent: string, depth = 0): string | null => {
    if (known.has(parent)) return parent;
    const via = made.get(parent);
    return via && depth < 6 && byId.get(via) ? rootOf(byId.get(via)!.parent_run, depth + 1) : null;
  };

  const attached = new Map<string, ForkExperiment[]>();
  for (const e of [...experiments].sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""))) {
    const root = rootOf(e.parent_run);
    if (root) attached.set(root, [...(attached.get(root) ?? []), e]);
  }

  let best: (Lead & { rate: number; total: number }) | null = null;
  let latest: (Lead & { at: string }) | null = null;
  let worked = 0;
  let forks = 0;
  const lanes: Lane[] = recorded.map((run) => {
    const items: ForkItem[] = (attached.get(run.id) ?? []).map((e, i) => {
      const running = ["queued", "running"].includes(e.status);
      const verdict = running ? null : verdictFor(e.control, e.treatment, e.stats.fisher_p);
      const tone = !verdict ? "neutral" : verdict.tone;
      const item: ForkItem = {
        id: e.id, number: i + 1, agent: e.fork_agent ?? "agent", running, tone, nested: !known.has(e.parent_run),
        ballot: ballotOf(e), verdict: verdict?.text ?? "", p: e.stats.fisher_p, at: e.created_at ? Date.parse(e.created_at) || null : null,
        result: running ? "Running…" : `${e.treatment.pass} of ${e.treatment.total} right`,
        without: running ? "still running" : `without the change ${e.control.pass} of ${e.control.total}`,
        href: `/runs/${run.id}?fork=${e.id}`,
      };
      forks++;
      if (!running && (!latest || (e.created_at ?? "") >= latest.at)) {
        latest = { fork: item, workflow: run.workflow, fix: tone === "good", at: e.created_at ?? "" };
      }
      if (tone === "good") {
        worked++;
        const rate = e.treatment.total ? e.treatment.pass / e.treatment.total : 0;
        if (!best || rate > best.rate || (rate === best.rate && e.treatment.total > best.total)) {
          best = { fork: item, workflow: run.workflow, fix: true, rate, total: e.treatment.total };
        }
      }
      return item;
    });
    const firstGood = items.find((f) => f.tone === "good");
    const status: Lane["status"] = run.outcome === "pass" ? "right" : firstGood ? "fixed" : items.length ? "open" : "none";
    const statusText = status === "right" ? "Gave the right answer"
      : status === "fixed" ? `Fixed by fork ${firstGood!.number}`
      : status === "open" ? "Not fixed yet"
      : run.outcome === "fail" ? "Nothing tried yet" : "No forks";
    return { run, forks: items, status, statusText };
  });

  const lead = (l: (Lead & object) | null): Lead | null => (l ? { fork: l.fork, workflow: l.workflow, fix: l.fix } : null);
  return {
    lanes,
    stats: {
      runs: recorded.length, forks, worked,
      fixedRuns: lanes.filter((l) => l.status === "fixed").length,
      failedRuns: recorded.filter((r) => r.outcome === "fail").length,
    },
    best: lead(best),
    latest: lead(latest),
  };
}

/** The finding the page opens with, in two plain sentences: what is wrong, and what you have done about it. */
export function findingOf(board: Board): { first: string; second: string } {
  const { stats, best, latest } = board;
  if (stats.failedRuns === 0) {
    return { first: stats.runs === 1 ? "Your run gave the right answer." : "Every run gave the right answer.", second: stats.forks ? `You have tried ${stats.forks} ${stats.forks === 1 ? "fork" : "forks"}.` : "Nothing to fix right now." };
  }
  const first = stats.runs === 1 ? "Your run gave a wrong answer." : `${stats.failedRuns} of ${stats.runs} runs gave a wrong answer.`;
  if (best) {
    const f = best.fork;
    return { first, second: `Changing the ${f.agent} took it from ${countRight(f.ballot.without)} of ${f.ballot.without.length} right to ${countRight(f.ballot.with)} of ${f.ballot.with.length}.` };
  }
  if (stats.forks > 0) return { first, second: latest ? `Nothing you tried has fixed it yet. Last: the ${latest.fork.agent}.` : "Your forks are still running." };
  return { first, second: "You have not tried a fork yet. Open a wrong run, change what an agent wrote, and fork it." };
}

export type Filter = "all" | "wrong" | "fixed" | "right";
export const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" }, { key: "wrong", label: "Wrong" }, { key: "fixed", label: "Fixed" }, { key: "right", label: "Right" },
];

/** Wrong = a wrong answer nobody has fixed yet. Fixed = a wrong answer a fork fixed. */
export function laneMatches(lane: Lane, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "right") return lane.status === "right";
  if (filter === "fixed") return lane.status === "fixed";
  return (lane.status === "open" || lane.status === "none") && !!lane.run.outcome && lane.run.outcome !== "pass";
}

export const countRight = (dots: Dot[]) => dots.filter((d) => d === "right").length;
export { cap };

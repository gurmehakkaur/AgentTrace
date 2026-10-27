import { diffState } from "./diff.ts";
import { nodeRuns } from "./runs.ts";
import { agentCards, brief, callsLabel, taskOf, type Mark } from "./story.ts";
import { verdictFor } from "./verdict.ts";
import type { Experiment, Origin, Step } from "./types";

/** The run as a line. One lane is one path through the workflow: lane 0 is the original run, and every
 * fork (an experiment) opens a new lane that leaves the line where the change was made. Columns are
 * the order things ran in, so a node further right ran later. */

export const COL_W = 146;
export const LANE0_H = 172; // the original line is taller: its agents carry a task line and a mark
export const LANE_H = 138;
export const PAD_X = 36;
export const PAD_Y = 40;

export type NodeKind = "start" | "agent" | "edited" | "live" | "result";
export type Tone = "neutral" | "good" | "bad";

export type GNode = {
  id: string;
  lane: number;
  col: number;
  kind: NodeKind;
  label: string; // the agent's name, or the result
  sub: string; // one plain line under it: what the agent does, or what happened
  mark?: Mark;
  tone: Tone;
  nodeRun?: number; // which agent run this is
  experiment?: string; // which fork a branch node belongs to
  origin?: Origin; // set when the step did not come straight from the recording
  draft?: boolean; // part of a fork that has not been started yet
  change?: string[]; // on an edited node: each value that was changed, "name: before → after"
};

export type GEdge = { id: string; from: string; to: string; kind: "line" | "spawn"; lane: number };
export type GLane = { index: number; label: string; experiment?: string; tone: Tone };
export type Graph = { lanes: GLane[]; nodes: GNode[]; edges: GEdge[]; cols: number; width: number; height: number };

type Fork = { key: string; exp?: Experiment; parent: string; forkAt: number; number: number; created: string };

export function buildGraph(
  steps: Step[], opts: { marks?: Map<number, Mark>; experiments?: Experiment[]; outcome?: string; resultText?: string; draft?: { nodeRun: number; fromExperiment?: string | null } | null },
): Graph {
  const cards = agentCards(steps);
  const marks = opts.marks ?? new Map<number, Mark>();
  const nodes: GNode[] = [{ id: "start", lane: 0, col: 0, kind: "start", label: "Request", sub: "what the run was asked", tone: "neutral" }];
  const edges: GEdge[] = [];
  const lanes: GLane[] = [{ index: 0, label: "Original run", tone: "neutral" }];

  cards.forEach((c, i) => {
    const o = originNote(c.steps);
    nodes.push({
      id: `a${c.idx}`, lane: 0, col: i + 1, kind: "agent", label: c.agent, sub: o ? o.note : taskOf(c.steps) ?? callsLabel(c),
      mark: marks.get(c.idx), tone: "neutral", nodeRun: c.idx, origin: o?.origin,
    });
  });
  const end = cards.length + 1;
  const wrong = opts.outcome === "fail" || opts.outcome === "error";
  nodes.push({
    id: "end", lane: 0, col: end, kind: "result", label: wrong ? "Wrong answer" : opts.outcome === "pass" ? "Right answer" : "Finished",
    sub: opts.resultText ?? "", tone: wrong ? "bad" : opts.outcome === "pass" ? "good" : "neutral",
  });
  chain(edges, nodes.filter((n) => n.lane === 0), 0);

  // Which forks exist, and what each was forked from. A fork can be made from one of another fork's own
  // runs; then it hangs off that fork's line.
  const mainId = steps[0]?.run;
  const owner = new Map<string, string>(); // run id -> the fork that made it
  const forks: Fork[] = [];
  for (const e of opts.experiments ?? []) {
    const forkAt = cards.findIndex((c) => c.idx === e.fork_node_run_idx);
    if (forkAt < 0) continue;
    const fromMain = mainId === undefined || e.parent_run === mainId;
    const parentExp = fromMain ? undefined : owner.get(e.parent_run);
    if (!fromMain && !parentExp) continue; // made from a run we do not draw
    forks.push({ key: e.id, exp: e, parent: parentExp ?? "main", forkAt, number: forks.filter((f) => f.exp).length + 1, created: e.created_at ?? "" });
    for (const t of e.tiles) if (t.arm === "treatment" && t.run_id) owner.set(t.run_id, e.id);
  }
  const at = opts.draft ? cards.findIndex((c) => c.idx === opts.draft!.nodeRun) : -1;
  if (opts.draft && at >= 0) {
    const from = opts.draft.fromExperiment;
    // The newest thing there is: it opens right under the line it was forked from.
    forks.push({ key: "draft", parent: from && forks.some((f) => f.key === from) ? from : "main", forkAt: at, number: 0, created: "\uffff" });
  }

  // Lanes run top to bottom in the order of a tree: a fork sits right under the line it came from, and its own
  // forks sit right under it. Among forks of one line, the one made at a later agent is nearer the line, then the
  // newest. So a new fork opens right under its parent and pushes the others down, and a line never has to cross
  // the forks above it.
  const laneOf = new Map<string, number>();
  let next = 1;
  const place = (parent: string) => {
    const kids = forks.filter((f) => f.parent === parent).sort((a, b) => b.forkAt - a.forkAt || b.created.localeCompare(a.created));
    for (const f of kids) {
      laneOf.set(f.key, next++);
      place(f.key);
    }
  };
  place("main");

  /** The node a new line leaves: the one just before the changed agent, on the line it was forked from. */
  const sourceFor = (parentLane: number, forkAt: number): string => {
    const onParent = parentLane > 0 ? nodes.find((n) => n.lane === parentLane && n.col === forkAt) : undefined;
    if (onParent) return onParent.id;
    return forkAt === 0 ? "start" : `a${cards[forkAt - 1].idx}`;
  };

  for (const f of [...forks].sort((a, b) => laneOf.get(a.key)! - laneOf.get(b.key)!)) {
    const lane = laneOf.get(f.key)!;
    const parentLane = f.parent === "main" ? 0 : laneOf.get(f.parent) ?? 0;
    const agent = cards[f.forkAt].agent;
    const e = f.exp;
    const draft = !e;
    const done = !!e && !["queued", "running"].includes(e.status);
    const verdict = e ? verdictFor(e.control, e.treatment, e.stats.fisher_p) : null;
    const tone: Tone = !done || !verdict ? "neutral" : verdict.tone === "good" ? "good" : verdict.tone === "bad" ? "bad" : "neutral";
    lanes.push({ index: lane, label: draft ? "New fork, not started" : `Fork ${f.number}: ${agent} changed`, experiment: e?.id ?? "draft", tone });

    const change = e ? describeEdit(steps, e.fork_node_run_idx, e.edit_patch) : null;
    const id = (part: string) => `${f.key}:${part}`;
    const branch: GNode[] = [
      { id: draft ? "draft:edit" : id("edit"), lane, col: f.forkAt + 1, kind: "edited", label: agent, sub: draft ? "your change goes here" : change?.short ?? "Changed by you", tone: "neutral", experiment: f.key, change: change?.lines, nodeRun: cards[f.forkAt].idx, draft },
      ...cards.slice(f.forkAt + 1).map((c, j): GNode => ({
        id: draft ? `draft:${c.idx}` : id(String(c.idx)), lane, col: f.forkAt + 2 + j, kind: "live", label: c.agent,
        sub: draft ? "will run again" : `Run again ${e!.n} times`, tone: "neutral", experiment: f.key, nodeRun: c.idx, draft,
      })),
      {
        id: draft ? "draft:end" : id("end"), lane, col: end, kind: "result", tone, experiment: f.key, draft,
        label: draft ? "Not run yet" : done ? `${e!.treatment.pass} of ${e!.treatment.total} right` : "Running…",
        sub: draft ? "make the change below" : done ? `without the change: ${e!.control.pass} of ${e!.control.total}` : `${e!.tiles.filter((t) => t.status === "done").length} of ${e!.tiles.length} runs done`,
      },
    ];
    nodes.push(...branch);
    chain(edges, branch, lane);
    edges.push({ id: draft ? "draft:spawn" : id("spawn"), from: sourceFor(parentLane, f.forkAt), to: branch[0].id, kind: "spawn", lane });
  }

  return {
    lanes: lanes.sort((a, b) => a.index - b.index), nodes, edges, cols: end + 1,
    width: PAD_X * 2 + (end + 1) * COL_W, height: PAD_Y + LANE0_H + Math.max(0, lanes.length - 1) * LANE_H + 12,
  };
}

/** Where an agent's steps came from, when that is not simply "the original recording": copied exactly,
 * changed by a fork, or run again live. This is the line between what replays and what is sampled. */
export function originNote(steps: Step[]): { origin: Origin; note: string } | null {
  const seen = new Set(steps.map((s) => s.origin));
  if (seen.size === 1 && seen.has("recorded")) return null;
  if (seen.has("edited")) return { origin: "edited", note: "your change is applied here" };
  if (seen.has("live")) return { origin: "live", note: "ran live, so it is sampled" };
  return { origin: "replayed", note: "replayed exactly from the recording" };
}

/** What a fork changed, in words: each value that differs from the recording, before and after. */
export function describeEdit(steps: Step[], nodeRun: number, patch: Record<string, unknown>): { lines: string[]; short: string | null } {
  const after = nodeRuns(steps).find((r) => r.idx === nodeRun)?.stateAfter ?? {};
  const before = Object.fromEntries(Object.keys(patch).map((k) => [k, after[k]]));
  const changes = diffState(before, patch);
  const leaf = (path: string) => path.split(".").slice(-1)[0];
  const lines = changes.map((c) => `${c.path}: ${c.kind === "added" ? "nothing" : brief(c.before, 60)} → ${c.kind === "removed" ? "nothing" : brief(c.after, 60)}`);
  const first = changes[0];
  const small = (v: unknown) => JSON.stringify(v ?? "").length <= 14;
  const side = (v: unknown, gone: boolean) => (gone ? "nothing" : brief(v, 14));
  // Short values read well on the line ("Changed drafts: 1 → 2"); long ones are described, and kept in full for the panel.
  const short = first
    ? `Changed ${leaf(first.path)}${small(first.before) && small(first.after) ? `: ${side(first.before, first.kind === "added")} → ${side(first.after, first.kind === "removed")}` : ""}${changes.length > 1 ? ` (+${changes.length - 1})` : ""}`
    : null;
  return { lines, short };
}

function chain(edges: GEdge[], line: GNode[], lane: number) {
  for (let i = 0; i < line.length - 1; i++) edges.push({ id: `${line[i].id}>${line[i + 1].id}`, from: line[i].id, to: line[i + 1].id, kind: "line", lane });
}

/** The height of a lane's line: the original line is taller than the forks under it. */
export const laneY = (lane: number) => PAD_Y + (lane === 0 ? 0 : LANE0_H + (lane - 1) * LANE_H) + 40;

/** Where a node's centre sits, in pixels. */
export const pos = (n: Pick<GNode, "lane" | "col">) => ({ x: PAD_X + n.col * COL_W + COL_W / 2, y: laneY(n.lane) });

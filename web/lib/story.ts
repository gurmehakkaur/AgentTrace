import { diffState, type Change } from "./diff.ts";
import { nodeRuns, stateBefore } from "./runs.ts";
import type { RcaReport, Step } from "./types";

/** One agent's turn, in plain terms: what it was called, what it did, what it changed. */
export type AgentCard = {
  idx: number; // which execution of an agent this is (1-based, run order)
  agent: string;
  steps: Step[];
  modelCalls: number;
  toolCalls: number;
  tools: string[];
  changes: Change[]; // the workflow state it changed
};

export function agentCards(steps: Step[]): AgentCard[] {
  const runs = nodeRuns(steps);
  return runs.map((r) => ({
    idx: r.idx,
    agent: r.agent,
    steps: r.steps,
    modelCalls: r.steps.filter((s) => s.kind === "llm").length,
    toolCalls: r.steps.filter((s) => s.kind === "tool").length,
    tools: [...new Set(r.steps.filter((s) => s.kind === "tool").map((s) => s.tool_name ?? "tool"))],
    changes: diffState(stateBefore(runs, r.idx), r.stateAfter),
  }));
}

/** A value on one line, cut to `max` characters. Strings show their first line. */
export function brief(value: unknown, max = 60): string {
  const text = typeof value === "string" ? value.split("\n").find((l) => l.trim()) ?? "" : JSON.stringify(value);
  const flat = (text ?? "").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

/** "ticket_filter.status = ["solved"]": the last two path parts keep it short and readable. */
export function describeChange(c: Change, max = 60): string {
  const path = c.path.split(".").slice(-2).join(".");
  return c.kind === "removed" ? `${path} removed` : `${path} = ${brief(c.after, max)}`;
}

/** "2 tool calls, 1 model call" */
export function callsLabel(card: Pick<AgentCard, "modelCalls" | "toolCalls">): string {
  const parts: string[] = [];
  if (card.toolCalls) parts.push(`${card.toolCalls} tool call${card.toolCalls === 1 ? "" : "s"}`);
  if (card.modelCalls) parts.push(`${card.modelCalls} model call${card.modelCalls === 1 ? "" : "s"}`);
  return parts.join(", ") || "no calls";
}

export type Mark = { kind: "cause"; confidence: number } | { kind: "carried" };

/** Which agent is the likely cause, and which later agents on the data path passed its mistake on. */
export function marksFromReport(report: RcaReport | null): Map<number, Mark> {
  const marks = new Map<number, Mark>();
  if (!report || report.candidates.length === 0) return marks;
  const order = report.verification?.ranking ?? report.candidates.map((_, i) => i);
  const top = report.candidates[order[0]];
  const start = report.lineage.indexOf(top.node_run_idx);
  if (start >= 0) report.lineage.slice(start + 1).forEach((i) => marks.set(i, { kind: "carried" }));
  marks.set(top.node_run_idx, { kind: "cause", confidence: top.confidence });
  return marks;
}

/** What an agent does, in the words of its own instructions: the first sentence after "You are the ...
 * agent", skipping sentences that describe its input. Null when the instructions were not recorded. */
export function taskOf(steps: Step[]): string | null {
  for (const step of steps) {
    const system = (step.input as { system?: unknown } | null)?.system;
    if (step.kind !== "llm" || typeof system !== "string") continue;
    const sentences = system.replace(/\s+/g, " ").split(/(?<=[.!?])\s+/).slice(1);
    const task = sentences.find((t) => t.length > 8 && !/^(You |Reply|Return|Output|Use only|Do not)/.test(t));
    if (!task) continue;
    const head = task.split(":")[0].replace(/[.!?]+$/, "").trim();
    return head.length <= 72 ? head : `${head.slice(0, 71).replace(/\s+\S*$/, "")}…`;
  }
  return null;
}

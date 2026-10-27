import type { State, Step } from "./types";

/** One execution of an agent. A node run may hold several steps (e.g. tool calls, then an LLM
 * call); its state_after sits on its last step. Forks happen at node-run boundaries. */
export type NodeRun = {
  idx: number;
  agent: string;
  steps: Step[];
  stateAfter: State | null;
  writes: string[];
};

export function nodeRuns(steps: Step[]): NodeRun[] {
  const byIdx = new Map<number, Step[]>();
  for (const step of [...steps].sort((a, b) => a.idx - b.idx)) {
    byIdx.set(step.node_run_idx, [...(byIdx.get(step.node_run_idx) ?? []), step]);
  }
  return [...byIdx.entries()]
    .sort(([a], [b]) => a - b)
    .map(([idx, group]) => {
      const last = group[group.length - 1];
      return { idx, agent: group[0].agent, steps: group, stateAfter: last.state_after, writes: last.writes };
    });
}

/** Agents in the order they first appear: one lane each. */
export function agentOrder(steps: Step[]): string[] {
  return [...new Set([...steps].sort((a, b) => a.idx - b.idx).map((s) => s.agent))];
}

const omit = (state: State, keys: string[]): State =>
  Object.fromEntries(Object.entries(state).filter(([k]) => !keys.includes(k)));

/** State before a node run: the previous node run's state_after. For the first node run there
 * is no earlier snapshot, so use its own state_after minus what it wrote (the initial state). */
export function stateBefore(runs: NodeRun[], idx: number): State | null {
  const position = runs.findIndex((r) => r.idx === idx);
  if (position < 0) return null;
  if (position > 0) return runs[position - 1].stateAfter;
  const first = runs[0];
  return first.stateAfter ? omit(first.stateAfter, first.writes) : null;
}

/** What the fork editor starts with: the node run's recorded output (the keys it wrote). */
export function forkPrefill(run: NodeRun): State {
  const after = run.stateAfter ?? {};
  return Object.fromEntries(run.writes.filter((k) => k in after).map((k) => [k, after[k]]));
}

/** Only the top-level keys whose value differs from the prefill: that is the edit we send. */
export function changedKeys(prefill: State, edited: State): State {
  return Object.fromEntries(
    Object.entries(edited).filter(([k, v]) => JSON.stringify(prefill[k]) !== JSON.stringify(v)),
  );
}

/** Parse the editor text into an object, or say why not. */
export function parseEdit(text: string): { ok: true; value: State } | { ok: false; error: string } {
  try {
    const value: unknown = JSON.parse(text);
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return { ok: false, error: "Must be a JSON object, like {\"key\": ...}" };
    }
    return { ok: true, value: value as State };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : "Invalid JSON" };
  }
}

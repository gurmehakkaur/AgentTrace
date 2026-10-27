import assert from "node:assert/strict";
import { test } from "node:test";
import { agentOrder, changedKeys, forkPrefill, nodeRuns, parseEdit, stateBefore } from "./runs.ts";
import type { Step } from "./types.ts";

const step = (idx: number, node_run_idx: number, agent: string, over: Partial<Step> = {}): Step => ({
  run: "r", idx, node_run_idx, agent, kind: "llm", origin: "recorded", model: "m", params: {},
  input: null, output: null, tool_name: null, tool_args: null, tool_result: null, side_effect: null,
  state_after: null, reads: [], writes: [], tokens_in: 0, tokens_out: 0, latency_ms: 0, redactions: [],
  ...over,
});

// planner (1 step) -> researcher (tool, tool, llm) -> writer
const steps = [
  step(1, 1, "planner", { writes: ["plan"], state_after: { request: "r", plan: { f: ["solved"] } } }),
  step(2, 2, "researcher", { kind: "tool" }),
  step(3, 2, "researcher", { kind: "tool" }),
  step(4, 2, "researcher", { writes: ["findings"], state_after: { request: "r", plan: { f: ["solved"] }, findings: 1 } }),
  step(5, 3, "writer", { writes: ["draft"], state_after: { request: "r", plan: { f: ["solved"] }, findings: 1, draft: "d" } }),
];

test("steps group into node runs by node_run_idx, with state_after from the last step", () => {
  const runs = nodeRuns([...steps].reverse());
  assert.deepEqual(runs.map((r) => [r.idx, r.agent, r.steps.length]), [[1, "planner", 1], [2, "researcher", 3], [3, "writer", 1]]);
  assert.deepEqual(runs[1].writes, ["findings"]);
  assert.ok(runs[1].stateAfter && "findings" in runs[1].stateAfter);
});

test("a repeated agent is a new node run, but one lane", () => {
  const loop = [...steps, step(6, 4, "critic"), step(7, 5, "writer")];
  assert.equal(nodeRuns(loop).length, 5);
  assert.deepEqual(agentOrder(loop), ["planner", "researcher", "writer", "critic"]);
});

test("state before a node run is the previous snapshot; for the first it is the initial state", () => {
  const runs = nodeRuns(steps);
  assert.deepEqual(stateBefore(runs, 2), runs[0].stateAfter);
  assert.deepEqual(stateBefore(runs, 1), { request: "r" }); // state_after minus what planner wrote
  assert.equal(stateBefore(runs, 99), null);
});

test("the fork editor starts from the keys the node wrote, and sends only what changed", () => {
  const prefill = forkPrefill(nodeRuns(steps)[0]);
  assert.deepEqual(prefill, { plan: { f: ["solved"] } });
  assert.deepEqual(changedKeys(prefill, { plan: { f: ["solved"] } }), {});
  assert.deepEqual(changedKeys(prefill, { plan: { f: ["open"] } }), { plan: { f: ["open"] } });
});

test("the editor text must be a JSON object", () => {
  assert.deepEqual(parseEdit('{"a": 1}'), { ok: true, value: { a: 1 } });
  for (const bad of ["[1]", "3", "null", "{oops", ""]) assert.equal(parseEdit(bad).ok, false);
});

test("an RCA patch pre-fills the editor so that exactly the patch is what gets sent", () => {
  const prefill = forkPrefill(nodeRuns(steps)[0]);
  const patch = { plan: { f: ["new", "open"] } };
  assert.deepEqual(changedKeys(prefill, { ...prefill, ...patch }), patch);
  assert.deepEqual(changedKeys(prefill, { ...prefill, ...{ plan: prefill.plan } }), {}); // a no-op patch sends nothing
});

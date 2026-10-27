import assert from "node:assert/strict";
import { test } from "node:test";
import { buildGraph, pos } from "./graph.ts";
import type { Experiment, Step } from "./types.ts";

const step = (over: Partial<Step>): Step => ({
  run: "r", idx: 1, node_run_idx: 1, agent: "planner", kind: "llm", origin: "recorded", model: "m", params: {},
  input: null, output: null, tool_name: null, tool_args: null, tool_result: null, side_effect: null,
  state_after: null, reads: [], writes: [], tokens_in: 0, tokens_out: 0, latency_ms: 0, redactions: [], ...over,
});
const steps = ["planner", "researcher", "writer", "critic"].map((agent, i) =>
  step({ idx: i + 1, node_run_idx: i + 1, agent, writes: ["k" + i], state_after: { ["k" + i]: i } }),
);
const exp = (over: Partial<Experiment>): Experiment => ({
  id: "e1", status: "done", parent_run: "r", fork_node_run_idx: 1, n: 8, edit_patch: {}, control: { pass: 0, total: 8 },
  treatment: { pass: 8, total: 8 }, tiles: [], stats: { fisher_p: 0.0001, wilson: { control: null, treatment: null }, label: "directional" },
  tokens_used: 0, token_ceiling: 1, error: null, ...over,
});

test("a run with no forks is one line: start, each agent in order, and the answer", () => {
  const g = buildGraph(steps, { outcome: "fail" });
  assert.equal(g.lanes.length, 1);
  assert.deepEqual(g.nodes.map((n) => n.label), ["Request", "planner", "researcher", "writer", "critic", "Wrong answer"]);
  assert.deepEqual(g.nodes.map((n) => n.col), [0, 1, 2, 3, 4, 5]);
  assert.equal(g.edges.length, 5);
  assert.equal(g.nodes.at(-1)?.tone, "bad");
});

test("a fork opens a new lane that leaves the line just before the changed agent", () => {
  const g = buildGraph(steps, { experiments: [exp({ fork_node_run_idx: 3 })], outcome: "fail" });
  assert.equal(g.lanes.length, 2);
  const spawn = g.edges.find((e) => e.kind === "spawn")!;
  assert.equal(spawn.from, "a2"); // the researcher, which ran just before the writer
  assert.equal(spawn.to, "e1:edit");
  const branch = g.nodes.filter((n) => n.lane === 1);
  assert.deepEqual(branch.map((n) => n.label), ["writer", "critic", "8 of 8 right"]);
  assert.deepEqual(branch.map((n) => n.col), [3, 4, 5]); // same columns as the original line
});

test("a fork at the first agent leaves the request itself", () => {
  const g = buildGraph(steps, { experiments: [exp({ fork_node_run_idx: 1 })] });
  assert.equal(g.edges.find((e) => e.kind === "spawn")!.from, "start");
  assert.equal(g.nodes.filter((n) => n.lane === 1).length, 5); // edited planner + 3 live + result
});

test("the branch says plainly whether the change worked", () => {
  const helped = buildGraph(steps, { experiments: [exp({})] });
  assert.equal(helped.lanes[1].tone, "good");
  const nothing = buildGraph(steps, {
    experiments: [exp({ control: { pass: 0, total: 5 }, treatment: { pass: 0, total: 5 }, stats: { fisher_p: 1, wilson: { control: null, treatment: null }, label: "d" } })],
  });
  assert.equal(nothing.lanes[1].tone, "bad");
});

test("a running fork shows progress, not a result", () => {
  const running = exp({ status: "running", tiles: [{ arm: "control", i: 0, status: "done", run_id: null, outcome: "fail" }, { arm: "treatment", i: 0, status: "running", run_id: null, outcome: null }] });
  const g = buildGraph(steps, { experiments: [running] });
  const end = g.nodes.find((n) => n.id === "e1:end")!;
  assert.equal(end.label, "Running…");
  assert.equal(end.sub, "1 of 2 runs done");
  assert.equal(end.tone, "neutral");
});

test("several forks stack as lanes, and a fork of an unknown agent is skipped", () => {
  const g = buildGraph(steps, { experiments: [exp({ id: "a", fork_node_run_idx: 1 }), exp({ id: "b", fork_node_run_idx: 4 }), exp({ id: "c", fork_node_run_idx: 99 })] });
  assert.deepEqual(g.lanes.map((l) => l.index), [0, 1, 2]);
  assert.match(g.lanes[1].label, /Fork 2: critic changed/); // a fork at a later agent sits nearer the line
});

test("positions grow to the right with the column and down with the lane", () => {
  assert.ok(pos({ lane: 0, col: 2 }).x > pos({ lane: 0, col: 1 }).x);
  assert.ok(pos({ lane: 1, col: 1 }).y > pos({ lane: 0, col: 1 }).y);
});

test("the edited node shows what was changed, before and after", () => {
  const g = buildGraph(steps, { experiments: [exp({ fork_node_run_idx: 2, edit_patch: { k1: "new" } })] });
  const edited = g.nodes.find((n) => n.id === "e1:edit")!;
  assert.equal(edited.sub, "Changed k1: 1 → new");
  assert.deepEqual(edited.change, ["k1: 1 → new"]);
});

test("an edit that changes nothing falls back to plain words", () => {
  const g = buildGraph(steps, { experiments: [exp({ fork_node_run_idx: 2, edit_patch: { k1: 1 } })] });
  assert.equal(g.nodes.find((n) => n.id === "e1:edit")!.sub, "Changed by you");
});

test("setting up a fork opens a dashed line at once, before anything runs", () => {
  const g = buildGraph(steps, { draft: { nodeRun: 2 } });
  assert.equal(g.lanes.length, 2);
  assert.equal(g.lanes[1].label, "New fork, not started");
  assert.deepEqual(g.nodes.filter((n) => n.lane === 1).map((n) => n.label), ["researcher", "writer", "critic", "Not run yet"]);
  assert.ok(g.nodes.filter((n) => n.lane === 1).every((n) => n.draft));
  assert.equal(g.edges.find((e) => e.id === "draft:spawn")!.from, "a1");
});

test("a draft for an agent that is not in the run is ignored", () => {
  assert.equal(buildGraph(steps, { draft: { nodeRun: 99 } }).lanes.length, 1);
});

test("on a fork's own run the line says which agents replayed and which ran live", () => {
  const forked = [
    step({ idx: 1, node_run_idx: 1, agent: "planner", origin: "edited", writes: ["k0"], state_after: { k0: 1 } }),
    step({ idx: 2, node_run_idx: 2, agent: "researcher", origin: "live", writes: ["k1"], state_after: { k0: 1, k1: 1 } }),
  ];
  const g = buildGraph(forked, {});
  assert.deepEqual(g.nodes.filter((n) => n.kind === "agent").map((n) => [n.origin, n.sub]), [
    ["edited", "your change is applied here"],
    ["live", "ran live, so it is sampled"],
  ]);
  const copied = buildGraph([step({ origin: "replayed", writes: ["k"], state_after: { k: 1 } })], {});
  assert.equal(copied.nodes.find((n) => n.kind === "agent")!.sub, "replayed exactly from the recording");
});

test("an ordinary recorded run keeps its plain call counts", () => {
  assert.equal(buildGraph(steps, {}).nodes.find((n) => n.id === "a1")!.origin, undefined);
});

test("a long rewritten text is described, not quoted half-way", () => {
  const long = "The brief has all the required sections and a valid JSON footer.";
  const g = buildGraph(steps, { experiments: [exp({ fork_node_run_idx: 2, edit_patch: { k1: long } })] });
  assert.equal(g.nodes.find((n) => n.id === "e1:edit")!.sub, "Changed k1");
});

test("a fork made from one of another fork's runs leaves that fork's line, where the change was made", () => {
  const withRuns = steps.map((s) => ({ ...s, run: "main" }));
  const first = exp({
    id: "e1", parent_run: "main", fork_node_run_idx: 2,
    tiles: [{ arm: "treatment", i: 0, status: "done", run_id: "attempt-1", outcome: "fail" }],
  });
  const second = exp({ id: "e2", parent_run: "attempt-1", fork_node_run_idx: 4, created_at: "later" });
  const g = buildGraph(withRuns, { experiments: [first, second] });
  const spawn = g.edges.find((e) => e.id === "e2:spawn")!;
  assert.equal(spawn.from, "e1:3"); // the writer on fork 1's own line, just before the critic
  assert.equal(g.lanes.length, 3);
  assert.equal(g.edges.find((e) => e.id === "e1:spawn")!.from, "a1"); // fork 1 still leaves the original run
});

test("a fork of a fork made at or before the first fork's change falls back to the original line", () => {
  const withRuns = steps.map((s) => ({ ...s, run: "main" }));
  const first = exp({ id: "e1", parent_run: "main", fork_node_run_idx: 3, tiles: [{ arm: "treatment", i: 0, status: "done", run_id: "a1", outcome: "fail" }] });
  const second = exp({ id: "e2", parent_run: "a1", fork_node_run_idx: 3 });
  assert.equal(buildGraph(withRuns, { experiments: [first, second] }).edges.find((e) => e.id === "e2:spawn")!.from, "a2");
});

test("a fork of a run we do not draw is left out, and a draft from a fork leaves that fork's line", () => {
  const withRuns = steps.map((s) => ({ ...s, run: "main" }));
  const stranger = exp({ id: "x", parent_run: "somewhere-else" });
  assert.equal(buildGraph(withRuns, { experiments: [stranger] }).lanes.length, 1);
  const first = exp({ id: "e1", parent_run: "main", fork_node_run_idx: 2, tiles: [] });
  const g = buildGraph(withRuns, { experiments: [first], draft: { nodeRun: 4, fromExperiment: "e1" } });
  assert.equal(g.edges.find((e) => e.id === "draft:spawn")!.from, "e1:3");
});

test("a new fork opens right under the line it came from and pushes the others down", () => {
  const at = (id: string, node: number, when: string) => exp({ id, fork_node_run_idx: node, created_at: when });
  const before = buildGraph(steps, { experiments: [at("planner1", 1, "2026-01-01"), at("writer1", 3, "2026-01-02")] });
  assert.deepEqual(before.lanes.slice(1).map((l) => l.experiment), ["writer1", "planner1"]); // later agent first
  const after = buildGraph(steps, { experiments: [at("planner1", 1, "2026-01-01"), at("writer1", 3, "2026-01-02"), at("writer2", 3, "2026-01-03")] });
  assert.deepEqual(after.lanes.slice(1).map((l) => l.experiment), ["writer2", "writer1", "planner1"]); // newest at that agent on top
  assert.deepEqual(after.lanes.map((l) => l.index), [0, 1, 2, 3]);
});

test("a fork's own forks sit directly under it, before its older siblings", () => {
  const withRuns = steps.map((s) => ({ ...s, run: "main" }));
  const a = exp({ id: "a", parent_run: "main", fork_node_run_idx: 2, created_at: "1", tiles: [{ arm: "treatment", i: 0, status: "done", run_id: "ra", outcome: "pass" }] });
  const b = exp({ id: "b", parent_run: "main", fork_node_run_idx: 2, created_at: "2", tiles: [] });
  const child = exp({ id: "child", parent_run: "ra", fork_node_run_idx: 4, created_at: "3" });
  const g = buildGraph(withRuns, { experiments: [a, b, child] });
  assert.deepEqual(g.lanes.slice(1).map((l) => l.experiment), ["b", "a", "child"]);
  const draft = buildGraph(withRuns, { experiments: [a, b], draft: { nodeRun: 2 } });
  assert.deepEqual(draft.lanes.slice(1).map((l) => l.experiment), ["draft", "b", "a"]); // the one being set up is the newest
});

test("every lane has the same agents in the same columns as the original line, so lines always line up", () => {
  const g = buildGraph(steps, { experiments: [exp({ id: "x", fork_node_run_idx: 2 })] });
  const col = (id: string) => g.nodes.find((n) => n.id === id)!.col;
  assert.equal(col("x:edit"), col("a2"));
  assert.equal(col("x:3"), col("a3"));
  assert.equal(col("x:end"), col("end"));
});

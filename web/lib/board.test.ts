import assert from "node:assert/strict";
import { test } from "node:test";
import { ballotOf, buildBoard, findingOf, laneMatches } from "./board.ts";
import type { Experiment, RunSummary, Tile } from "./types.ts";

const run = (id: string, at: string, over: Partial<RunSummary> = {}): RunSummary => ({ id, workflow: "wf", kind: "recorded", status: "ok", outcome: "fail", started_at: at, ...over });
const fork = (id: string, parent: string, at: string, over: Partial<Experiment & { fork_agent: string }> = {}): Experiment & { fork_agent?: string } => ({
  id, status: "done", parent_run: parent, fork_node_run_idx: 1, n: 5, edit_patch: {}, control: { pass: 0, total: 5 }, treatment: { pass: 5, total: 5 }, tiles: [],
  stats: { fisher_p: 0.008, wilson: { control: null, treatment: null }, label: "d" }, tokens_used: 0, token_ceiling: 1, error: null, created_at: at, fork_agent: "planner", ...over,
});
const NONE = { fisher_p: 1, wilson: { control: null, treatment: null }, label: "d" };
const tile = (arm: Tile["arm"], i: number, outcome: Tile["outcome"], status: Tile["status"] = "done"): Tile => ({ arm, i, status, run_id: null, outcome });

test("one lane per recorded run, newest first, and a fork's own attempts are not lanes", () => {
  const b = buildBoard([run("a", "2026-01-01T00:00:00Z"), run("b", "2026-01-02T00:00:00Z"), run("f", "2026-01-03T00:00:00Z", { kind: "fork" })], []);
  assert.deepEqual(b.lanes.map((l) => l.run.id), ["b", "a"]);
  assert.equal(b.stats.runs, 2);
});

test("a ballot has one dot per live run, in order, one row without the change and one with it", () => {
  const e = fork("e", "a", "2026-01-01T00:00:00Z", {
    tiles: [tile("treatment", 1, "pass"), tile("control", 0, "fail"), tile("control", 1, "error"), tile("treatment", 0, "fail"), tile("control", 2, null, "running")],
  });
  assert.deepEqual(ballotOf(e), { without: ["wrong", "error", "open"], with: ["wrong", "right"] });
});

test("an older fork without tiles falls back to its counts", () => {
  assert.deepEqual(ballotOf(fork("e", "a", "2026-01-01T00:00:00Z", { control: { pass: 1, total: 3 }, treatment: { pass: 3, total: 3 } })), {
    without: ["right", "wrong", "wrong"], with: ["right", "right", "right"],
  });
});

test("forks sit on their run in the order they were tried and carry a plain verdict", () => {
  const b = buildBoard([run("a", "2026-01-01T10:00:00Z")], [
    fork("e2", "a", "2026-01-01T10:20:00Z", { fork_agent: "critic", control: { pass: 0, total: 3 }, treatment: { pass: 0, total: 3 }, n: 3, stats: NONE }),
    fork("e1", "a", "2026-01-01T10:04:00Z"),
  ]);
  const lane = b.lanes[0];
  assert.deepEqual(lane.forks.map((f) => [f.number, f.agent]), [[1, "planner"], [2, "critic"]]);
  assert.deepEqual(lane.forks.map((f) => f.result), ["5 of 5 right", "0 of 3 right"]);
  assert.deepEqual(lane.forks.map((f) => f.tone), ["good", "bad"]);
  assert.equal(lane.forks[1].verdict, "The change made no difference. This step is probably not the cause.");
  assert.equal(lane.forks[0].href, "/runs/a?fork=e1");
});

test("a lane says plainly whether its run got fixed", () => {
  const b = buildBoard(
    [run("fixed", "2026-01-04T00:00:00Z"), run("open", "2026-01-03T00:00:00Z"), run("none", "2026-01-02T00:00:00Z"), run("right", "2026-01-01T00:00:00Z", { outcome: "pass" })],
    [fork("e1", "fixed", "2026-01-04T01:00:00Z"), fork("e2", "open", "2026-01-03T01:00:00Z", { control: { pass: 0, total: 5 }, treatment: { pass: 0, total: 5 }, stats: NONE })],
  );
  assert.deepEqual(b.lanes.map((l) => [l.status, l.statusText]), [
    ["fixed", "Fixed by fork 1"], ["open", "Not fixed yet"], ["none", "Nothing tried yet"], ["right", "Gave the right answer"],
  ]);
  assert.deepEqual(b.stats, { runs: 4, forks: 2, worked: 1, fixedRuns: 1, failedRuns: 3 });
  const names = (f: "all" | "wrong" | "fixed" | "right") => b.lanes.filter((l) => laneMatches(l, f)).map((l) => l.run.id);
  assert.deepEqual([names("all").length, names("wrong"), names("fixed"), names("right")], [4, ["open", "none"], ["fixed"], ["right"]]);
});

test("the best fix is the one with the highest right-rate, and the latest is the newest finished fork", () => {
  const b = buildBoard([run("a", "2026-01-01T00:00:00Z")], [
    fork("weak", "a", "2026-01-01T01:00:00Z", { fork_agent: "writer", treatment: { pass: 4, total: 5 } }),
    fork("strong", "a", "2026-01-01T02:00:00Z", { fork_agent: "planner", control: { pass: 0, total: 8 }, treatment: { pass: 8, total: 8 }, n: 8 }),
    fork("busy", "a", "2026-01-01T03:00:00Z", { status: "running" }),
  ]);
  assert.deepEqual(b.best && [b.best.fork.agent, b.best.fork.id, b.best.fix], ["planner", "strong", true]);
  assert.equal(b.latest?.fork.id, "strong");
  assert.equal(buildBoard([run("a", "2026-01-01T00:00:00Z")], []).best, null);
});

test("a fork made from one of another fork's runs stays on the run the chain started from", () => {
  const first = fork("e1", "a", "2026-01-01T01:00:00Z", { tiles: [{ arm: "treatment", i: 0, status: "done", run_id: "attempt", outcome: "fail" }] });
  const inner = fork("e2", "attempt", "2026-01-01T02:00:00Z", { fork_agent: "critic" });
  const lane = buildBoard([run("a", "2026-01-01T00:00:00Z")], [first, inner]).lanes[0];
  assert.deepEqual(lane.forks.map((f) => [f.id, f.nested]), [["e1", false], ["e2", true]]);
});

test("a fork still running says so and is not counted as a fix", () => {
  const b = buildBoard([run("a", "2026-01-01T00:00:00Z")], [fork("e1", "a", "2026-01-01T01:00:00Z", { status: "running" })]);
  assert.equal(b.lanes[0].forks[0].result, "Running…");
  assert.equal(b.stats.worked, 0);
  assert.equal(b.latest, null);
});

test("the opening finding says what is wrong and what has been done about it", () => {
  const A = "2026-01-01T00:00:00Z";
  const one = (forks: Parameters<typeof buildBoard>[1], runs = [run("a", A), run("b", "2026-01-02T00:00:00Z", { outcome: "pass" })]) => findingOf(buildBoard(runs, forks));
  assert.deepEqual(one([]), { first: "1 of 2 runs gave a wrong answer.", second: "You have not tried a fork yet. Open a wrong run, change what an agent wrote, and fork it." });
  assert.equal(one([fork("e", "a", A, { control: { pass: 0, total: 8 }, treatment: { pass: 8, total: 8 }, n: 8 })]).second, "Changing the planner took it from 0 of 8 right to 8 of 8.");
  assert.equal(one([fork("e", "a", A, { fork_agent: "critic", treatment: { pass: 0, total: 5 }, stats: NONE })]).second, "Nothing you tried has fixed it yet. Last: the critic.");
  assert.deepEqual(findingOf(buildBoard([run("a", A, { outcome: "pass" })], [])), { first: "Your run gave the right answer.", second: "Nothing to fix right now." });
});

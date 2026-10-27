import assert from "node:assert/strict";
import { test } from "node:test";
import { buildBoard } from "./board.ts";
import { buildRows, domainOf, RUN_COLORS, ticksOf } from "./gantt.ts";
import type { Experiment, RunSummary } from "./types.ts";

const run = (id: string, at: string, over: Partial<RunSummary> = {}): RunSummary => ({ id, workflow: "Renewal brief", kind: "recorded", status: "ok", outcome: "fail", started_at: at, ended_at: at, ...over });
const fork = (id: string, parent: string, at: string, over: Partial<Experiment & { fork_agent: string }> = {}): Experiment & { fork_agent?: string } => ({
  id, status: "done", parent_run: parent, fork_node_run_idx: 1, n: 5, edit_patch: {}, control: { pass: 0, total: 5 }, treatment: { pass: 5, total: 5 }, tiles: [],
  stats: { fisher_p: 0.008, wilson: { control: null, treatment: null }, label: "d" }, tokens_used: 0, token_ceiling: 1, error: null, created_at: at, fork_agent: "planner", ...over,
});

const board = () => buildBoard(
  [run("c", "2026-01-02T09:00:00Z", { workflow: "Support triage", outcome: "pass" }), run("b", "2026-01-01T12:00:00Z"), run("a", "2026-01-01T10:00:00Z", { ended_at: "2026-01-01T10:03:00Z" })],
  [fork("e1", "a", "2026-01-01T10:20:00Z"), fork("e2", "a", "2026-01-01T10:40:00Z", { fork_agent: "critic" })],
);

test("rows are numbered like a sheet: a group, then its runs oldest first, each followed by its forks", () => {
  const rows = buildRows(board(), "all");
  assert.deepEqual(rows.map((r) => [r.n, r.kind, r.kind === "group" ? r.label : r.kind === "run" ? r.lane.run.id : r.fork.id]), [
    [1, "group", "Renewal brief"], [2, "run", "a"], [3, "fork", "e1"], [4, "fork", "e2"], [5, "run", "b"], [6, "group", "Support triage"], [7, "run", "c"],
  ]);
  assert.equal(rows[0].kind === "group" && rows[0].sub, "2 runs · 1 fixed · 1 wrong");
  assert.deepEqual(rows[2].kind === "fork" && rows[2].parent, 1);
});

test("a run keeps its colour when the list is filtered, and every run has its own until the palette is used up", () => {
  const all = buildRows(board(), "all").filter((r) => r.kind === "run");
  const wrong = buildRows(board(), "wrong").filter((r) => r.kind === "run");
  const colour = (rows: typeof all, id: string) => rows.find((r) => r.kind === "run" && r.lane.run.id === id)?.kind === "run" && (rows.find((r) => r.kind === "run" && r.lane.run.id === id) as { color: string }).color;
  assert.equal(colour(all, "b"), colour(wrong, "b"));
  assert.equal(new Set(all.map((r) => (r as { color: string }).color)).size, 3);
  assert.ok(RUN_COLORS.every((c) => !/^#(f2877a|7ad19b)$/i.test(c)));
});

test("filters drop runs and the groups left empty", () => {
  const names = (f: "wrong" | "fixed" | "right") => buildRows(board(), f).filter((r) => r.kind !== "fork").map((r) => (r.kind === "group" ? r.label : r.kind === "run" ? r.lane.run.id : ""));
  assert.deepEqual(names("right"), ["Support triage", "c"]);
  assert.deepEqual(names("fixed"), ["Renewal brief", "a"]);
  assert.deepEqual(names("wrong"), ["Renewal brief", "b"]);
});

test("the time range holds every run and fork with air on both sides, and never collapses to nothing", () => {
  const rows = buildRows(board(), "all");
  const { min, max } = domainOf(rows);
  assert.ok(min < Date.parse("2026-01-01T10:00:00Z") && max > Date.parse("2026-01-02T09:00:00Z"));
  const one = domainOf(buildRows(buildBoard([run("a", "2026-01-01T10:00:00Z")], []), "all"));
  assert.ok(one.max - one.min >= 30 * 60_000);
});

test("axis ticks rise, stay inside the range and are never closer than the gap", () => {
  const min = Date.parse("2026-01-01T09:00:00Z");
  for (const span of [40 * 60_000, 6 * 3600_000, 3 * 86400_000, 90 * 86400_000]) {
    const { ticks } = ticksOf(min, min + span, 800);
    assert.ok(ticks.length >= 1);
    ticks.forEach((t, i) => {
      assert.ok(t.t >= min && t.t <= min + span);
      if (i) assert.ok((t.t - ticks[i - 1].t) * (800 / span) >= 84 - 0.001);
    });
  }
});

import assert from "node:assert/strict";
import { test } from "node:test";
import { diffState } from "./diff.ts";

test("a new nested object is listed leaf by leaf, so the planted filter is its own line", () => {
  const changes = diffState(
    { request: "r" },
    { request: "r", plan: { account_id: "acct-1", ticket_filter: { status: ["solved"] } } },
  );
  assert.deepEqual(
    changes.map((c) => [c.path, c.kind]),
    [["plan.account_id", "added"], ["plan.ticket_filter.status", "added"]],
  );
  assert.deepEqual(changes[1].after, ["solved"]);
});

test("changed and removed leaves carry before and after", () => {
  const changes = diffState({ a: 1, b: { c: [1] }, gone: true }, { a: 2, b: { c: [1, 2] } });
  assert.deepEqual(changes, [
    { path: "a", kind: "changed", before: 1, after: 2 },
    { path: "b.c", kind: "changed", before: [1], after: [1, 2] },
    { path: "gone", kind: "removed", before: true },
  ]);
});

test("identical states and null inputs produce no changes", () => {
  assert.deepEqual(diffState({ a: { b: 1 } }, { a: { b: 1 } }), []);
  assert.deepEqual(diffState(null, null), []);
  assert.equal(diffState(null, { a: 1 }).length, 1);
});

test("an empty object counts as a value, not as nothing", () => {
  assert.deepEqual(diffState({}, { filter: {} }), [{ path: "filter", kind: "added", after: {} }]);
});

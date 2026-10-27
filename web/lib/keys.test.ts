import assert from "node:assert/strict";
import { test } from "node:test";
import { describeScopes, KEY_KINDS, usage } from "./keys.ts";

test("a key says in words what it can do, and an old key with no scopes can only send runs", () => {
  assert.equal(describeScopes(["ingest"]), "send runs");
  assert.equal(describeScopes(["read", "spend"]), "read and spend tokens");
  assert.equal(describeScopes(undefined), "send runs");
  assert.equal(describeScopes([]), "send runs");
});

test("only the kinds that can cost tokens carry the spend scope, and each kind says how to use it", () => {
  assert.deepEqual(KEY_KINDS.filter((k) => k.scopes.includes("spend")).map((k) => k.id), ["spend"]);
  const [ingest, worker, read] = KEY_KINDS;
  assert.equal(usage(ingest, "k", "https://api"), "");
  assert.match(usage(worker, "at_live_x", "https://api"), /safe_to_rerun=True/);
  assert.match(usage(read, "at_live_x", "https://api"), /AGENTTRACE_KEY=at_live_x/);
});

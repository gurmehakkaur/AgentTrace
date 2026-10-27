import assert from "node:assert/strict";
import { test } from "node:test";
import { EXAMPLES, exampleFor } from "./examples.ts";

test("the examples have distinct addresses, start with the original saved run, and each says what it shows", () => {
  assert.equal(new Set(EXAMPLES.map((e) => e.href)).size, EXAMPLES.length);
  assert.equal(EXAMPLES[0].href, "/demo");
  assert.ok(EXAMPLES.every((e) => e.href.startsWith("/demo") && e.label.length > 5 && e.blurb.length > 20));
});

test("an unknown address falls back to the first example", () => {
  assert.equal(exampleFor("/demo/worker").label, "Forking your own agents");
  assert.equal(exampleFor("/demo/nope").href, "/demo");
});

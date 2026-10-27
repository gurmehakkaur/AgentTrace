import assert from "node:assert/strict";
import { test } from "node:test";
import { verdictFor } from "./verdict.ts";

test("a big, significant gap is called a fix", () => {
  assert.equal(verdictFor({ pass: 0, total: 8 }, { pass: 8, total: 8 }, 0.0001)?.text, "The change fixed it.");
});

test("a significant but partial gap is called a help, not a fix", () => {
  assert.equal(verdictFor({ pass: 0, total: 10 }, { pass: 5, total: 10 }, 0.01)?.tone, "good");
  assert.match(verdictFor({ pass: 0, total: 10 }, { pass: 5, total: 10 }, 0.01)!.text, /did not fix every run/);
});

test("a gap that could be luck is only a hint", () => {
  const v = verdictFor({ pass: 0, total: 3 }, { pass: 2, total: 3 }, 0.2)!;
  assert.equal(v.tone, "neutral");
  assert.match(v.text, /too few runs/);
});

test("no gap means the step is probably not the cause", () => {
  assert.match(verdictFor({ pass: 0, total: 5 }, { pass: 0, total: 5 }, 1)!.text, /no difference/);
});

test("worse is said plainly, and an empty arm gives no verdict", () => {
  assert.match(verdictFor({ pass: 3, total: 5 }, { pass: 1, total: 5 }, 0.5)!.text, /worse/);
  assert.equal(verdictFor({ pass: 0, total: 0 }, { pass: 0, total: 5 }, null), null);
});

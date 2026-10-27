import assert from "node:assert/strict";
import { test } from "node:test";
import { loadDemo } from "./demo.ts";
import { demoSnapshot } from "./demo-snapshot.ts";

const live = { run: { id: "live-run" }, rca: null, experiments: [] };
const answer = (body: unknown, ok = true) => (async () => ({ ok, json: async () => body })) as unknown as typeof fetch;

test("a live answer is used when the API replies in time", async () => {
  assert.equal(((await loadDemo(answer(live))) as unknown as { run: { id: string } }).run.id, "live-run");
});

test("an API that is asleep, down or answers badly shows the saved copy at once, never nothing", async () => {
  const saved = demoSnapshot as { run: { steps: unknown[] } };
  for (const f of [(async () => { throw new TypeError("fetch failed"); }) as unknown as typeof fetch, answer({}, false)]) {
    const demo = (await loadDemo(f)) as unknown as { run: { steps: unknown[] } };
    assert.equal(demo, saved);
    assert.ok(demo.run.steps.length > 0);
  }
});

test("the wait is short: a reply that never comes is given up on within the time asked", async () => {
  // A real request keeps the process alive while it waits; the timeout on its own does not, so the stand-in does too.
  const never = ((_: unknown, init?: RequestInit) => new Promise((_res, rej) => {
    const hold = setInterval(() => {}, 10);
    init?.signal?.addEventListener("abort", () => { clearInterval(hold); rej(new Error("timed out")); });
  })) as unknown as typeof fetch;
  const started = Date.now();
  await loadDemo(never, 50);
  assert.ok(Date.now() - started < 1000);
});

test("the saved copy holds a failing run, its steps and the featured experiments", () => {
  const d = demoSnapshot as { run: { outcome: string; steps: { agent: string }[] }; experiments: { control: unknown; treatment: unknown }[] };
  assert.equal(d.run.outcome, "fail");
  assert.ok(d.run.steps.some((s) => s.agent === "planner"));
  assert.ok(d.experiments.length >= 1 && d.experiments.every((e) => e.control && e.treatment));
});

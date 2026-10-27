import assert from "node:assert/strict";
import { test } from "node:test";
import { checkChips, headline } from "./checks.ts";

test("the renewal demo keeps its three checks, and a run from elsewhere shows only its own", () => {
  assert.deepEqual(checkChips({ open_tickets_ok: false, pipeline_ok: true, critic_loop_ok: true }).map((c) => [c.label, c.ok]), [
    ["Open tickets", false], ["Pipeline total", true], ["Review loop", true],
  ]);
  const own = checkChips({ verdict: { kind: "code", name: "says_five", passed: false, reason: "said 0" } });
  assert.deepEqual(own, [{ label: "Your check says_five", ok: false, note: "said 0" }]);
});

test("a check that could not run is neither right nor wrong", () => {
  const [chip] = checkChips({ verdict: { kind: "code", name: "c", passed: null, reason: "The check itself failed: KeyError" } });
  assert.equal(chip.ok, null);
  assert.match(chip.label, /could not run/);
});

test("a run nobody has judged is not called right", () => {
  assert.equal(headline("pass"), "This run gave the right answer.");
  assert.equal(headline("fail"), "This run gave a wrong answer.");
  assert.equal(headline("error"), "This run gave a wrong answer.");
  assert.equal(headline(undefined), "This run has no verdict yet.");
  assert.equal(headline(null), "This run has no verdict yet.");
  assert.deepEqual(checkChips(undefined), []);
});

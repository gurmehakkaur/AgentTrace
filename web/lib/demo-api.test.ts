import assert from "node:assert/strict";
import { test } from "node:test";
import { makeDemoApi } from "./demo-api.ts";

const T = 1_760_000_000_000;

test("making a key adds it with the scopes asked for, and the key shown is plainly not a real one", () => {
  const api = makeDemoApi(() => T);
  const made = api("POST", "/v1/keys", { scopes: ["read", "spend"] }).json as { key: string; scopes: string[] };
  assert.deepEqual(made.scopes, ["read", "spend"]);
  assert.match(made.key, /not-real/);
  const listed = api("GET", "/v1/keys?k=2", null).json as { scopes: string[] }[];
  assert.equal(listed.length, 4);
  assert.deepEqual(listed[0].scopes, ["read", "spend"]);
});

test("a webhook can be added, tested and removed, and a signed one gets a secret once", () => {
  const api = makeDemoApi(() => T);
  assert.deepEqual(api("POST", "/v1/webhooks", { kind: "slack", include_suspect: false }).json, {});
  assert.match((api("POST", "/v1/webhooks", { kind: "generic" }).json as { secret: string }).secret, /example/);
  const hooks = api("GET", "/v1/webhooks", null).json as { id: string; revoked_at: string | null }[];
  assert.equal(hooks.length, 3);
  assert.deepEqual(api("POST", `/v1/webhooks/${hooks[0].id}/test`, null).json, { delivered: true, status: 200 });
  api("DELETE", `/v1/webhooks/${hooks[0].id}`, null);
  assert.ok((api("GET", "/v1/webhooks", null).json as { revoked_at: string | null }[])[0].revoked_at);
});

test("anything else says plainly that it is an example", () => {
  const out = makeDemoApi(() => T)("POST", "/v1/runs/import", {});
  assert.equal(out.status, 404);
  assert.match((out.json as { detail: string }).detail, /example/);
});

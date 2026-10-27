/** What the public "Keys, alerts and agents" example answers when the Connect page asks the API. Nothing is saved
 * anywhere: it lives in the page until it is closed. Times are made when asked, never at load, so a page can be
 * built ahead of time. */

type Row = Record<string, unknown>;
export type Answer = { status: number; json: unknown };

export function makeDemoApi(now: () => number = Date.now) {
  const iso = (minAgo: number) => new Date(now() - minAgo * 60_000).toISOString();
  const state = {
    keys: [
      { id: "k1", prefix: "at_live_AbCd", scopes: ["ingest"], created_at: iso(5000), last_seen_at: iso(3), revoked_at: null },
      { id: "k2", prefix: "at_live_Wk9x", scopes: ["worker"], created_at: iso(3000), last_seen_at: iso(0.2), revoked_at: null },
      { id: "k3", prefix: "at_live_Ag7q", scopes: ["read", "spend"], created_at: iso(900), last_seen_at: null, revoked_at: null },
    ] as Row[],
    hooks: [
      { id: "w1", kind: "slack", host: "hooks.slack.com", ends: "xK2f", include_suspect: true, on_forks: true, created_at: iso(800), revoked_at: null },
    ] as Row[],
    next: 10,
  };

  return function answer(method: string, path: string, body: Row | null): Answer {
    const p = path.replace(/[?&]k=\d+/, "");
    if (method === "GET" && p === "/v1/keys") return { status: 200, json: state.keys };
    if (method === "POST" && p === "/v1/keys") {
      const scopes = (body?.scopes as string[] | undefined) ?? ["ingest"];
      const key = `at_live_EXAMPLE${(state.next++).toString(36)}-this-key-is-not-real-and-works-nowhere`;
      state.keys = [{ id: `k${state.next}`, prefix: key.slice(0, 12), scopes, created_at: iso(0), last_seen_at: null, revoked_at: null }, ...state.keys];
      return { status: 201, json: { key, prefix: key.slice(0, 12), scopes } };
    }
    if (method === "DELETE" && p.startsWith("/v1/keys/")) {
      const id = p.split("/").pop();
      state.keys = state.keys.map((k) => (k.id === id ? { ...k, revoked_at: iso(0) } : k));
      return { status: 200, json: { id } };
    }
    if (method === "GET" && p === "/v1/webhooks") return { status: 200, json: state.hooks };
    if (method === "POST" && p === "/v1/webhooks") {
      const kind = body?.kind as string;
      state.hooks = [{ id: `w${state.next++}`, kind, host: kind === "slack" ? "hooks.slack.com" : "alerts.example.com", ends: "Q9zT", include_suspect: !!body?.include_suspect, on_forks: body?.on_forks !== false, created_at: iso(0), revoked_at: null }, ...state.hooks];
      return { status: 201, json: kind === "generic" ? { secret: "this-secret-is-an-example" } : {} };
    }
    if (method === "DELETE" && p.startsWith("/v1/webhooks/")) {
      const id = p.split("/").pop();
      state.hooks = state.hooks.map((h) => (h.id === id ? { ...h, revoked_at: iso(0) } : h));
      return { status: 200, json: { id } };
    }
    if (method === "POST" && /^\/v1\/webhooks\/\w+\/test$/.test(p)) return { status: 200, json: { delivered: true, status: 200 } };
    return { status: 404, json: { detail: "This is an example: that part is not available here. Sign in to use it." } };
  };
}

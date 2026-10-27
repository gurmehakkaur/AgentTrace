/** What a key may do. An admin picks this when making the key: a key that only sends runs cannot read them, and
 * only a key with `spend` can cost tokens. */
export type KeyKind = { id: string; label: string; scopes: string[]; hint: string };

export const KEY_KINDS: KeyKind[] = [
  { id: "ingest", label: "Send runs", scopes: ["ingest"], hint: "For your code that records runs, and for an OpenTelemetry exporter." },
  { id: "worker", label: "Run forks for me", scopes: ["worker"], hint: "For a worker next to your code. It runs your agents again when you fork one of your runs." },
  { id: "read", label: "An agent that reads", scopes: ["read"], hint: "For an assistant or the command line to look at failed runs. It cannot cost tokens." },
  { id: "spend", label: "An agent that can test fixes", scopes: ["read", "spend"], hint: "As above, and it can ask which step broke a run and start experiments. These cost tokens, within the same limits as a person." },
];

const NAMES: Record<string, string> = { ingest: "send runs", worker: "run forks", read: "read", spend: "spend tokens" };

/** "send runs", "read and spend tokens". A key made before scopes existed has none: it can only send runs. */
export function describeScopes(scopes: string[] | undefined): string {
  const names = (scopes && scopes.length ? scopes : ["ingest"]).map((s) => NAMES[s] ?? s);
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0];
}

/** The few lines that show how to use a key of this kind. */
export function usage(kind: KeyKind, key: string, apiUrl: string): string {
  if (kind.id === "worker") {
    return `from agenttrace_sdk import Worker

worker = Worker("${apiUrl}", "${key}")
worker.register("my_workflow", resume, oracle=check, safe_to_rerun=True)  # see docs/integrations.md
asyncio.run(worker.run_forever())`;
  }
  if (kind.id === "read" || kind.id === "spend") {
    return `export AGENTTRACE_URL=${apiUrl}
export AGENTTRACE_KEY=${key}
agenttrace failed                    # runs that came out wrong
agenttrace mcp                       # or serve these to an assistant over MCP`;
  }
  return "";
}

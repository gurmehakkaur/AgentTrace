import type { State } from "./types";

export type Change = {
  path: string;
  kind: "added" | "removed" | "changed";
  before?: unknown;
  after?: unknown;
};

const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** Objects are walked to their leaves (so `plan.ticket_filter.status` is its own line);
 * arrays and scalars are leaves. */
function leaves(value: unknown, path: string, out: Map<string, unknown>) {
  if (isObject(value) && Object.keys(value).length > 0) {
    for (const [key, child] of Object.entries(value)) leaves(child, path ? `${path}.${key}` : key, out);
  } else {
    out.set(path, value);
  }
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** What changed between two state snapshots, one entry per differing leaf, sorted by path. */
export function diffState(before: State | null, after: State | null): Change[] {
  const a = new Map<string, unknown>();
  const b = new Map<string, unknown>();
  leaves(before ?? {}, "", a);
  leaves(after ?? {}, "", b);
  a.delete("");
  b.delete("");

  const changes: Change[] = [];
  for (const [path, value] of b) {
    if (!a.has(path)) changes.push({ path, kind: "added", after: value });
    else if (!same(a.get(path), value)) changes.push({ path, kind: "changed", before: a.get(path), after: value });
  }
  for (const [path, value] of a) if (!b.has(path)) changes.push({ path, kind: "removed", before: value });
  return changes.sort((x, y) => x.path.localeCompare(y.path));
}

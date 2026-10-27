import type { Loaded } from "@/lib/use-api-data";

/** The loading and error states every data page shares; renders `children(data)` when loaded. */
export function LoadState<T>({
  state, notFound, children,
}: { state: Loaded<T>; notFound?: string; children: (data: T) => React.ReactNode }) {
  if (state.status === "loading") return <p className="font-mono text-sm">Loading…</p>;
  if (state.status === "error") {
    const message =
      state.code === 403
        ? "Pick or create an organization with the switcher above: each organization is a workspace."
        : state.code === 404
          ? (notFound ?? "Not found in this workspace. If you switched organizations, go back to Runs.")
          : `Could not load (${state.code || "network"}): ${state.message}`;
    return (
      <p role="alert" className="rounded-lg border border-bad/40 p-4 text-sm text-bad">
        {message}
      </p>
    );
  }
  return <>{children(state.data)}</>;
}

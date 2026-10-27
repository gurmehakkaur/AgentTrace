import { demoSnapshot } from "./demo-snapshot.ts";
import type { Benchmark, Experiment, RcaReport, Run } from "./types";

/** What GET /v1/public/demo returns: the saved failing run, its report and the featured experiments. */
export type Demo = {
  run: Run;
  rca: RcaReport | null;
  experiments: (Experiment & { role: "decoy" | "hero" | null; benchmark?: Benchmark | null })[];
};

const API_URL = process.env.NEXT_PUBLIC_API_URL;

/** The saved demo, read on the server so the first paint already holds the real run and results.
 *
 * A free-plan API that has gone to sleep takes about a minute to wake, and its first answer can take ten seconds
 * more. A visitor must not wait for that, so the live answer gets a few seconds, and after that the page shows
 * the saved copy of the same stored results (lib/demo-snapshot.ts, made by scripts/snapshot-demo.mjs). */
export async function loadDemo(fetchLive: typeof fetch = fetch, waitMs = 4000): Promise<Demo | null> {
  try {
    const res = await fetchLive(`${API_URL}/v1/public/demo`, { signal: AbortSignal.timeout(waitMs) });
    if (res.ok) return (await res.json()) as Demo;
  } catch {
    // asleep, slow or down: fall through to the saved copy
  }
  return demoSnapshot as Demo;
}

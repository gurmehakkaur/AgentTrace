import Link from "next/link";
import { BenchmarkTable } from "@/components/benchmark-table";
import { JsonBlock } from "@/components/json-block";
import { formatP, formatTokens, percent, shortId } from "@/lib/format";
import { verdictFor } from "@/lib/verdict";
import type { Experiment, Tile } from "@/lib/types";

export const isFinished = (e: Experiment) => !["queued", "running"].includes(e.status);

export function ExperimentView({
  experiment: e, title, blurb, runHref = (id) => `/runs/${id}`, level = 1,
}: {
  experiment: Experiment;
  title?: string;
  blurb?: string;
  runHref?: (runId: string) => string; // where a run link points (the demo has its own public pages)
  level?: 1 | 2;
}) {
  const Heading = level === 1 ? "h1" : "h2";
  const finished = e.tiles.filter((t) => t.status === "done" || t.status === "skipped").length;
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <Heading className="text-2xl font-semibold tracking-tight">{title ?? "Test result"}</Heading>
        {blurb && <p className="text-muted">{blurb}</p>}
        <p className="text-sm text-muted">
          Started from{" "}
          <Link href={runHref(e.parent_run)} className="font-mono underline underline-offset-4">
            run {shortId(e.parent_run)}
          </Link>
          , changing agent step {e.fork_node_run_idx}. {e.n} runs without the change, {e.n} with it.
        </p>
      </header>

      <ResultCard experiment={e} finished={finished} />

      <section aria-label="Runs">
        <h2 className="mb-2 text-base font-medium text-ink">Every run</h2>
        <div className="flex flex-col gap-3">
          {(["control", "treatment"] as const).map((arm) => (
            <div key={arm} className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="w-40 shrink-0 text-sm font-medium">{arm === "control" ? "Without the change" : "With the change"}</span>
              <ul className="flex flex-wrap gap-2">
                {e.tiles.filter((t) => t.arm === arm).map((t) => (
                  <li key={`${t.arm}-${t.i}`}>
                    <TileCell tile={t} runHref={runHref} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted">
          Select a square to open that run.
        </p>
      </section>

      {e.benchmark && <BenchmarkTable benchmark={e.benchmark} />}

      <details className="rounded-lg border border-line p-3">
        <summary className="cursor-pointer text-sm font-medium">What was changed</summary>
        <div className="mt-3">
          <JsonBlock label="The new value the agent was given" value={e.edit_patch} />
        </div>
      </details>
    </div>
  );
}

function ResultCard({ experiment: e, finished }: { experiment: Experiment; finished: number }) {
  const running = !isFinished(e);
  const { control: c, treatment: t, stats } = e;
  const verdict = running ? null : verdictFor(c, t, stats.fisher_p);
  return (
    <section
      aria-live="polite"
      aria-label="Result"
      className="rounded-2xl border border-line bg-frame p-5 sm:p-8"
    >
      {verdict && (
        <p className={`text-2xl font-semibold sm:text-3xl ${verdict.tone === "good" ? "text-good" : verdict.tone === "bad" ? "text-bad" : ""}`}>
          {verdict.text}
        </p>
      )}
      <p className="mt-4 text-base text-ink">How often the answer came out right</p>
      <div className="mt-2 grid grid-cols-2 gap-4">
        <div>
          <p className="text-sm text-muted">Without the change</p>
          <p className="text-4xl font-bold tabular-nums sm:text-6xl">{c.pass}/{c.total}</p>
        </div>
        <div>
          <p className="text-sm text-muted">With the change</p>
          <p className="text-4xl font-bold tabular-nums sm:text-6xl">{t.pass}/{t.total}</p>
        </div>
      </div>
      <p className="mt-3 text-base sm:text-lg">
        {stats.fisher_p === null ? (
          "The p-value appears once both sides have finished a run"
        ) : (
          <>
            Fisher exact p {stats.fisher_p < 0.001 ? "" : "≈ "}
            <b>{formatP(stats.fisher_p)}</b> · {stats.label}
          </>
        )}
      </p>
      {stats.wilson.control && stats.wilson.treatment && (
        <p className="mt-1 text-sm text-muted">
          95% intervals: without {percent(stats.wilson.control[0])}–{percent(stats.wilson.control[1])}, with{" "}
          {percent(stats.wilson.treatment[0])}–{percent(stats.wilson.treatment[1])}. Small N shows direction, not proof.
        </p>
      )}

      {running && e.mode === "worker" && e.status === "queued" && (
        <p className="mt-4 rounded-lg border border-line bg-tile px-3 py-2 text-sm">
          {e.workers_online
            ? "Your worker is connected and will take the first job in a few seconds."
            : "Waiting for your worker, and none has asked for a job in the last minute."}{" "}
          This run is forked by the worker you run next to your code, because only your code can re-run your agents.
          {!e.workers_online && " Start it with a key made for it on the Connect page."}
        </p>
      )}
      {running && (
        <div className="mt-4">
          <p className="text-sm font-medium">
            Running: {finished} of {e.tiles.length} runs finished
          </p>
          <div className="mt-1 h-2 overflow-hidden rounded bg-tile">
            <div className="h-full bg-ink transition-all" style={{ width: `${(finished / e.tiles.length) * 100}%` }} />
          </div>
        </div>
      )}
      {e.status === "capped" && (
        <p className="mt-4 text-sm font-medium text-orange-800">
          Stopped early at the token ceiling ({formatTokens(e.token_ceiling)}); only finished runs are counted.
        </p>
      )}
      {e.status === "error" && (
        <p role="alert" className="mt-4 text-sm font-medium text-bad">
          The experiment failed{e.error ? ` (${e.error})` : ""}. Counts show the runs that finished.
        </p>
      )}
      <p className="mt-4 text-xs text-muted">
        Earlier steps replay exactly from the recording. Later steps ran live and are sampled, so each arm runs N
        times. {formatTokens(e.tokens_used)} tokens.
      </p>
    </section>
  );
}

const TILE_BASE = "flex h-11 w-11 items-center justify-center rounded-md text-xs font-medium";

export function TileCell({ tile, runHref }: { tile: Tile; runHref: (runId: string) => string }) {
  let className = `${TILE_BASE} bg-tile text-muted`;
  let word = "";
  let label = "waiting";
  if (tile.status === "running") {
    className = `${TILE_BASE} animate-pulse bg-run-2 text-ink`;
    word = "running";
    label = "running";
  } else if (tile.status === "skipped") {
    className = `${TILE_BASE} border border-dashed border-ink/40 text-muted`;
    word = "skipped";
    label = "skipped";
  } else if (tile.status === "done") {
    // Words, not colour alone: right, wrong, or crashed.
    const map = {
      pass: ["bg-good-solid text-white", "right", "gave the right answer"],
      fail: ["bg-bad-solid text-white", "wrong", "gave a wrong answer"],
      error: ["bg-warn text-frame", "crash", "crashed"],
    } as const;
    const [cls, w, l] = map[tile.outcome ?? "error"];
    className = `${TILE_BASE} ${cls}`;
    word = w;
    label = l;
  }
  const full = `${tile.arm === "control" ? "Without the change" : "With the change"}, run ${tile.i}: ${label}`;
  return tile.run_id ? (
    <Link href={runHref(tile.run_id)} className={`${className} hover:ring-2 hover:ring-ink`} aria-label={`${full}. Open the run`} title={full}>
      {word}
    </Link>
  ) : (
    <span className={className} aria-label={full} title={full}>
      {word}
    </span>
  );
}

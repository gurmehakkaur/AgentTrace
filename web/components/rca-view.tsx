import Link from "next/link";
import type { Candidate, RcaReport, VerificationItem } from "@/lib/types";

/** "Why it probably failed": the most likely cause first, the other suspects folded away.
 * The agent proposes; experiments decide. */
export function RcaView({
  report, agentOf, canRun, busy, error, onFind, onTest, readOnly = false,
  experimentHref = () => null, onVerify, verifyBusy = false,
}: {
  report: RcaReport | null;
  agentOf: (nodeRunIdx: number) => string;
  canRun: boolean;
  busy: boolean;
  error: string | null;
  onFind: () => void;
  onTest: (candidate: Candidate) => void;
  readOnly?: boolean; // the public demo shows a saved report: nothing to run or test
  experimentHref?: (experimentId: string) => string | null; // where experiment links point; null = no link
  onVerify?: () => void; // start auto-verify (omit in read-only views)
  verifyBusy?: boolean;
}) {
  const verification = report?.verification ?? null;
  const running = verification?.status === "running";
  const order = verification?.ranking ?? report?.candidates.map((_, i) => i) ?? [];
  const canVerify = !!report && report.candidates.some((c) => c.proposed_edit);
  const [first, ...rest] = order;

  return (
    <section aria-label="Why it probably failed" className="flex flex-col gap-4">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Why it probably failed</h2>
        <p className="mt-1 max-w-prose text-muted">
          An AI reads the run and follows the wrong answer back to the step that caused it.
        </p>
      </div>

      {!readOnly && !report && (
        <div className="flex flex-col items-start gap-2">
          <button
            type="button"
            onClick={onFind}
            disabled={!canRun || busy}
            className="btn btn-primary rounded-lg px-5 py-2.5 font-semibold hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? "Reading the run…" : "Find the cause"}
          </button>
          {!canRun && <p className="text-sm text-muted">This only works on runs that failed their check.</p>}
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      )}

      {report && first !== undefined && (
        <>
          <p className="text-sm text-muted">
            Path of the mistake: {report.lineage.map((i) => agentOf(i)).join(" → ")}
          </p>

          {verification?.status === "done" && (
            <p className="rounded-lg border border-line bg-frame px-4 py-3 text-sm font-medium">
              {report.verdict_idx !== null
                ? `Supported by a small test: fixing the ${agentOf(report.candidates[report.verdict_idx].node_run_idx)} helped (${verification.n} runs each way). That is too few runs to be sure, so treat it as a strong hint.`
                : "No suspect passed its small test, so none is supported. The ranking below is still the AI's opinion."}
            </p>
          )}
          {verification?.status === "error" && (
            <p role="alert" className="text-sm text-bad">Checking by experiment failed ({verification.error ?? "unknown error"}).</p>
          )}

          <Suspect
            candidate={report.candidates[first]}
            rank={1}
            report={report}
            ci={first}
            agentOf={agentOf}
            item={verification?.items.find((it) => it.candidate_idx === first)}
            verification={verification}
            running={running}
            readOnly={readOnly}
            onTest={onTest}
            experimentHref={experimentHref}
            lead
          />

          {rest.length > 0 && (
            <details className="rounded-xl border border-line p-4">
              <summary className="cursor-pointer text-sm font-medium">Other suspects ({rest.length})</summary>
              <div className="mt-4 flex flex-col gap-4">
                {rest.map((ci, i) => (
                  <Suspect
                    key={ci}
                    candidate={report.candidates[ci]}
                    rank={i + 2}
                    report={report}
                    ci={ci}
                    agentOf={agentOf}
                    item={verification?.items.find((it) => it.candidate_idx === ci)}
                    verification={verification}
                    running={running}
                    readOnly={readOnly}
                    onTest={onTest}
                    experimentHref={experimentHref}
                  />
                ))}
              </div>
            </details>
          )}

          {!readOnly && onVerify && (
            <div className="flex flex-col items-start gap-1">
              <button
                type="button"
                onClick={onVerify}
                disabled={!canVerify || running || verifyBusy}
                className="rounded-lg border border-ink/40 px-4 py-2 text-sm font-semibold hover:bg-ink/5 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {running || verifyBusy ? "Testing the top suspects…" : verification ? "Check again" : "Check the top suspects by experiment"}
              </button>
              <p className="text-xs text-muted">Runs each suspect&apos;s fix a few times and ranks them by what actually happened.</p>
            </div>
          )}
          {!readOnly && (
            <button type="button" onClick={onFind} disabled={!canRun || busy} className="self-start text-sm text-muted underline underline-offset-4 hover:text-ink disabled:opacity-40">
              {busy ? "Reading the run…" : "Ask the AI again"}
            </button>
          )}
        </>
      )}
    </section>
  );
}

function Suspect({
  candidate: c, rank, report, ci, agentOf, item, verification, running, readOnly, onTest, experimentHref, lead = false,
}: {
  candidate: Candidate;
  rank: number;
  report: RcaReport;
  ci: number;
  agentOf: (i: number) => string;
  item?: VerificationItem;
  verification: RcaReport["verification"];
  running: boolean;
  readOnly: boolean;
  onTest: (c: Candidate) => void;
  experimentHref: (id: string) => string | null;
  lead?: boolean;
}) {
  const confirmed = report.verdict_idx === ci;
  return (
    <article className={`rounded-xl border p-5 ${lead ? "border-bad/25 bg-bad-tint" : "border-line"}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className={`font-semibold ${lead ? "text-xl" : "text-base"}`}>
          {lead ? "Most likely: " : `#${rank} `}
          <span className="capitalize">{agentOf(c.node_run_idx)}</span>
        </h3>
        {confirmed && <span className="rounded-full bg-good-solid px-2 py-0.5 text-xs font-medium text-white">Supported by test</span>}
        <span className="ml-auto text-sm tabular-nums text-muted">{Math.round(c.confidence * 100)}% sure</span>
      </div>
      {c.matches_past_pattern && (
        <SeenBefore
          experimentId={c.matches_past_pattern}
          text={report.recalled.find((r) => r.experiment === c.matches_past_pattern)?.text}
          href={experimentHref(c.matches_past_pattern)}
        />
      )}
      <p className="mt-3 max-w-prose">{c.hypothesis}</p>
      {verification && (
        <Measurement item={item} running={running} href={item?.experiment_id ? experimentHref(item.experiment_id) : null} n={verification.n} />
      )}
      {c.evidence_quotes.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm text-muted">Evidence from the run</summary>
          <ul className="mt-2 flex flex-col gap-1.5">
            {c.evidence_quotes.map((q) => (
              <li key={q} className="break-words border-l-2 border-ink/40 pl-3 font-mono text-xs text-ink">
                {q}
              </li>
            ))}
          </ul>
        </details>
      )}
      {!readOnly && c.proposed_edit && (
        <button
          type="button"
          onClick={() => onTest(c)}
          className="btn btn-primary mt-4 rounded-lg px-4 py-2 text-sm font-semibold hover:opacity-90"
        >
          Test this fix
        </button>
      )}
      {!readOnly && !c.proposed_edit && <p className="mt-3 text-xs text-muted">No concrete fix proposed for this one.</p>}
    </article>
  );
}

/** The candidate matches a root cause that an earlier experiment in this workspace confirmed. */
function SeenBefore({ experimentId, text, href }: { experimentId: string; text?: string; href: string | null }) {
  const chip = (
    <span className="inline-flex items-center gap-1 rounded-full border border-ink/30 px-2 py-0.5 text-xs font-medium text-ink">
      <span aria-hidden>↺</span> Seen before in this workspace
    </span>
  );
  return (
    <div className="mt-2 flex flex-col gap-1">
      {href ? (
        <Link href={href} aria-label={`Seen before: open experiment ${experimentId.slice(0, 8)}`} className="self-start hover:opacity-80">
          {chip}
        </Link>
      ) : (
        <span className="self-start">{chip}</span>
      )}
      {text && <p className="max-w-prose text-xs text-muted">{text}</p>}
    </div>
  );
}

/** What the experiment for one suspect measured. */
function Measurement({ item, running, href, n }: { item?: VerificationItem; running: boolean; href: string | null; n: number }) {
  const box = "mt-3 rounded-lg border border-line px-3 py-2 text-sm";
  if (!item) return <p className={`${box} text-muted`}>Not tested: no concrete fix to try.</p>;
  if (item.error) return <p className={`${box} text-muted`}>Could not be tested: {item.error}</p>;
  if (running || !item.control || !item.treatment) {
    return <p className={`${box} animate-pulse text-muted`}>Testing: {n} runs without the fix, {n} with it…</p>;
  }
  return (
    <p className={box}>
      <b>Tested</b>: without the fix {item.control.pass}/{item.control.total}, with it {item.treatment.pass}/{item.treatment.total}.{" "}
      {item.verified ? "The fix helped." : "The fix did not help enough."}{" "}
      {href && (
        <Link href={href} className="font-semibold underline underline-offset-2">
          See the experiment
        </Link>
      )}
    </p>
  );
}

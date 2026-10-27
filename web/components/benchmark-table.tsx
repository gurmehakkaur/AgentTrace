import type { Benchmark } from "@/lib/types";
import { percent } from "@/lib/format";

const cell = "px-2 py-2 text-right tabular-nums sm:px-3";

// The planner fix was found on one account. This asks whether it holds on others. Every number
// is a count of whole fresh runs (live, sampled), reported as it came out.
export function BenchmarkTable({ benchmark: b }: { benchmark: Benchmark }) {
  const { original: o, patched: p } = b.totals;
  return (
    <section aria-label="Generalization benchmark">
      <h2 className="mb-1 text-base font-medium text-ink">
        Does the fix hold on other accounts?
      </h2>
      <p className="mb-3 text-sm text-muted">
        Original vs patched prompt on {b.accounts.length} other accounts, {b.n} fresh runs each
        {b.excluded_account ? ` (not ${b.excluded_account}, where the fix was found)` : ""}.
      </p>
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-sm">
          <caption className="sr-only">Passing runs per account for the original and the patched planner prompt</caption>
          <thead className="bg-tile text-left">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Account</th>
              <th scope="col" className={`${cell} font-medium`}>Original</th>
              <th scope="col" className={`${cell} font-medium`}>Patched</th>
            </tr>
          </thead>
          <tbody>
            {b.accounts.map((a) => (
              <tr key={a.account_id} className="border-t border-line">
                <th scope="row" className="px-3 py-2 text-left font-mono font-normal">{a.account_id}</th>
                <td className={cell}>{a.original.pass}/{a.original.total}</td>
                <td className={cell}>{a.patched.pass}/{a.patched.total}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-ink font-semibold">
              <th scope="row" className="px-3 py-2 text-left">All accounts</th>
              <td className={cell}>{o.pass}/{o.total} ({percent(o.total ? o.pass / o.total : 0)})</td>
              <td className={cell}>{p.pass}/{p.total} ({percent(p.total ? p.pass / p.total : 0)})</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">
        Directional. A run that crashed counts as not passing.
      </p>
    </section>
  );
}

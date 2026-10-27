import type { OracleDetail } from "./types";

export type Chip = { label: string; ok: boolean | null; note?: string };

/** The checks behind a run's verdict. The renewal demo has three fixed ones; a run from anywhere else has the
 * one check its owner wrote, labelled as that: a check written in code, and its reason. */
export function checkChips(detail: OracleDetail | undefined | null): Chip[] {
  if (!detail) return [];
  const chips: Chip[] = [];
  const demo = [
    ["Open tickets", detail.open_tickets_ok],
    ["Pipeline total", detail.pipeline_ok],
    ["Review loop", detail.critic_loop_ok],
  ] as const;
  for (const [label, ok] of demo) if (ok !== undefined) chips.push({ label, ok });
  const v = detail.verdict;
  if (v) {
    chips.push(
      v.passed === null || v.passed === undefined
        ? { label: `Your check ${v.name} could not run`, ok: null, note: v.reason }
        : { label: `Your check ${v.name}`, ok: v.passed, note: v.reason || undefined },
    );
  }
  return chips;
}

/** The headline for a run. A run nobody has judged yet is not "right": it has no verdict. */
export function headline(outcome: string | undefined | null): string {
  if (outcome === "pass") return "This run gave the right answer.";
  if (outcome === "fail" || outcome === "error") return "This run gave a wrong answer.";
  return "This run has no verdict yet.";
}

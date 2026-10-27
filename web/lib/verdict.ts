import type { Arm } from "./types";

export type Verdict = { tone: "good" | "neutral" | "bad"; text: string };

const SIGNIFICANT = 0.05;

/** The one-sentence answer to "did the change work?". It always says what the numbers can
 * support: with few runs, a gap that could be luck is reported as a hint, not a result. */
export function verdictFor(control: Arm, treatment: Arm, p: number | null): Verdict | null {
  if (control.total === 0 || treatment.total === 0) return null;
  const c = control.pass / control.total;
  const t = treatment.pass / treatment.total;
  if (t > c) {
    if (p !== null && p < SIGNIFICANT) {
      return t >= 0.8
        ? { tone: "good", text: "The change fixed it." }
        : { tone: "good", text: "The change helped, but it did not fix every run." };
    }
    return { tone: "neutral", text: "It looks like the change helped, but there are too few runs to be sure." };
  }
  if (t === c) return { tone: "bad", text: "The change made no difference. This step is probably not the cause." };
  return { tone: "bad", text: "The change made things worse." };
}

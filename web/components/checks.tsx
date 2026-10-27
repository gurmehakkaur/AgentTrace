import { checkChips } from "@/lib/checks";
import type { OracleDetail } from "@/lib/types";

/** The code checks behind the verdict, as plain chips: code against the real data, not an AI's opinion. */
export function Checks({ detail }: { detail?: OracleDetail | null }) {
  const chips = checkChips(detail);
  if (chips.length === 0) return null;
  const notes = chips.filter((c) => c.note);
  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-wrap gap-2" aria-label="Checks run in code">
        {chips.map((c) => (
          <li
            key={c.label}
            className={`rounded-full border px-3 py-1 text-sm ${c.ok === null ? "border-line bg-tile text-muted" : c.ok ? "border-good/30 bg-good-tint text-good" : "border-bad/30 bg-bad-tint text-bad"}`}
          >
            {c.label}{c.ok === null ? "" : `: ${c.ok ? "right" : "wrong"}`}
          </li>
        ))}
      </ul>
      {notes.map((c) => <p key={c.label} className="max-w-[60ch] text-muted">{c.note}</p>)}
    </div>
  );
}

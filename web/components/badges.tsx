import type { Origin, Outcome } from "@/lib/types";

const OUTCOME: Record<Outcome, { label: string; className: string }> = {
  pass: { label: "PASS", className: "bg-good-solid text-white" },
  fail: { label: "FAIL", className: "bg-bad-solid text-white" },
  error: { label: "ERROR", className: "bg-warn text-frame" },
};

export function OutcomeBadge({ outcome, status }: { outcome?: Outcome; status?: string }) {
  const style = outcome ? OUTCOME[outcome] : null;
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-xs font-semibold tracking-wide ${
        style?.className ?? "bg-tile text-ink"
      }`}
    >
      {style?.label ?? (status ?? "unknown").toUpperCase()}
    </span>
  );
}

// Origin is how the UI tells the truth about replay: recorded/replayed steps come from the
// stored recording; live steps ran against Claude and are sampled, never deterministic.
export const ORIGINS: Record<Origin, { label: string; badge: string; chip: string; meaning: string }> = {
  recorded: {
    label: "recorded",
    badge: "border-muted text-ink",
    chip: "border-muted",
    meaning: "captured from the original run",
  },
  replayed: {
    label: "replayed",
    badge: "border-line bg-tile text-ink",
    chip: "border-line",
    meaning: "copied exactly from the recording, no API calls",
  },
  edited: {
    label: "edited",
    badge: "border-warn/40 bg-warn-tint text-warn",
    chip: "border-warn border-dashed",
    meaning: "your edit replaces the recorded output",
  },
  live: {
    label: "live",
    badge: "border-accent/50 text-accent",
    chip: "border-accent",
    meaning: "re-run against Claude: sampled, not deterministic",
  },
};

export function OriginBadge({ origin }: { origin: Origin }) {
  return (
    <span className={`inline-block rounded border px-1.5 py-0.5 text-xs font-medium ${ORIGINS[origin].badge}`}>
      {ORIGINS[origin].label}
    </span>
  );
}

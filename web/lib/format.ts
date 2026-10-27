export const shortId = (id: string) => id.slice(0, 8);

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export const formatTokens = (n: number) => n.toLocaleString();

export const formatP = (p: number) => (p < 0.001 ? "< 0.001" : p.toFixed(3));

export const percent = (x: number) => `${Math.round(x * 100)}%`;

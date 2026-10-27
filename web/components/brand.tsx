import Link from "next/link";

/** The product's mark: four agents in a line, one marked. Drawn from the product's own object. */
export function Mark() {
  return (
    <svg width="26" height="14" viewBox="0 0 26 14" aria-hidden>
      <path d="M3 7h20" stroke="#9d998e" strokeWidth="1.5" />
      {[3, 10, 17, 24].map((x, i) => (
        <circle key={x} cx={x} cy="7" r="2.6" fill={i === 2 ? "#d97757" : "#ece9e1"} />
      ))}
    </svg>
  );
}

export function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5 font-serif text-[1.375rem] leading-none tracking-tight">
      <Mark />
      AgentTrace
    </Link>
  );
}

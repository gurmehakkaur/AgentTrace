"use client";

import { useRouter } from "next/navigation";
import { EXAMPLES, exampleFor } from "@/lib/examples";

/** The dropdown that moves between the saved examples. A real select: keyboard and screen readers work as they do anywhere. */
export function ExamplePicker({ current }: { current: string }) {
  const router = useRouter();
  const here = exampleFor(current);
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor="example-picker" className="font-medium">Example</label>
      <select
        id="example-picker" value={here.href} onChange={(e) => router.push(e.target.value)}
        className="max-w-md rounded-lg border border-line bg-tile px-3 py-2"
      >
        {EXAMPLES.map((e) => <option key={e.href} value={e.href}>{e.label}</option>)}
      </select>
      <p className="max-w-[60ch] text-[0.8125rem] text-muted">{here.blurb} The data in the examples is sample data.</p>
    </div>
  );
}

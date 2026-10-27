import { Shell } from "@/components/shell";
import Link from "next/link";
import { Suspense } from "react";
import { ExperimentLoader } from "./experiment-loader";

export default function ExperimentPage() {
  return (
    <Shell>
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-5 py-8 sm:px-8">
      <Link href="/runs" className="text-sm underline-offset-4 hover:underline">
        ← All runs
      </Link>
      <Suspense fallback={<p className="font-mono text-sm">Loading…</p>}>
        <ExperimentLoader />
      </Suspense>
    </main>
    </Shell>
  );
}

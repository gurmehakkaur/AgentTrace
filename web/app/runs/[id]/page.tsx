import { Shell } from "@/components/shell";
import Link from "next/link";
import { Suspense } from "react";
import { RunLoader } from "./run-loader";

export const metadata = { title: "Run" };

export default function RunPage() {
  return (
    <Shell>
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-5 py-8 sm:px-8">
      <Link href="/runs" className="text-sm text-muted underline-offset-4 hover:text-ink hover:underline">
        ← All runs
      </Link>
      {/* The route param is read on the client, which Cache Components needs inside Suspense. */}
      <Suspense fallback={<p className="font-mono text-sm">Loading…</p>}>
        <RunLoader />
      </Suspense>
    </main>
    </Shell>
  );
}

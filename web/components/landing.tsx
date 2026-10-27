import Link from "next/link";
import { LandingGraph } from "@/components/landing-graph";
import { TopBar } from "@/components/shell";
import type { Demo } from "@/lib/demo";

const STEPS = [
  ["Record", "Add the Python recorder to your agents. Each run becomes a line of agents, with secrets removed first."],
  ["Find the cause", "Open a run that went wrong. The agent that most likely caused it is marked on the line."],
  ["Fork to test a fix", "Change what one agent decided. A new line opens and the rest runs again, with and without your change."],
] as const;

/** The landing page: say what it is, then show the real thing. The graph is a saved run you can click. */
export function Landing({ demo }: { demo: Demo | null }) {
  return (
    <div className="flex min-h-svh flex-col">
      <TopBar />
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-20 px-5 pb-20 pt-4 sm:px-8 sm:pt-6">
        {/* The line and its forks are part of the first screen, so the headline and the picture sit together. */}
        <div className="flex flex-col gap-7">
        <section className="flex flex-col gap-4">
          <h1 className="max-w-3xl font-serif text-[2.25rem] leading-[1.08] sm:text-[2.75rem]">See which agent broke your run.</h1>
          <p className="max-w-[60ch] text-[1.0625rem] text-muted">
            AgentTrace draws a multi-agent run as one line, marks where the mistake came in, and lets you fork any step to test a fix
            before you ship it.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link href="/demo" className="btn btn-primary">Open the saved example</Link>
            <Link href="/sign-in" className="btn">Sign in</Link>
          </div>
        </section>

        <section aria-label="A saved run" className="flex flex-col gap-3">
          {demo ? (
            <>
              <p className="text-muted">A real saved run. Select any node to see what it is.</p>
              <LandingGraph demo={demo} />
            </>
          ) : (
            <div className="card flex h-64 items-center justify-center text-muted">The saved example is loading.</div>
          )}
        </section>

        </div>

        <section aria-label="How you use it" className="grid gap-x-12 gap-y-6 lg:grid-cols-[1fr_2fr]">
          <h2 className="font-serif text-3xl">How you use it</h2>
          <ol className="divide-y divide-line border-y border-line">
            {STEPS.map(([title, text]) => (
              <li key={title} className="py-5">
                <h3 className="font-serif text-xl">{title}</h3>
                <p className="mt-1 max-w-prose text-muted">{text}</p>
              </li>
            ))}
          </ol>
        </section>

        <footer className="border-t border-line pt-6 text-[0.8125rem] text-muted">
          <p className="max-w-prose">
            Steps before a fork replay exactly from the recording. Steps after it run live, so results are shown as passes out of N
            with a Fisher exact p-value, as directional evidence.
          </p>
        </footer>
      </main>
    </div>
  );
}

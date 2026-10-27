import { Shell } from "@/components/shell";
import { Connect } from "./connect";

export const metadata = { title: "Connect your agents" };

export default function ConnectPage() {
  return (
    <Shell>
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-12 px-5 py-8 sm:px-8">
        <header className="flex flex-col gap-2">
          <h1 className="font-serif text-[1.75rem] sm:text-[2.25rem]">Connect your agents</h1>
          <p className="max-w-[60ch] text-muted">
            Send your agents&apos; runs to this workspace, or bring runs you already have. Each one appears as a line you can open.
          </p>
        </header>
        <Connect />
      </main>
    </Shell>
  );
}

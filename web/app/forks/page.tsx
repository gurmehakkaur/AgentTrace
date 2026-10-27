import { Shell } from "@/components/shell";
import { ForksList } from "./forks-list";

export const metadata = { title: "Forks" };

export default function ForksPage() {
  return (
    <Shell>
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-5 py-8 sm:px-8">
        <header>
          <h1 className="font-serif text-[1.75rem] sm:text-[2.25rem]">Forks</h1>
          <p className="mt-1 max-w-[60ch] text-muted">Every change you have tried, newest first, and whether it worked. Open one to see its line.</p>
        </header>
        <ForksList />
      </main>
    </Shell>
  );
}

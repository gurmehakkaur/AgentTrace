import { Shell } from "@/components/shell";
import { RunsList } from "./runs-list";

export const metadata = { title: "Runs" };

export default function RunsPage() {
  return (
    <Shell>
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-5 py-8 sm:px-8">
      <h1 className="font-serif text-[1.5rem] sm:text-[1.75rem]">Runs</h1>
      <RunsList />
    </main>
    </Shell>
  );
}

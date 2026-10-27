import { Shell } from "@/components/shell";
import { ActivityList } from "./activity-list";

export const metadata = { title: "Activity" };

export default function ActivityPage() {
  return (
    <Shell>
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-5 py-8 sm:px-8">
        <header>
          <h1 className="font-serif text-[1.75rem] sm:text-[2.25rem]">Activity</h1>
          <p className="mt-1 max-w-[60ch] text-muted">Who started forks, looked for causes, made keys or deleted runs in this workspace. Admins only.</p>
        </header>
        <ActivityList />
      </main>
    </Shell>
  );
}

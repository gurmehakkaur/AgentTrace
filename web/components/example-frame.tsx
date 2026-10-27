import type { ReactNode } from "react";
import { ExamplePicker } from "@/components/example-picker";
import { Shell } from "@/components/shell";

/** The page every example sits in: the sidebar, the dropdown, then the example. */
export function ExampleFrame({ path, wide = false, children }: { path: string; wide?: boolean; children: ReactNode }) {
  return (
    <Shell>
      <main className={`mx-auto flex w-full flex-1 flex-col gap-8 px-5 py-8 sm:px-8 ${wide ? "max-w-6xl" : "max-w-5xl"}`}>
        <ExamplePicker current={path} />
        {children}
      </main>
    </Shell>
  );
}

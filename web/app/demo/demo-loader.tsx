import { RunView } from "@/components/run-view";
import type { Demo } from "@/lib/demo";

export function DemoView({ demo }: { demo: Demo | null }) {
  if (!demo) {
    return (
      <p role="alert" className="card p-5">
        The saved example is not available right now. Please try again in a minute.
      </p>
    );
  }
  return <RunView run={demo.run} mode="demo" report={demo.rca} experiments={demo.experiments} titleLevel={1} />;
}

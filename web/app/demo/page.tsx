import { ExampleFrame } from "@/components/example-frame";
import { Suspense } from "react";
import { loadDemo } from "@/lib/demo";
import { DemoView } from "./demo-loader";

export const metadata = { title: "Examples" };

async function Content() {
  return <DemoView demo={await loadDemo()} />;
}

export default function DemoPage() {
  return (
    <ExampleFrame path="/demo" wide>
      <Suspense fallback={<p className="text-muted">Loading the saved run…</p>}>
        <Content />
      </Suspense>
    </ExampleFrame>
  );
}

import { Suspense } from "react";
import { Landing } from "@/components/landing";
import { loadDemo } from "@/lib/demo";

async function Content() {
  return <Landing demo={await loadDemo()} />;
}

export default function Home() {
  return (
    <Suspense fallback={<Landing demo={null} />}>
      <Content />
    </Suspense>
  );
}

import { Connect } from "@/app/connect/connect";
import { DemoApi } from "@/components/demo-api";
import { ExampleFrame } from "@/components/example-frame";

export const metadata = { title: "Example: keys, alerts and agents" };

export default function Page() {
  return (
    <ExampleFrame path="/demo/connect">
      <section className="flex flex-col gap-3">
        <h1 className="font-serif text-[1.75rem] sm:text-[2.25rem]">Connect your agents</h1>
        <p className="max-w-[70ch] text-muted">
          This is the real Connect page with sample answers, so you can try it without signing in: nothing is saved and no key here works anywhere.
          Pick what a key is for and make one. A key made for a worker shows how to start the worker; one made for an agent shows the commands.
          Further down, add a Slack address to be told when a run fails.
        </p>
      </section>
      <DemoApi><Connect /></DemoApi>
    </ExampleFrame>
  );
}

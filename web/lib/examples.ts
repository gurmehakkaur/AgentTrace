/** The saved examples, in the order the dropdown shows them. Every one is public and uses sample data. */
export type Example = { href: string; label: string; blurb: string };

export const EXAMPLES: Example[] = [
  { href: "/demo", label: "A failing run, fixed by a fork", blurb: "The real recorded run behind the headline result: find the cause, fork it, and see 0 of 8 become 8 of 8." },
  { href: "/demo/overview", label: "All your runs by time", blurb: "Every run on one sheet, each in its own colour, with the forks you tried on it." },
  { href: "/demo/connect", label: "Keys, alerts and agents", blurb: "Make a key for what you need, and get told in Slack when a run fails. Click around: nothing here is saved." },
  { href: "/demo/worker", label: "Forking your own agents", blurb: "A worker next to your code runs your agents again, and AgentTrace counts the results." },
  { href: "/demo/terminal", label: "From your terminal and CI", blurb: "Look at failed runs, ask which step broke one, and stop a deploy when a proven fix stops working." },
];

export const exampleFor = (path: string): Example => EXAMPLES.find((e) => e.href === path) ?? EXAMPLES[0];

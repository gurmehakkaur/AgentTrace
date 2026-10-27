import Link from "next/link";
import { OrganizationSwitcher, Show, SignInButton, UserButton } from "@clerk/nextjs";
import { Suspense } from "react";
import { Brand } from "@/components/brand";
import { type NavGroup, NavLinks } from "@/components/nav-links";

const SIGNED_IN: NavGroup[] = [
  { label: "Your project", items: [{ href: "/runs", label: "Runs" }, { href: "/forks", label: "Forks" }, { href: "/activity", label: "Activity" }] },
  { label: "Set up", items: [{ href: "/connect", label: "Connect your agents" }] },
  { label: "Learn", items: [{ href: "/demo", label: "Examples" }] },
];
const SIGNED_OUT: NavGroup[] = [{ label: "Learn", items: [{ href: "/demo", label: "Examples" }] }];

/** The app frame, as in the Claude Console: a quiet sidebar with the product, the workspace and the
 * pages, and the work on the right. On a phone the sidebar becomes a bar across the top. */
export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col lg:flex-row">
      <aside className="flex min-w-0 flex-none flex-col gap-4 overflow-hidden border-b border-line px-3 py-3 lg:w-60 lg:border-b-0 lg:border-r lg:py-5">
        <div className="flex items-center justify-between">
          <Brand />
        </div>
        <Suspense>
          <div className="flex min-w-0 flex-col gap-4">
            <Show when="signed-in">
              {/* Organizations are workspaces, so a personal account is not offered. */}
              <OrganizationSwitcher
                hidePersonal
                afterSelectOrganizationUrl="/runs"
                appearance={{
                  elements: {
                    rootBox: "w-full min-w-0",
                    organizationSwitcherTrigger: "w-full min-w-0 justify-between",
                    organizationPreview: "min-w-0",
                    organizationPreviewTextContainer: "min-w-0",
                    organizationPreviewMainIdentifier: "truncate",
                  },
                }}
              />
            </Show>
            <nav aria-label="Main">
              <Show when="signed-in">
                <NavLinks groups={SIGNED_IN} />
              </Show>
              <Show when="signed-out">
                <NavLinks groups={SIGNED_OUT} />
              </Show>
            </nav>
          </div>
          <div className="mt-auto hidden items-center gap-3 lg:flex">
            <Show when="signed-in">
              <UserButton />
            </Show>
            <Show when="signed-out">
              <SignInButton>
                <button type="button" className="btn btn-primary w-full">Sign in</button>
              </SignInButton>
            </Show>
          </div>
        </Suspense>
      </aside>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

/** The bar for pages without a sidebar: the landing page and sign-in. */
export function TopBar() {
  return (
    <header className="flex h-14 items-center justify-between gap-3 px-4 sm:px-8">
      <Brand />
      <Suspense>
        <nav className="flex items-center gap-3">
          <Link href="/demo" className="hidden text-muted hover:text-ink sm:inline">Examples</Link>
          <Show when="signed-out">
            <SignInButton>
              <button type="button" className="btn btn-primary whitespace-nowrap">Sign in</button>
            </SignInButton>
          </Show>
          <Show when="signed-in">
            <Link href="/runs" className="btn btn-primary whitespace-nowrap">Open your runs</Link>
          </Show>
        </nav>
      </Suspense>
    </header>
  );
}

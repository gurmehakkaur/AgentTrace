"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export type NavGroup = { label: string; items: { href: string; label: string }[] };

/** Sidebar links in small groups. The current page is a filled row; everything else is quiet text. */
export function NavLinks({ groups }: { groups: NavGroup[] }) {
  const path = usePathname();
  return (
    <div className="flex flex-col gap-5">
      {groups.map((g) => (
        <div key={g.label}>
          <p className="px-3 pb-1 text-[0.8125rem] text-muted">{g.label}</p>
          <ul className="flex flex-col gap-0.5">
            {g.items.map((i) => {
              const on = path === i.href || path.startsWith(`${i.href}/`);
              return (
                <li key={i.href}>
                  <Link
                    href={i.href}
                    aria-current={on ? "page" : undefined}
                    className={`block truncate rounded-lg px-3 py-2 ${on ? "bg-tile text-ink" : "text-ink/80 hover:bg-tile/60 hover:text-ink"}`}
                  >
                    {i.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

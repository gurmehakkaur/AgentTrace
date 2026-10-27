"use client";

import { useEffect, useState } from "react";
import type { Loaded } from "@/lib/use-api-data";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

/** GET a public (no sign-in) API route. No Authorization header: these routes serve only the
 * demo workspace, and the server decides that, not us. */
export function usePublicData<T>(path: string): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}${path}`)
      .then(async (res) => {
        if (!res.ok) {
          const detail = (await res.json().catch(() => null))?.detail;
          throw Object.assign(new Error(typeof detail === "string" ? detail : res.statusText), { status: res.status });
        }
        return res.json() as Promise<T>;
      })
      .then((data) => !cancelled && setState({ status: "ok", data }))
      .catch((err: unknown) => {
        if (cancelled) return;
        const status = (err as { status?: number }).status ?? 0;
        setState({ status: "error", code: status, message: err instanceof Error ? err.message : "Request failed" });
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  return state;
}

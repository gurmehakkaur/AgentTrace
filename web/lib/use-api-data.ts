"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect, useEffectEvent, useState } from "react";
import { ApiError, useApi } from "@/lib/api";

export type Loaded<T> =
  | { status: "loading" }
  | { status: "ok"; data: T }
  | { status: "error"; code: number; message: string };

/** GET `path` from the API as the signed-in user; refetch when the organization changes.
 * If `pollMs` returns a number for the latest data, fetch again after that many ms. */
export function useApiData<T>(path: string, pollMs?: (data: T) => number | null): Loaded<T> {
  const { orgId, isLoaded } = useAuth();
  const api = useApi();
  const [state, setState] = useState<Loaded<T>>({ status: "loading" });
  const waitFor = useEffectEvent((data: T) => pollMs?.(data) ?? null);

  useEffect(() => {
    if (!isLoaded) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const data = await api<T>(path);
        if (cancelled) return;
        setState({ status: "ok", data });
        const wait = waitFor(data);
        if (wait !== null) timer = setTimeout(load, wait);
      } catch (err) {
        if (cancelled) return;
        setState({
          status: "error",
          code: err instanceof ApiError ? err.status : 0,
          message: err instanceof Error ? err.message : "Request failed",
        });
      }
    };
    void load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [api, isLoaded, orgId, path]);

  return state;
}

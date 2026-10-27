"use client";

import { useAuth } from "@clerk/nextjs";
import { useCallback } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** fetch against the AgentTrace API with the signed-in user's Clerk session token as a Bearer
 * token. The API takes the workspace from the token's active organization, never from us. */
export function useApi() {
  const { getToken } = useAuth();
  return useCallback(
    async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
      const token = await getToken();
      const res = await fetch(`${API_URL}${path}`, {
        ...init,
        headers: {
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          ...init.headers,
          Authorization: `Bearer ${token}`,
        },
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => null))?.detail;
        throw new ApiError(res.status, typeof detail === "string" ? detail : res.statusText);
      }
      return res.json() as Promise<T>;
    },
    [getToken],
  );
}

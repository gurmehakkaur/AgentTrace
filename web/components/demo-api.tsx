"use client";

import { useEffect, useState, type ReactNode } from "react";
import { makeDemoApi } from "@/lib/demo-api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";

let restore: (() => void) | null = null;

function patch() {
  if (restore) return;
  const base = window.fetch;
  const answer = makeDemoApi();
  window.fetch = async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (!API || !url.startsWith(API)) return base.call(window, input, init);
    const { status, json } = answer((init?.method ?? "GET").toUpperCase(), url.slice(API.length), init?.body ? JSON.parse(String(init.body)) : null);
    return new Response(JSON.stringify(json), { status, headers: { "Content-Type": "application/json" } });
  };
  restore = () => {
    window.fetch = base;
    restore = null;
  };
}

/** Inside this, the app's calls to the API are answered with sample data, so an example works without signing in.
 * The real fetch comes back when the example is left: fake answers can never follow you into the real app. */
export function DemoApi({ children }: { children: ReactNode }) {
  useState(() => { if (typeof window !== "undefined") patch(); }); // in place before the children make their first calls
  useEffect(() => {
    patch(); // again if React ran the cleanup and mounted this a second time
    return () => restore?.();
  }, []);
  return <>{children}</>;
}

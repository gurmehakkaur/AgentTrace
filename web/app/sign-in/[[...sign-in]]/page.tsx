import { TopBar } from "@/components/shell";
import { SignIn } from "@clerk/nextjs";
import { Suspense } from "react";

export const metadata = { title: "Sign in" };

export default function SignInPage() {
  return (
    <div className="flex min-h-svh flex-col"><TopBar />
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      {/* Clerk reads the URL; Cache Components needs that inside Suspense. */}
      <Suspense>
        <SignIn />
      </Suspense>
    </main>
    </div>
  );
}

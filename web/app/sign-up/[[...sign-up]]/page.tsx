import { TopBar } from "@/components/shell";
import { SignUp } from "@clerk/nextjs";
import { Suspense } from "react";

export const metadata = { title: "Sign up" };

export default function SignUpPage() {
  return (
    <div className="flex min-h-svh flex-col"><TopBar />
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <Suspense>
        <SignUp />
      </Suspense>
    </main>
    </div>
  );
}

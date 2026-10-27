import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Everything except the landing page and the sign-in/up pages needs a signed-in user.
const isPublic = createRouteMatcher(["/", "/sign-in(.*)", "/sign-up(.*)", "/demo(.*)"]);

export default clerkMiddleware(async (auth, req) => {
  if (!isPublic(req)) await auth.protect();
});

export const config = {
  matcher: [
    // Skip Next.js internals and static files, unless found in search params
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/__clerk/:path*",
    "/(api|trpc)(.*)",
  ],
};

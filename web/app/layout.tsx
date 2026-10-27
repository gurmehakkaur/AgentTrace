import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Geist_Mono, Inter, Newsreader } from "next/font/google";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], weight: ["400", "500"] });
const newsreader = Newsreader({ variable: "--font-newsreader", subsets: ["latin"], weight: ["400", "500"] });
// Monospace is only for real code: state values, ids and JSON.
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

const PITCH = "AgentTrace draws a multi-agent run as one line, marks where the mistake came in, and lets you fork any step to test a fix before you ship it.";

export const metadata: Metadata = {
  title: { default: "AgentTrace: see which agent broke your run", template: "%s · AgentTrace" },
  description: PITCH,
  openGraph: { title: "AgentTrace: see which agent broke your run", description: PITCH, siteName: "AgentTrace", type: "website" },
  twitter: { card: "summary", title: "AgentTrace: see which agent broke your run", description: PITCH },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning: browser extensions (Zotero, dark-mode tools) add attributes to <html>
    // before React loads, which logs a harmless hydration warning. It only silences this one element.
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${newsreader.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <ClerkProvider>{children}</ClerkProvider>
      </body>
    </html>
  );
}

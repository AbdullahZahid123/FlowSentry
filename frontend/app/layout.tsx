import "@xyflow/react/dist/style.css";
import "./globals.css";
import { ThemeProvider } from "@/components/theme";
import { SessionProvider } from "@/lib/session";
import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";

export const metadata: Metadata = {
  title: {
    default: "FlowSentry — Reliability for n8n",
    template: "%s · FlowSentry",
  },
  description:
    "Monitoring for n8n workflows. Monitor executions, investigate failures, and manage incidents across your n8n instances.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{__html:"try{document.documentElement.classList.toggle('light',localStorage.getItem('fs_theme')==='light')}catch(e){}"}} /></head>
      <body
        className={`${GeistSans.variable} ${GeistMono.variable} min-h-screen antialiased`}
      >
        <ThemeProvider>
          <SessionProvider>{children}</SessionProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

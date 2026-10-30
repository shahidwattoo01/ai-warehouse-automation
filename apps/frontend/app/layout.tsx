import type { Metadata } from "next";
import "./globals.css";
import { SimProvider } from "@/components/layout/SimProvider";
import { AuthGate } from "@/components/layout/AuthGate";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  title: "Warehouse AI Control Center",
  description: "AI-Powered Autonomous Warehouse Automation & Fleet Intelligence Platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body>
        <SimProvider>
          <AuthGate>{children}</AuthGate>
        </SimProvider>
      </body>
    </html>
  );
}

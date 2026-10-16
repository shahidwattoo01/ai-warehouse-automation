import type { Metadata } from "next";
import "./globals.css";
import { SimProvider } from "@/components/layout/SimProvider";
import { Sidebar } from "@/components/layout/Sidebar";
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
          <div className="flex h-screen overflow-hidden">
            <Sidebar />
            <main className="flex min-w-0 flex-1 flex-col">{children}</main>
          </div>
        </SimProvider>
      </body>
    </html>
  );
}

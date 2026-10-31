"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { useTheme } from "@/lib/theme";

export function ThemeToggle() {
  const { theme, setTheme, toggle } = useTheme();
  const [ready, setReady] = useState(false);

  // Sync the store with the theme the boot script applied before hydration.
  useEffect(() => {
    setTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    setReady(true);
  }, [setTheme]);

  const dark = ready && theme === "dark";
  return (
    <button
      onClick={toggle}
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      title={dark ? "Light mode" : "Dark mode"}
      className="flex items-center gap-2 rounded-control border border-border px-3 py-1.5 text-sm"
    >
      {dark ? <Sun size={16} /> : <Moon size={16} />}
      <span className="hidden 2xl:inline">{dark ? "Light" : "Dark"}</span>
    </button>
  );
}

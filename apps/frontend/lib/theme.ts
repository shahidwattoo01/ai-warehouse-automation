"use client";

import { create } from "zustand";

export type Theme = "light" | "dark";

const KEY = "wh-theme";

/** Pearl-white light theme by default; dark is a deep black. Persisted per browser. */
export const useTheme = create<{ theme: Theme; setTheme: (t: Theme) => void; toggle: () => void }>((set, get) => ({
  theme: typeof document !== "undefined" && document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  setTheme: (theme) => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {}
    set({ theme });
  },
  toggle: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),
}));

/** Runs before hydration (inlined in <head>) so the saved theme applies without a flash. */
export const THEME_BOOT_SCRIPT = `try{var t=localStorage.getItem("${KEY}");document.documentElement.dataset.theme=t==="dark"?"dark":"light"}catch(e){}`;

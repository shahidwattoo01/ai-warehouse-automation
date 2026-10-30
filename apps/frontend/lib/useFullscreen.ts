"use client";

import { useCallback, useEffect, useRef, useState } from "react";

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return (
    !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)
  );
}

/**
 * YouTube-style full screen for an element: `toggle()` or the "f" key enter/leave, Esc leaves.
 * The element itself goes full screen (nothing is re-created), so a 3D camera keeps its view.
 * Where the browser refuses native full screen (some embedded browsers) the element fills the
 * window instead: `windowed` is then true and the caller applies a fixed full-window style.
 */
export function useFullscreen<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [native, setNative] = useState(false);
  const [windowed, setWindowed] = useState(false);

  useEffect(() => {
    const onChange = () => setNative(document.fullscreenElement === ref.current);
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const toggle = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
      return;
    }
    if (windowed) {
      setWindowed(false);
      return;
    }
    const el = ref.current;
    if (!el?.requestFullscreen || !document.fullscreenEnabled) {
      setWindowed(true);
      return;
    }
    el.requestFullscreen()
      // Some embedded browsers resolve without actually going full screen.
      .then(() => setTimeout(() => !document.fullscreenElement && setWindowed(true), 300))
      .catch(() => setWindowed(true));
  }, [windowed]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key.toLowerCase() === "f") {
        e.preventDefault();
        toggle();
      } else if (e.key === "Escape" && windowed) {
        setWindowed(false); // native full screen handles Esc itself
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle, windowed]);

  return { ref, isFull: native || windowed, windowed, toggle };
}

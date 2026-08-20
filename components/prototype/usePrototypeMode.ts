"use client";

import { useEffect, useState } from "react";

export type PrototypeMode = "first" | "returning";

const MODE_KEY = "basis:mode";

export function usePrototypeMode() {
  const [mode, setMode] = useState<PrototypeMode>("first");

  useEffect(() => {
    if (typeof window === "undefined") return;

    const raw = localStorage.getItem(MODE_KEY);
    if (raw === "first" || raw === "returning") {
      
      // FIXED: Deferred state assignment to break the synchronous cascading execution loop
      requestAnimationFrame(() => {
        setMode(raw);
      });
    }
  }, []);


  const updateMode = (next: PrototypeMode) => {
    setMode(next);
    localStorage.setItem(MODE_KEY, next);
  };

  return { mode, setMode: updateMode };
}
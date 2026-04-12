"use client";

import { useAppStore } from "@/lib/store";

export function useHydrated() {
  return useAppStore((s) => s._hasHydrated);
}

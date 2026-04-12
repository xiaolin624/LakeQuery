"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { TableMeta } from "@/types/schema";

interface LlmConfig {
  provider: string;
  apiKey: string;
  model: string;
}

interface CatalogConfig {
  type: "hms" | "iceberg";
  host: string;
  port: string;
  username: string;
  restUri: string;
  database: string;
}

interface QueryResult {
  sql: string;
  answer: string;
  rows: Record<string, unknown>[];
  tables: string[];
  validated: boolean;
}

interface QueryState {
  question: string;
  dialect: string;
  result: QueryResult | null;
}

interface AppState {
  _hasHydrated: boolean;
  setHasHydrated: (v: boolean) => void;

  llmConfig: LlmConfig;
  setLlmConfig: (config: Partial<LlmConfig>) => void;

  catalogConfig: CatalogConfig;
  setCatalogConfig: (config: Partial<CatalogConfig>) => void;

  syncedTables: TableMeta[];
  addSyncedTables: (tables: TableMeta[]) => void;
  clearSyncedTables: () => void;

  queryState: QueryState;
  setQueryState: (patch: Partial<QueryState>) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      _hasHydrated: false,
      setHasHydrated: (v) => set({ _hasHydrated: v }),

      llmConfig: {
        provider: "OpenRouter",
        apiKey: "",
        model: "google/gemini-2.0-flash-001",
      },
      setLlmConfig: (config) =>
        set((state) => ({
          llmConfig: { ...state.llmConfig, ...config },
        })),

      catalogConfig: {
        type: "hms",
        host: "",
        port: "10000",
        username: "atguigu",
        restUri: "",
        database: "",
      },
      setCatalogConfig: (config) =>
        set((state) => ({
          catalogConfig: { ...state.catalogConfig, ...config },
        })),

      syncedTables: [],
      addSyncedTables: (incoming) =>
        set((state) => {
          const newKeys = new Set(
            incoming.map((t) => `${t.database}.${t.table_name}`),
          );
          const kept = state.syncedTables.filter(
            (t) => !newKeys.has(`${t.database}.${t.table_name}`),
          );
          return { syncedTables: [...kept, ...incoming] };
        }),
      clearSyncedTables: () => set({ syncedTables: [] }),

      queryState: {
        question: "",
        dialect: "hive",
        result: null,
      },
      setQueryState: (patch) =>
        set((state) => ({
          queryState: { ...state.queryState, ...patch },
        })),
    }),
    {
      name: "lakequery-store",
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    },
  ),
);

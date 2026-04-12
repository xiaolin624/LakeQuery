"use client";

import { useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { useAppStore } from "@/lib/store";
import { useHydrated } from "@/hooks/useHydration";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronRight, Database, Loader2, Table2, Trash2 } from "lucide-react";
import type { CatalogSyncResponse, ColumnMeta, TableMeta } from "@/types/schema";

/* -------- demo data (for local testing without a real backend) -------- */
const demoTables: TableMeta[] = [
  {
    database: "trade_dwd",
    table_name: "dwd_order_detail",
    columns: [
      { name: "order_id", data_type: "bigint" },
      { name: "user_id", data_type: "bigint" },
      { name: "product_id", data_type: "bigint" },
      { name: "amount", data_type: "double" },
      { name: "quantity", data_type: "int" },
      { name: "province", data_type: "string" },
      { name: "city", data_type: "string" },
      { name: "channel", data_type: "string" },
      { name: "payment_type", data_type: "string" },
      { name: "order_status", data_type: "tinyint" },
      { name: "created_at", data_type: "timestamp" },
      { name: "dt", data_type: "string", is_partition_key: true },
    ],
  },
  {
    database: "trade_dwd",
    table_name: "dwd_payment_flow",
    columns: [
      { name: "payment_id", data_type: "bigint" },
      { name: "order_id", data_type: "bigint" },
      { name: "user_id", data_type: "bigint" },
      { name: "amount", data_type: "double" },
      { name: "payment_method", data_type: "string" },
      { name: "status", data_type: "tinyint" },
      { name: "paid_at", data_type: "timestamp" },
      { name: "dt", data_type: "string", is_partition_key: true },
    ],
  },
  {
    database: "trade_dim",
    table_name: "dim_user",
    columns: [
      { name: "user_id", data_type: "bigint" },
      { name: "username", data_type: "string" },
      { name: "gender", data_type: "tinyint" },
      { name: "age", data_type: "int" },
      { name: "province", data_type: "string" },
      { name: "city", data_type: "string" },
      { name: "register_date", data_type: "date" },
    ],
  },
  {
    database: "trade_dim",
    table_name: "dim_product",
    columns: [
      { name: "product_id", data_type: "bigint" },
      { name: "product_name", data_type: "string" },
      { name: "category", data_type: "string" },
      { name: "brand", data_type: "string" },
      { name: "price", data_type: "double" },
    ],
  },
  {
    database: "analytics",
    table_name: "ads_daily_revenue",
    columns: [
      { name: "province", data_type: "string" },
      { name: "total_revenue", data_type: "double" },
      { name: "order_count", data_type: "bigint" },
      { name: "avg_order_value", data_type: "double" },
      { name: "uv", data_type: "bigint" },
      { name: "dt", data_type: "string", is_partition_key: true },
    ],
  },
  {
    database: "analytics",
    table_name: "ads_user_retention",
    columns: [
      { name: "cohort_date", data_type: "date" },
      { name: "day_n", data_type: "int" },
      { name: "retained_users", data_type: "bigint" },
      { name: "total_users", data_type: "bigint" },
      { name: "retention_rate", data_type: "double" },
      { name: "channel", data_type: "string" },
      { name: "dt", data_type: "string", is_partition_key: true },
    ],
  },
];

/* -------- mock field lookup (fallback when API returns names only) -------- */
const mockFieldMap: Record<string, ColumnMeta[]> = Object.fromEntries(
  demoTables.map((t) => [`${t.database}.${t.table_name}`, t.columns]),
);

function tableNamesToMeta(database: string, names: string[]): TableMeta[] {
  return names.map((fullName) => {
    const tableName = fullName.includes(".")
      ? fullName.split(".").pop()!
      : fullName;
    const columns = mockFieldMap[fullName] ?? [];
    return { table_name: tableName, database, columns };
  });
}

export default function CatalogPage() {
  const hydrated = useHydrated();
  const { catalogConfig, setCatalogConfig, syncedTables, addSyncedTables, clearSyncedTables } =
    useAppStore();
  const [syncing, setSyncing] = useState(false);

  async function handleSync() {
    setSyncing(true);
    try {
      const payload = {
        database: catalogConfig.database,
        catalog_type: catalogConfig.type,
        hms_host:
          catalogConfig.type === "hms" ? catalogConfig.host : undefined,
        hms_port:
          catalogConfig.type === "hms"
            ? Number(catalogConfig.port) || 10000
            : undefined,
        hms_auth:
          catalogConfig.type === "hms" ? "NONE" : undefined,
        hms_username:
          catalogConfig.type === "hms" ? (catalogConfig.username || "hive") : undefined,
        iceberg_rest_uri:
          catalogConfig.type === "iceberg" ? catalogConfig.restUri : undefined,
      };
      const { data } = await axios.post<CatalogSyncResponse>(
        "/api/v1/catalog/sync",
        payload,
      );
      /* prefer full table data from API; fall back to name-only conversion */
      const newTables =
        data.tables && data.tables.length > 0
          ? data.tables
          : tableNamesToMeta(catalogConfig.database, data.table_names);
      addSyncedTables(newTables);
      toast.success(
        `同步成功：${data.tables_synced} 张表（${catalogConfig.database}），${data.vectors_indexed} 条向量已索引`,
      );
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail ?? err.message;
        toast.error(`同步失败：${detail}`);
      } else {
        toast.error("同步失败：未知错误");
      }
    } finally {
      setSyncing(false);
    }
  }

  function handleLoadDemo() {
    addSyncedTables(demoTables);
    toast.success("已加载演示数据（3 个库，6 张表）");
  }

  function handleTabChange(v: string) {
    setCatalogConfig({ type: v as "hms" | "iceberg" });
  }

  /* group tables by database for display */
  const databases = [...new Set(syncedTables.map((t) => t.database))];

  if (!hydrated) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-10">
        <Skeleton className="h-7 w-32" />
        <Skeleton className="mt-2 h-4 w-64" />
        <Skeleton className="mt-6 h-[240px] w-full rounded-xl" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-xl font-semibold tracking-tight">Data Sources</h1>
      <p className="mt-1 text-[13px] text-muted-foreground">
        Connect to your Hive Metastore or Iceberg REST Catalog. You can sync
        multiple databases — tables accumulate across syncs.
      </p>

      <Tabs
        value={catalogConfig.type}
        onValueChange={handleTabChange}
        className="mt-6"
      >
        <TabsList>
          <TabsTrigger value="hms" className="text-[13px]">
            Hive Metastore
          </TabsTrigger>
          <TabsTrigger value="iceberg" className="text-[13px]">
            Iceberg REST
          </TabsTrigger>
        </TabsList>

        {/* ---- HMS Tab ---- */}
        <TabsContent value="hms">
          <Card>
            <CardHeader>
              <CardTitle className="text-[15px]">HMS Connection</CardTitle>
              <CardDescription>
                Connect to a Hive Metastore Thrift server.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="hms-host" className="text-[13px]">
                    Host
                  </Label>
                  <Input
                    id="hms-host"
                    placeholder="192.168.10.102"
                    value={catalogConfig.host}
                    onChange={(e) => setCatalogConfig({ host: e.target.value })}
                    className="text-[13px]"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="hms-port" className="text-[13px]">
                    Port
                  </Label>
                  <Input
                    id="hms-port"
                    placeholder="10000"
                    value={catalogConfig.port}
                    onChange={(e) => setCatalogConfig({ port: e.target.value })}
                    className="text-[13px]"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="hms-username" className="text-[13px]">
                    Username
                  </Label>
                  <Input
                    id="hms-username"
                    placeholder="atguigu"
                    value={catalogConfig.username}
                    onChange={(e) => setCatalogConfig({ username: e.target.value })}
                    className="text-[13px]"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="hms-database" className="text-[13px]">
                    Database
                  </Label>
                  <Input
                    id="hms-database"
                    placeholder="gmall"
                    value={catalogConfig.database}
                    onChange={(e) =>
                      setCatalogConfig({ database: e.target.value })
                    }
                    className="text-[13px]"
                  />
                </div>
              </div>
              <Button
                onClick={handleSync}
                disabled={
                  syncing || !catalogConfig.host || !catalogConfig.database
                }
                variant="outline"
                className="text-[13px]"
              >
                {syncing && (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                )}
                Sync Metadata
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ---- Iceberg Tab ---- */}
        <TabsContent value="iceberg">
          <Card>
            <CardHeader>
              <CardTitle className="text-[15px]">
                Iceberg REST Catalog
              </CardTitle>
              <CardDescription>
                Connect to an Iceberg REST Catalog endpoint.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="rest-uri" className="text-[13px]">
                  REST URI
                </Label>
                <Input
                  id="rest-uri"
                  placeholder="http://iceberg-rest:8181"
                  value={catalogConfig.restUri}
                  onChange={(e) =>
                    setCatalogConfig({ restUri: e.target.value })
                  }
                  className="text-[13px]"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="ice-database" className="text-[13px]">
                  Database / Namespace
                </Label>
                <Input
                  id="ice-database"
                  placeholder="trade_dwd"
                  value={catalogConfig.database}
                  onChange={(e) =>
                    setCatalogConfig({ database: e.target.value })
                  }
                  className="text-[13px]"
                />
              </div>
              <Button
                onClick={handleSync}
                disabled={
                  syncing || !catalogConfig.restUri || !catalogConfig.database
                }
                variant="outline"
                className="text-[13px]"
              >
                {syncing && (
                  <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                )}
                Sync Metadata
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* ---- Tables Grid ---- */}
      <div className="mt-10">
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-semibold tracking-tight">
            Synced Tables
          </h2>
          <div className="flex items-center gap-2">
            {syncedTables.length > 0 && (
              <>
                <Badge variant="secondary" className="text-[11px]">
                  {databases.length} db · {syncedTables.length} tables
                </Badge>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() => {
                    clearSyncedTables();
                    toast("已清空所有已同步表");
                  }}
                  aria-label="Clear all"
                >
                  <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                </Button>
              </>
            )}
          </div>
        </div>

        {syncedTables.length === 0 ? (
          <div className="mt-6 flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16 text-center">
            <Database className="h-8 w-8 text-muted-foreground/50" />
            <p className="mt-3 text-[13px] text-muted-foreground">
              Connect a data source to discover tables.
            </p>
            <Button
              variant="link"
              className="mt-2 h-auto p-0 text-[12px]"
              onClick={handleLoadDemo}
            >
              Load demo data for testing
            </Button>
          </div>
        ) : (
          <div className="mt-4 space-y-6">
            {databases.map((db) => (
              <div key={db}>
                <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground">
                  <Database className="h-3.5 w-3.5" />
                  {db}
                </h3>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {syncedTables
                    .filter((t) => t.database === db)
                    .map((t) => (
                      <Collapsible key={`${t.database}.${t.table_name}`}>
                        <Card className="group transition-colors hover:border-foreground/20">
                          <CollapsibleTrigger asChild>
                            <CardContent className="cursor-pointer p-4">
                              <div className="flex items-start gap-3">
                                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted/50">
                                  <Table2 className="h-4 w-4 text-muted-foreground" />
                                </div>
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center justify-between">
                                    <p className="truncate text-[13px] font-medium leading-tight text-foreground">
                                      {t.table_name}
                                    </p>
                                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
                                  </div>
                                  <div className="mt-2 flex items-center gap-2">
                                    <span className="text-[11px] text-muted-foreground">
                                      {t.columns.length > 0
                                        ? `${t.columns.length} cols`
                                        : "—"}
                                    </span>
                                    {t.columns.some(
                                      (c) => c.is_partition_key,
                                    ) && (
                                      <Badge
                                        variant="outline"
                                        className="h-[18px] px-1.5 text-[10px]"
                                      >
                                        partitioned
                                      </Badge>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </CardContent>
                          </CollapsibleTrigger>
                          {t.columns.length > 0 && (
                            <CollapsibleContent>
                              <div className="border-t border-border px-4 pb-3 pt-2">
                                <ul className="space-y-1">
                                  {t.columns.map((c) => (
                                    <li
                                      key={c.name}
                                      className="flex items-center justify-between text-[12px]"
                                    >
                                      <span className="font-mono text-foreground/80">
                                        {c.name}
                                      </span>
                                      <span className="flex items-center gap-1.5 font-mono text-muted-foreground">
                                        {c.data_type}
                                        {c.is_partition_key && (
                                          <Badge
                                            variant="outline"
                                            className="h-[16px] px-1 text-[9px]"
                                          >
                                            PK
                                          </Badge>
                                        )}
                                      </span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            </CollapsibleContent>
                          )}
                        </Card>
                      </Collapsible>
                    ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

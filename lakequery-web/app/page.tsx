"use client";

import { useState } from "react";
import axios from "axios";
import { useAppStore } from "@/lib/store";
import { useHydrated } from "@/hooks/useHydration";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ArrowRight,
  CheckCircle2,
  Copy,
  Database,
  Loader2,
  Table2,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

const dialects = ["hive", "spark", "trino", "duckdb", "presto"] as const;

export default function QueryPage() {
  const hydrated = useHydrated();
  const { llmConfig, catalogConfig, syncedTables, queryState, setQueryState } = useAppStore();
  const [loading, setLoading] = useState(false);

  const { question, dialect, result } = queryState;

  /* Derive active databases from synced tables */
  const syncedDatabases = [...new Set(syncedTables.map((t) => t.database))];

  async function handleSubmit() {
    if (!question.trim()) return;
    setLoading(true);
    setQueryState({ result: null });
    try {
      const { data } = await axios.post("/api/v1/query", {
        question,
        dialect,
        database: syncedDatabases[0] ?? catalogConfig.database,
      });
      if (data.error) {
        toast.error(data.error);
        setQueryState({
          result: {
            sql: data.sql || "",
            answer: data.answer || "",
            rows: [],
            tables: data.tables_used ?? [],
            validated: false,
          },
        });
      } else {
        setQueryState({
          result: {
            sql: data.sql,
            answer: data.answer || "",
            rows: data.execution_result ?? [],
            tables: data.tables_used ?? [],
            validated: data.validation_passed,
          },
        });
      }
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail ?? err.message;
        toast.error(`查询失败：${detail}`);
      } else {
        toast.error("查询失败：未知错误");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleCopy() {
    if (!result?.sql) return;
    try {
      await navigator.clipboard.writeText(result.sql);
      toast.success("SQL copied to clipboard");
    } catch {
      toast.error("Failed to copy");
    }
  }

  const hasKey = hydrated && !!llmConfig.apiKey;
  const hasSource = hydrated && (
    catalogConfig.type === "hms"
      ? !!catalogConfig.host
      : !!catalogConfig.restUri
  );

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      {/* Status bar */}
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant={hasKey ? "secondary" : "outline"}
          className="gap-1 text-[11px]"
        >
          {hasKey ? (
            <CheckCircle2 className="h-3 w-3 text-emerald-500" />
          ) : (
            <XCircle className="h-3 w-3 text-muted-foreground" />
          )}
          LLM: {llmConfig.model.split("/").pop()}
        </Badge>
        <Badge
          variant={hasSource ? "secondary" : "outline"}
          className="gap-1 text-[11px]"
        >
          {hasSource ? (
            <CheckCircle2 className="h-3 w-3 text-emerald-500" />
          ) : (
            <XCircle className="h-3 w-3 text-muted-foreground" />
          )}
          Catalog: {catalogConfig.type.toUpperCase()}
        </Badge>
      </div>

      {/* Heading */}
      <div className="mt-6">
        <h1 className="text-2xl font-semibold tracking-tight">
          Ask your data warehouse
        </h1>
        <p className="mt-1 text-[13px] text-muted-foreground">
          Describe what you need in natural language. LakeQuery generates,
          validates, and transpiles SQL for you.
        </p>
      </div>

      {/* Input area */}
      <div className="mt-6 space-y-3">
        <Textarea
          placeholder='例如：查下昨天各省的 DAU，按降序排列'
          value={question}
          onChange={(e) => setQueryState({ question: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit();
          }}
          className="min-h-[100px] resize-none text-[14px] leading-relaxed"
        />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Select value={dialect} onValueChange={(v) => setQueryState({ dialect: v })}>
              <SelectTrigger className="h-8 w-[120px] text-[12px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {dialects.map((d) => (
                  <SelectItem key={d} value={d} className="text-[12px]">
                    {d}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span className="text-[11px] text-muted-foreground">
              Ctrl+Enter to submit
            </span>
          </div>

          <Button
            onClick={handleSubmit}
            disabled={loading || !question.trim()}
            className="gap-1.5 text-[13px]"
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <ArrowRight className="h-3.5 w-3.5" />
            )}
            Generate SQL
          </Button>
        </div>
      </div>

      {/* Loading skeleton */}
      {loading && !result && (
        <div className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader className="pb-3">
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent className="space-y-2">
              <Skeleton className="h-[140px] w-full rounded-md" />
              <Skeleton className="h-3 w-48" />
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-3">
              <Skeleton className="h-4 w-16" />
            </CardHeader>
            <CardContent className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </CardContent>
          </Card>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Answer panel (metadata queries) */}
          {result.answer && (
            <Card className="lg:col-span-2">
              <CardHeader className="pb-3">
                <CardTitle className="text-[13px] font-medium">
                  查询结果
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="whitespace-pre-wrap text-[13px] leading-relaxed">
                  {result.answer}
                </p>
              </CardContent>
            </Card>
          )}

          {/* SQL panel */}
          {result.sql && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
              <CardTitle className="text-[13px] font-medium">
                Generated SQL
              </CardTitle>
              <div className="flex items-center gap-2">
                {result.validated && (
                  <Badge
                    variant="secondary"
                    className="gap-1 text-[10px] text-emerald-600"
                  >
                    <CheckCircle2 className="h-3 w-3" />
                    Validated
                  </Badge>
                )}
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={handleCopy}
                  aria-label="Copy SQL"
                >
                  <Copy className="h-3.5 w-3.5" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <pre className="overflow-x-auto rounded-md bg-neutral-950 p-4 text-[12.5px] leading-relaxed text-neutral-100">
                <code>{result.sql}</code>
              </pre>
              <div className="mt-3 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <Database className="h-3 w-3" />
                {result.tables.join(", ")}
              </div>
            </CardContent>
          </Card>
          )}

          {/* Result table */}
          {result.sql && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[13px] font-medium">
                Preview
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full text-[12.5px]">
                  <thead>
                    <tr className="border-b border-border bg-muted/50">
                      {Object.keys(result.rows[0] || {}).map((key) => (
                        <th
                          key={key}
                          className="px-3 py-2 text-left font-medium text-muted-foreground"
                        >
                          {key}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr
                        key={i}
                        className="border-b border-border last:border-0"
                      >
                        {Object.values(row).map((val, j) => (
                          <td key={j} className="px-3 py-2">
                            {String(val)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] text-muted-foreground">
                {result.rows.length > 0
                  ? `Showing ${result.rows.length} rows`
                  : "No execution result (SQL generated only)"}
              </p>
            </CardContent>
          </Card>
          )}
        </div>
      )}

      {/* Empty state */}
      {!result && !loading && (
        <div className="mt-16 flex flex-col items-center justify-center text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full border border-border bg-muted/50">
            <Table2 className="h-5 w-5 text-muted-foreground/60" />
          </div>
          <p className="mt-4 text-[13px] text-muted-foreground">
            Results will appear here after you submit a query.
          </p>
        </div>
      )}
    </div>
  );
}

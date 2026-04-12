"use client";

import { useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";

const CUSTOM_VALUE = "__custom__";

const presetModels = [
  "google/gemini-2.0-flash-001",
  "openai/gpt-4o",
  "openai/gpt-4o-mini",
  "anthropic/claude-sonnet-4",
  "anthropic/claude-3.5-sonnet",
  "deepseek/deepseek-chat-v3-0324",
  "deepseek/deepseek-coder",
  "google/gemini-pro-1.5",
];

export default function SettingsPage() {
  const hydrated = useHydrated();
  const { llmConfig, setLlmConfig } = useAppStore();

  const isPreset = presetModels.includes(llmConfig.model);
  const [customMode, setCustomMode] = useState(false);
  const [customModel, setCustomModel] = useState("");

  function handleModelSelect(value: string) {
    if (value === CUSTOM_VALUE) {
      setCustomMode(true);
      setCustomModel("");
    } else {
      setCustomMode(false);
      setLlmConfig({ model: value });
      toast.success("Configuration saved");
    }
  }

  function handleCustomConfirm() {
    if (!customModel.trim()) return;
    setLlmConfig({ model: customModel.trim() });
    toast.success("Configuration saved");
  }

  if (!hydrated) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-10">
        <Skeleton className="h-7 w-32" />
        <Skeleton className="mt-2 h-4 w-64" />
        <Skeleton className="mt-6 h-[320px] w-full rounded-xl" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      <p className="mt-1 text-[13px] text-muted-foreground">
        Configure your LLM provider and model preferences.
      </p>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="text-[15px]">LLM Configuration</CardTitle>
          <CardDescription>
            Provide your OpenRouter API key and select a model.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="api-key" className="text-[13px]">
              API Key
            </Label>
            <Input
              id="api-key"
              type="password"
              placeholder="sk-or-v1-..."
              value={llmConfig.apiKey}
              onChange={(e) => setLlmConfig({ apiKey: e.target.value })}
              className="font-mono text-[13px]"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="model" className="text-[13px]">
              Model
            </Label>
            <Select
              value={customMode ? CUSTOM_VALUE : isPreset ? llmConfig.model : CUSTOM_VALUE}
              onValueChange={handleModelSelect}
            >
              <SelectTrigger id="model" className="text-[13px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {presetModels.map((m) => (
                  <SelectItem key={m} value={m} className="text-[13px]">
                    {m}
                  </SelectItem>
                ))}
                <SelectItem value={CUSTOM_VALUE} className="text-[13px]">
                  Custom model...
                </SelectItem>
              </SelectContent>
            </Select>

            {(customMode || !isPreset) && (
              <div className="flex items-center gap-2 pt-1">
                <Input
                  placeholder="provider/model-name"
                  value={customMode ? customModel : llmConfig.model}
                  onChange={(e) => {
                    setCustomMode(true);
                    setCustomModel(e.target.value);
                  }}
                  className="font-mono text-[13px]"
                />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleCustomConfirm}
                  disabled={!(customMode ? customModel.trim() : false)}
                  className="shrink-0 text-[12px]"
                >
                  Apply
                </Button>
              </div>
            )}
          </div>

          <Button
            onClick={() => {
              setLlmConfig({ apiKey: llmConfig.apiKey });
              toast.success("Configuration saved");
            }}
            disabled={!llmConfig.apiKey}
            className="w-full text-[13px]"
          >
            Save Configuration
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

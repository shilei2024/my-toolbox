import type { ProviderRegistry } from "../providers/registry.ts";
import type { Phase9RemoteProviderConfig } from "./config.ts";
import { GeminiImageProvider } from "./gemini.ts";
import { JimengImageProvider } from "./jimeng.ts";
import { OpenAIImageProvider } from "./openai.ts";
import { ArkVideoProvider } from "./ark-video.ts";

export function registerPhase9RemoteProviders(registry: ProviderRegistry, config: Phase9RemoteProviderConfig, fetcher: typeof fetch = fetch): readonly string[] {
  const registered: string[] = [];
  if (config.jimeng) { registry.register(new JimengImageProvider(config.jimeng, fetcher)); registered.push("jimeng"); }
  if (config.openai) { registry.register(new OpenAIImageProvider(config.openai, fetcher)); registered.push("openai"); }
  if (config.gemini) { registry.register(new GeminiImageProvider(config.gemini, fetcher)); registered.push("gemini"); }
  if (config.arkVideo) { registry.register(new ArkVideoProvider(config.arkVideo, fetcher)); registered.push("ark-video"); }
  return registered;
}

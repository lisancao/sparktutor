/**
 * AI provider resolution and routing.
 *
 * Determines which AI backend to use (Anthropic, Copilot, OpenAI-compatible,
 * or none) and routes code review and chat requests accordingly.
 *
 * Connectivity strategy (no per-submit ping):
 *   - On startup, probe the resolved provider once and cache the outcome.
 *   - If a probe failed, the provider stays in a short cooldown window during
 *     which auto mode falls back to the next option (Copilot, local-only).
 *   - The user can re-run the probe via the "Check AI Connection" command;
 *     real request failures always surface a clear error message.
 */

import * as vscode from "vscode";
import { Bridge } from "./bridge";
import { CopilotProvider } from "./copilotProvider";
import { OpenAICompatProvider } from "./openaiProvider";
import { EvalResult } from "./types";

export type AiProviderKind = "anthropic" | "copilot" | "openai-compatible" | "none";

/** Cooldown after a failed probe during which auto mode skips the provider. */
const HEALTH_COOLDOWN_MS = 60_000;

interface BuildReviewResult {
  needsAiReview: boolean;
  localResult?: EvalResult;
  messages?: { role: string; content: string }[];
}

interface BuildChatResult {
  messages: { role: string; content: string }[];
}

interface HealthRecord {
  ok: boolean;
  checkedAt: number;
}

export class AiRouter {
  private bridge: Bridge;
  private copilot: CopilotProvider;
  private openai: OpenAICompatProvider;
  private cachedProvider: AiProviderKind | undefined;
  private healthCache: Map<string, HealthRecord> = new Map();

  constructor(bridge: Bridge) {
    this.bridge = bridge;
    this.copilot = new CopilotProvider();
    this.openai = new OpenAICompatProvider();
  }

  /**
   * Determine which AI provider to use based on settings,
   * API key presence, and Copilot availability.
   */
  async resolveProvider(): Promise<AiProviderKind> {
    const config = vscode.workspace.getConfiguration("sparktutor");
    const setting = config.get<string>("aiProvider") || "auto";

    if (setting === "anthropic") {
      this.cachedProvider = "anthropic";
      return "anthropic";
    }

    if (setting === "copilot") {
      const available = await this.copilot.isAvailable();
      this.cachedProvider = available ? "copilot" : "none";
      return this.cachedProvider;
    }

    // Accept both the new "openai-compatible" name and the legacy "openai".
    if (setting === "openai-compatible" || setting === "openai") {
      // Explicit selection: still use it even if a previous probe failed —
      // the real request will surface a clear error.
      this.cachedProvider = this.openai.isConfigured()
        ? "openai-compatible"
        : "none";
      return this.cachedProvider;
    }

    // Auto mode: Anthropic if API key set, else OpenAI-compatible if configured
    // and not in failure cooldown, else Copilot if available, else none.
    const apiKey = config.get<string>("anthropicApiKey");
    const envKey = process.env.ANTHROPIC_API_KEY;
    if (apiKey || envKey) {
      this.cachedProvider = "anthropic";
      return "anthropic";
    }

    if (this.openai.isConfigured() && !this.inHealthCooldown("openai-compatible")) {
      this.cachedProvider = "openai-compatible";
      return "openai-compatible";
    }

    const copilotAvailable = await this.copilot.isAvailable();
    if (copilotAvailable) {
      this.cachedProvider = "copilot";
      return "copilot";
    }

    this.cachedProvider = "none";
    return "none";
  }

  /** Return the last resolved provider without re-checking availability. */
  getProvider(): AiProviderKind {
    return this.cachedProvider || "none";
  }

  /** Whether the provider failed a probe recently and auto mode should skip it. */
  private inHealthCooldown(provider: AiProviderKind): boolean {
    const rec = this.healthCache.get(provider);
    if (!rec || rec.ok) {
      return false;
    }
    return Date.now() - rec.checkedAt < HEALTH_COOLDOWN_MS;
  }

  /** Record the outcome of a connectivity probe for a provider. */
  private recordHealth(provider: AiProviderKind, ok: boolean): void {
    this.healthCache.set(provider, { ok, checkedAt: Date.now() });
  }

  /**
   * Startup probe: check the resolved provider once, cache the result,
   * and surface a warning if it is unreachable. Non-blocking.
   */
  async runStartupHealthCheck(): Promise<void> {
    const result = await this.checkConnection();
    if (!result.ok) {
      vscode.window.showWarningMessage(`SparkTutor: ${result.message}`);
    }
  }

  /**
   * Test connectivity to the active AI provider.
   * Returns { ok, message } — used by the "check AI connection" command
   * and the startup probe; the outcome is cached for the cooldown logic.
   */
  async checkConnection(): Promise<{ ok: boolean; message: string }> {
    const provider = await this.resolveProvider();

    if (provider === "openai-compatible") {
      const cfg = this.openai.getConfig();
      const started = Date.now();
      try {
        await this.openai.sendRequest(
          [{ role: "user", content: "ping" }],
          8
        );
        const message = `OpenAI-compatible OK (${cfg.baseUrl} · ${cfg.model}) in ${Date.now() - started}ms`;
        this.recordHealth("openai-compatible", true);
        return { ok: true, message };
      } catch (err) {
        const message = `OpenAI-compatible check failed: ${
          err instanceof Error ? err.message : err
        }`;
        this.recordHealth("openai-compatible", false);
        return { ok: false, message };
      }
    }

    if (provider === "copilot") {
      try {
        const available = await this.copilot.isAvailable();
        if (!available) {
          this.recordHealth("copilot", false);
          return { ok: false, message: "Copilot is not available." };
        }
        await this.copilot.sendRequest(
          [{ role: "user", content: "ping" }],
          8
        );
        this.recordHealth("copilot", true);
        return { ok: true, message: "Copilot OK." };
      } catch (err) {
        const message = `Copilot check failed: ${
          err instanceof Error ? err.message : err
        }`;
        this.recordHealth("copilot", false);
        return { ok: false, message };
      }
    }

    if (provider === "anthropic") {
      try {
        const result = await this.bridge.call<{ ok: boolean; message: string }>(
          "ping",
          {}
        );
        this.recordHealth("anthropic", result.ok);
        return result;
      } catch (err) {
        const message = `Anthropic check failed: ${
          err instanceof Error ? err.message : err
        }`;
        this.recordHealth("anthropic", false);
        return { ok: false, message };
      }
    }

    return {
      ok: false,
      message:
        "No AI provider configured. Set one up in SparkTutor settings first.",
    };
  }

  /**
   * Submit code for evaluation. Routes to the appropriate AI provider.
   */
  async submitCode(params: { code: string }): Promise<EvalResult> {
    const provider = await this.resolveProvider();

    if (provider === "anthropic") {
      // Existing flow: Python handles everything
      return this.bridge.call<EvalResult>("submit", params);
    }

    if (provider === "copilot") {
      return this.reviewViaExternal(
        params,
        (messages) => this.copilot.sendRequest(messages),
        "Copilot"
      );
    }

    if (provider === "openai-compatible") {
      return this.reviewViaExternal(
        params,
        (messages) => this.openai.sendRequest(messages),
        "AI"
      );
    }

    // No provider — run local checks only via the same buildReviewPrompt path.
    const buildResult = await this.bridge.call<BuildReviewResult>(
      "buildReviewPrompt",
      params
    );
    if (buildResult.localResult) {
      return buildResult.localResult;
    }

    return {
      passed: false,
      feedback: [
        {
          line: null,
          severity: "info",
          message:
            "未配置 AI 提供方 —— 仅使用本地检查。" +
            "请设置 Anthropic API 密钥、配置 OpenAI 兼容接口，或安装 GitHub Copilot 以启用 AI 评审。",
          suggestion: null,
          category: null,
        },
      ],
      encouragement: "",
      skillSignals: [],
    };
  }

  /**
   * Handle a chat question. Routes to the appropriate AI provider.
   */
  async chat(params: {
    question: string;
    code?: string;
  }): Promise<{ answer: string }> {
    const provider = await this.resolveProvider();

    if (provider === "anthropic") {
      // Existing flow: Python handles everything
      return this.bridge.call<{ answer: string }>("chat", params);
    }

    if (provider === "copilot") {
      return this.chatViaExternal(
        params,
        (messages) => this.copilot.sendRequest(messages),
        "Copilot"
      );
    }

    if (provider === "openai-compatible") {
      return this.chatViaExternal(
        params,
        (messages) => this.openai.sendRequest(messages),
        "AI"
      );
    }

    return {
      answer:
        "未配置 AI 提供方。请设置 Anthropic API 密钥、配置 OpenAI 兼容接口，或安装 GitHub Copilot 以启用对话。",
    };
  }

  /**
   * Shared review flow for external providers (Copilot, OpenAI-compatible):
   * Python builds the prompt → TS calls the provider → Python parses the response.
   */
  private async reviewViaExternal(
    params: { code: string },
    send: (messages: { role: string; content: string }[]) => Promise<string>,
    providerName: string
  ): Promise<EvalResult> {
    const buildResult = await this.bridge.call<BuildReviewResult>(
      "buildReviewPrompt",
      params
    );

    // If local checks were sufficient, return immediately
    if (!buildResult.needsAiReview && buildResult.localResult) {
      return buildResult.localResult;
    }

    // AI review needed — call the external provider
    if (buildResult.messages) {
      try {
        const rawText = await send(buildResult.messages);
        const parsed = await this.bridge.call<EvalResult>(
          "parseReviewResponse",
          { rawText }
        );
        return parsed;
      } catch (err) {
        // Provider failed — return local result if available, else error
        if (buildResult.localResult) {
          return buildResult.localResult;
        }
        return {
          passed: false,
          feedback: [
            {
              line: null,
              severity: "warning",
              message: `${providerName} review failed: ${
                err instanceof Error ? err.message : err
              }`,
              suggestion: null,
              category: null,
            },
          ],
          encouragement: "",
          skillSignals: [],
        };
      }
    }

    // No messages and no local result — shouldn't happen, but handle gracefully
    return buildResult.localResult || {
      passed: false,
      feedback: [],
      encouragement: "",
      skillSignals: [],
    };
  }

  /**
   * Shared chat flow for external providers (Copilot, OpenAI-compatible):
   * Python builds the messages → TS calls the provider → return the text.
   */
  private async chatViaExternal(
    params: { question: string; code?: string },
    send: (messages: { role: string; content: string }[]) => Promise<string>,
    providerName: string
  ): Promise<{ answer: string }> {
    const buildResult = await this.bridge.call<BuildChatResult>(
      "buildChatPrompt",
      params
    );

    try {
      const answer = await send(buildResult.messages);
      return { answer };
    } catch (err) {
      return {
        answer: `${providerName} chat failed: ${
          err instanceof Error ? err.message : err
        }`,
      };
    }
  }
}

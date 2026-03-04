/**
 * AI provider resolution and routing.
 *
 * Determines which AI backend to use (Anthropic, Copilot, or none) and
 * routes code review and chat requests accordingly.
 */

import * as vscode from "vscode";
import { Bridge } from "./bridge";
import { CopilotProvider } from "./copilotProvider";
import { EvalResult } from "./types";

export type AiProviderKind = "anthropic" | "copilot" | "none";

interface BuildReviewResult {
  needsAiReview: boolean;
  localResult?: EvalResult;
  messages?: { role: string; content: string }[];
}

interface BuildChatResult {
  messages: { role: string; content: string }[];
}

export class AiRouter {
  private bridge: Bridge;
  private copilot: CopilotProvider;
  private cachedProvider: AiProviderKind | undefined;

  constructor(bridge: Bridge) {
    this.bridge = bridge;
    this.copilot = new CopilotProvider();
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

    // Auto mode: Anthropic if API key set, else Copilot if available, else none
    const apiKey = config.get<string>("anthropicApiKey");
    const envKey = process.env.ANTHROPIC_API_KEY;
    if (apiKey || envKey) {
      this.cachedProvider = "anthropic";
      return "anthropic";
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
      // Round-trip: Python builds prompt → TS calls Copilot → Python parses
      const buildResult = await this.bridge.call<BuildReviewResult>(
        "buildReviewPrompt",
        params
      );

      // If local checks were sufficient, return immediately
      if (!buildResult.needsAiReview && buildResult.localResult) {
        return buildResult.localResult;
      }

      // AI review needed — call Copilot
      if (buildResult.messages) {
        try {
          const rawText = await this.copilot.sendRequest(buildResult.messages);
          const parsed = await this.bridge.call<EvalResult>(
            "parseReviewResponse",
            { rawText }
          );
          return parsed;
        } catch (err) {
          // Copilot failed — return local result if available, else error
          if (buildResult.localResult) {
            return buildResult.localResult;
          }
          return {
            passed: false,
            feedback: [
              {
                line: null,
                severity: "warning",
                message: `Copilot review failed: ${err instanceof Error ? err.message : err}`,
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

    // No provider — run local checks only via the same buildReviewPrompt path
    const buildResult = await this.bridge.call<BuildReviewResult>(
      "buildReviewPrompt",
      params
    );
    if (buildResult.localResult) {
      return buildResult.localResult;
    }
    // AI review was needed but no provider available
    return {
      passed: false,
      feedback: [
        {
          line: null,
          severity: "info",
          message:
            "No AI provider configured — using local checks only. " +
            "Set an Anthropic API key or install GitHub Copilot for AI-powered review.",
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
      // Round-trip: Python builds messages → TS calls Copilot → return text
      const buildResult = await this.bridge.call<BuildChatResult>(
        "buildChatPrompt",
        params
      );

      try {
        const answer = await this.copilot.sendRequest(buildResult.messages);
        return { answer };
      } catch (err) {
        return {
          answer: `Copilot chat failed: ${err instanceof Error ? err.message : err}`,
        };
      }
    }

    // No provider
    return {
      answer:
        "No AI provider available. Set an Anthropic API key or install GitHub Copilot to enable chat.",
    };
  }
}

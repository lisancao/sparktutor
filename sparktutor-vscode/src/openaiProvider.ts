/**
 * OpenAI-compatible chat completions provider.
 *
 * Talks to any endpoint implementing the OpenAI /chat/completions schema,
 * which covers most domestic (Chinese) model APIs and local servers:
 *   - DeepSeek          https://api.deepseek.com/v1
 *   - Zhipu GLM         https://open.bigmodel.cn/api/paas/v4
 *   - Alibaba Qwen      https://dashscope.aliyuncs.com/compatible-mode/v1
 *   - Moonshot Kimi     https://api.moonshot.cn/v1
 *   - Volcengine Doubao https://ark.cn-beijing.volces.com/api/v3
 *   - SiliconFlow       https://api.siliconflow.cn/v1
 *   - Ollama (local)    http://localhost:11434/v1
 *
 * Robustness against non-uniform implementations:
 *   - URL probing: if `{baseUrl}/chat/completions` fails with 404/405/network
 *     error and the base URL has no /v1 suffix, retry `{baseUrl}/v1/chat/completions`.
 *   - max_tokens fallback: if the endpoint rejects `max_tokens`, retry without it.
 *   - Content extraction: handles string, multimodal array, and empty responses.
 *   - Extra headers: `sparktutor.openaiExtraHeaders` (JSON) is merged into the
 *     request, overriding the default `Authorization: Bearer <key>` when present
 *     (e.g. services that expect `x-api-key` or a custom auth scheme).
 */

import * as vscode from "vscode";

export interface OpenAICompatOptions {
  baseUrl: string;
  apiKey: string;
  model: string;
  extraHeaders?: Record<string, string>;
}

/** Error carrying an optional HTTP status; status 0 means a network failure. */
class OpenAICompatError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "OpenAICompatError";
    this.status = status;
  }
}

export class OpenAICompatProvider {
  /** Read base URL / API key / model from VS Code settings or env vars. */
  getConfig(): OpenAICompatOptions {
    const config = vscode.workspace.getConfiguration("sparktutor");
    const baseUrl =
      config.get<string>("openaiBaseUrl") ||
      process.env.SPARKTUTOR_OPENAI_BASE_URL ||
      "https://api.openai.com/v1";
    const apiKey =
      config.get<string>("openaiApiKey") ||
      process.env.SPARKTUTOR_OPENAI_API_KEY ||
      process.env.OPENAI_API_KEY ||
      "";
    const model =
      config.get<string>("openaiModel") ||
      process.env.SPARKTUTOR_OPENAI_MODEL ||
      "gpt-4o-mini";
    const extraHeaders =
      config.get<Record<string, string>>("openaiExtraHeaders") || {};
    return { baseUrl, apiKey, model, extraHeaders };
  }

  /** Whether the provider has enough config to make a request. */
  isConfigured(): boolean {
    const cfg = this.getConfig();
    const hasAuth =
      Boolean(cfg.apiKey) ||
      Object.keys(cfg.extraHeaders || {}).length > 0;
    return Boolean(cfg.baseUrl && cfg.model && hasAuth);
  }

  /**
   * Send a chat request to an OpenAI-compatible endpoint.
   * Messages keep their {role, content} shape — system role is natively supported.
   */
  async sendRequest(
    messages: { role: string; content: string }[],
    maxTokens = 1024
  ): Promise<string> {
    const cfg = this.getConfig();
    if (!cfg.apiKey && Object.keys(cfg.extraHeaders || {}).length === 0) {
      throw new Error("OpenAI-compatible API key is not configured.");
    }

    const candidates = this.buildUrls(cfg.baseUrl);
    let lastErr: Error | null = null;

    for (const url of candidates) {
      try {
        return await this.postChat(url, cfg, messages, maxTokens);
      } catch (err) {
        lastErr = err instanceof Error ? err : new Error(String(err));
        // Only try the next URL on endpoint-level failures (404/405/network).
        if (!this.isUrlLevelError(err)) {
          break;
        }
      }
    }

    throw lastErr || new Error("OpenAI-compatible request failed.");
  }

  /** Candidate endpoint URLs: base + /chat/completions, plus /v1 variant. */
  private buildUrls(baseUrl: string): string[] {
    const base = baseUrl.replace(/\/+$/, "");
    const urls = [`${base}/chat/completions`];
    if (!/\/v1$/i.test(base)) {
      urls.push(`${base}/v1/chat/completions`);
    }
    return urls;
  }

  private isUrlLevelError(err: unknown): boolean {
    if (err instanceof OpenAICompatError) {
      return err.status === 0 || err.status === 404 || err.status === 405;
    }
    return false;
  }

  private buildHeaders(cfg: OpenAICompatOptions): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (cfg.apiKey) {
      headers.Authorization = `Bearer ${cfg.apiKey}`;
    }
    // User-supplied headers override defaults (x-api-key, custom auth, ...).
    for (const [key, value] of Object.entries(cfg.extraHeaders || {})) {
      headers[key] = String(value);
    }
    return headers;
  }

  private buildBody(
    cfg: OpenAICompatOptions,
    messages: { role: string; content: string }[],
    maxTokens?: number
  ): Record<string, unknown> {
    const body: Record<string, unknown> = {
      model: cfg.model,
      messages,
      stream: false,
    };
    if (maxTokens !== undefined) {
      body.max_tokens = maxTokens;
    }
    return body;
  }

  private async postChat(
    url: string,
    cfg: OpenAICompatOptions,
    messages: { role: string; content: string }[],
    maxTokens: number
  ): Promise<string> {
    let resp: Response;
    try {
      resp = await fetch(url, {
        method: "POST",
        headers: this.buildHeaders(cfg),
        body: JSON.stringify(this.buildBody(cfg, messages, maxTokens)),
      });
    } catch (err) {
      throw new OpenAICompatError(
        `OpenAI-compatible request failed: ${
          err instanceof Error ? err.message : err
        }`,
        0
      );
    }

    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      // Endpoint doesn't support max_tokens — retry once without it.
      if (resp.status === 400 && /max[_ -]?tokens/i.test(detail)) {
        return this.postChatWithoutMaxTokens(url, cfg, messages);
      }
      throw new OpenAICompatError(
        `OpenAI-compatible API error (${resp.status}): ${detail.slice(0, 500)}`,
        resp.status
      );
    }

    const data = (await resp.json()) as unknown;
    return this.extractContent(data);
  }

  private async postChatWithoutMaxTokens(
    url: string,
    cfg: OpenAICompatOptions,
    messages: { role: string; content: string }[]
  ): Promise<string> {
    let resp: Response;
    try {
      resp = await fetch(url, {
        method: "POST",
        headers: this.buildHeaders(cfg),
        body: JSON.stringify(this.buildBody(cfg, messages)),
      });
    } catch (err) {
      throw new OpenAICompatError(
        `OpenAI-compatible request failed: ${
          err instanceof Error ? err.message : err
        }`,
        0
      );
    }

    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      throw new OpenAICompatError(
        `OpenAI-compatible API error (${resp.status}): ${detail.slice(0, 500)}`,
        resp.status
      );
    }

    const data = (await resp.json()) as unknown;
    return this.extractContent(data);
  }

  /**
   * Extract response text. Handles:
   *   - content: "string"
   *   - content: [{type:"text", text:"..."}, ...]  (multimodal)
   *   - missing / empty / malformed responses
   */
  private extractContent(data: unknown): string {
    const d = data as { choices?: { message?: { content?: unknown } }[] };
    const content = d.choices?.[0]?.message?.content;

    if (typeof content === "string") {
      if (content.trim()) {
        return content;
      }
      throw new OpenAICompatError(
        "OpenAI-compatible API returned an empty response.",
        200
      );
    }

    if (Array.isArray(content)) {
      const parts = content
        .map((part) => {
          if (
            part &&
            typeof part === "object" &&
            typeof (part as { text?: unknown }).text === "string"
          ) {
            return (part as { text: string }).text;
          }
          return "";
        })
        .join("");
      if (parts.trim()) {
        return parts;
      }
    }

    throw new OpenAICompatError(
      "OpenAI-compatible API returned an unexpected response format.",
      200
    );
  }
}

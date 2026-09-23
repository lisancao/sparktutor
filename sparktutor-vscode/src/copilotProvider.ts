/**
 * Wraps the VS Code Language Model API (vscode.lm) to use GitHub Copilot
 * as an AI provider for code review and chat.
 */

import * as vscode from "vscode";

export class CopilotProvider {
  /**
   * Check whether any language models are available via vscode.lm.
   */
  async isAvailable(): Promise<boolean> {
    if (typeof vscode.lm === "undefined" || !vscode.lm.selectChatModels) {
      return false;
    }
    try {
      const models = await vscode.lm.selectChatModels();
      return models.length > 0;
    } catch {
      return false;
    }
  }

  /**
   * Select a chat model, honoring the `sparktutor.copilotModel` setting.
   * Priority: exact model id match → family match → gpt-4o family → first available.
   */
  async selectModel(): Promise<vscode.LanguageModelChat> {
    if (typeof vscode.lm === "undefined" || !vscode.lm.selectChatModels) {
      throw new Error("VS Code Language Model API is not available");
    }

    const config = vscode.workspace.getConfiguration("sparktutor");
    const preferred = (config.get<string>("copilotModel") || "").trim();

    const all = await vscode.lm.selectChatModels();
    if (all.length === 0) {
      throw new Error(
        "No language models available. Is GitHub Copilot installed and signed in?"
      );
    }

    if (preferred) {
      // Exact model id match (e.g. "gpt-4o", "claude-sonnet-4-6")
      const byId = all.find((m) => m.id === preferred);
      if (byId) {
        return byId;
      }
      // Family match (e.g. "gpt-4o", "claude")
      const byFamily = await vscode.lm.selectChatModels({ family: preferred });
      if (byFamily.length > 0) {
        return byFamily[0];
      }
    }

    // Fallbacks: prefer gpt-4o family, otherwise the first available model
    const gpt4o = await vscode.lm.selectChatModels({ family: "gpt-4o" });
    if (gpt4o.length > 0) {
      return gpt4o[0];
    }
    return all[0];
  }

  /**
   * Send a request to a language model via vscode.lm.
   *
   * Messages use {role, content} format. Since vscode.lm has no system role,
   * system messages are prepended as the first user message.
   */
  async sendRequest(
    messages: { role: string; content: string }[],
    maxTokens = 1024
  ): Promise<string> {
    if (typeof vscode.lm === "undefined" || !vscode.lm.selectChatModels) {
      throw new Error("VS Code Language Model API is not available");
    }

    const model = await this.selectModel();

    // Convert messages to vscode.LanguageModelChatMessage format.
    // vscode.lm has no system role — merge system content into the first user message.
    const chatMessages: vscode.LanguageModelChatMessage[] = [];
    let systemPrefix = "";

    for (const msg of messages) {
      if (msg.role === "system") {
        systemPrefix += msg.content + "\n\n";
      } else if (msg.role === "assistant") {
        chatMessages.push(
          vscode.LanguageModelChatMessage.Assistant(msg.content)
        );
      } else {
        // User message — prepend any accumulated system content
        const content = systemPrefix
          ? systemPrefix + msg.content
          : msg.content;
        systemPrefix = "";
        chatMessages.push(
          vscode.LanguageModelChatMessage.User(content)
        );
      }
    }

    // If there was only a system message with no user message, send as user
    if (systemPrefix && chatMessages.length === 0) {
      chatMessages.push(
        vscode.LanguageModelChatMessage.User(systemPrefix.trim())
      );
    }

    // Send request and collect streamed response
    const response = await model.sendRequest(
      chatMessages,
      { maxOutputTokens: maxTokens } as vscode.LanguageModelChatRequestOptions,
      new vscode.CancellationTokenSource().token
    );

    let result = "";
    for await (const chunk of response.text) {
      result += chunk;
    }
    return result;
  }
}

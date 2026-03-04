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
   * Send a request to a language model via vscode.lm.
   * Prefers GPT-4o family models, falls back to any available model.
   *
   * Messages use {role, content} format. Since vscode.lm has no system role,
   * system messages are prepended as the first user message.
   */
  async sendRequest(
    messages: { role: string; content: string }[]
  ): Promise<string> {
    if (typeof vscode.lm === "undefined" || !vscode.lm.selectChatModels) {
      throw new Error("VS Code Language Model API is not available");
    }

    // Select model — prefer gpt-4o family
    let models = await vscode.lm.selectChatModels({ family: "gpt-4o" });
    if (models.length === 0) {
      models = await vscode.lm.selectChatModels();
    }
    if (models.length === 0) {
      throw new Error(
        "No language models available. Is GitHub Copilot installed and signed in?"
      );
    }
    const model = models[0];

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
    const response = await model.sendRequest(chatMessages, {}, new vscode.CancellationTokenSource().token);

    let result = "";
    for await (const chunk of response.text) {
      result += chunk;
    }
    return result;
  }
}

/**
 * Status bar items: execution mode, current step, depth level.
 */

import * as vscode from "vscode";

export class StatusBarManager {
  private modeItem: vscode.StatusBarItem;
  private stepItem: vscode.StatusBarItem;
  private depthItem: vscode.StatusBarItem;
  private aiProviderItem: vscode.StatusBarItem;

  constructor() {
    this.modeItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100
    );
    this.modeItem.name = "SparkTutor Mode";
    this.modeItem.command = "sparktutor.changeMode";
    this.modeItem.tooltip = "Click to change execution mode";

    this.stepItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      99
    );
    this.stepItem.name = "SparkTutor Step";

    this.depthItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      98
    );
    this.depthItem.name = "SparkTutor Depth";
    this.depthItem.command = "sparktutor.changeDepth";
    this.depthItem.tooltip = "Click to change difficulty level";

    this.aiProviderItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      97
    );
    this.aiProviderItem.name = "SparkTutor AI Provider";
    this.aiProviderItem.tooltip = "AI provider for code review and chat";
  }

  setMode(mode: string): void {
    const icons: Record<string, string> = {
      lakehouse: "$(flame)",
      local: "$(terminal)",
      dry_run: "$(beaker)",
      databricks: "$(cloud)",
      unknown: "$(question)",
    };
    const labels: Record<string, string> = {
      lakehouse: "Lakehouse",
      local: "Local",
      dry_run: "Dry-run",
      databricks: "Databricks",
      unknown: "Unknown",
    };
    this.modeItem.text = `${icons[mode] || "$(question)"} ${labels[mode] || mode}`;
    this.modeItem.show();
  }

  setStep(currentIndex: number, totalSteps: number): void {
    this.stepItem.text = `Step ${currentIndex + 1}/${totalSteps}`;
    this.stepItem.show();
  }

  setDepth(depth: string): void {
    const label = depth.charAt(0).toUpperCase() + depth.slice(1);
    this.depthItem.text = label;
    this.depthItem.show();
  }

  setAiProvider(provider: string): void {
    const labels: Record<string, string> = {
      anthropic: "$(sparkle) AI: Claude",
      copilot: "$(copilot) AI: Copilot",
      none: "$(circle-slash) AI: Local",
    };
    this.aiProviderItem.text = labels[provider] || `AI: ${provider}`;
    this.aiProviderItem.show();
  }

  dispose(): void {
    this.modeItem.dispose();
    this.stepItem.dispose();
    this.depthItem.dispose();
    this.aiProviderItem.dispose();
  }
}

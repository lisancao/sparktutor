/**
 * Wraps vscode.OutputChannel for streaming Spark execution output.
 */

import * as vscode from "vscode";

export class SparkOutputChannel {
  private channel: vscode.OutputChannel;

  constructor() {
    this.channel = vscode.window.createOutputChannel("SparkTutor");
  }

  clear(): void {
    this.channel.clear();
  }

  appendLine(text: string): void {
    this.channel.appendLine(text);
  }

  show(): void {
    this.channel.show(true); // preserveFocus
  }

  dispose(): void {
    this.channel.dispose();
  }
}

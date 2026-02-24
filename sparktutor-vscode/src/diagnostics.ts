/**
 * DiagnosticsManager: converts FeedbackItems to VS Code diagnostics (squiggles).
 */

import * as vscode from "vscode";
import { FeedbackItem } from "./types";

export class DiagnosticsManager {
  private collection: vscode.DiagnosticCollection;

  constructor() {
    this.collection =
      vscode.languages.createDiagnosticCollection("SparkTutor");
  }

  /**
   * Set diagnostics for a file based on feedback items.
   * Items without a line number are skipped (shown only in the lesson panel).
   */
  setFeedback(uri: vscode.Uri, feedback: FeedbackItem[]): void {
    const diagnostics: vscode.Diagnostic[] = [];

    for (const item of feedback) {
      if (item.line === null || item.line === undefined) {
        continue; // No line number — show in lesson panel only
      }

      // Python lines are 1-based, VS Code is 0-based
      const line = Math.max(0, item.line - 1);
      const range = new vscode.Range(line, 0, line, 1000);

      const severity = this.mapSeverity(item.severity);
      const diag = new vscode.Diagnostic(range, item.message, severity);
      diag.source = "SparkTutor";

      if (item.suggestion) {
        diag.relatedInformation = [
          new vscode.DiagnosticRelatedInformation(
            new vscode.Location(uri, range),
            item.suggestion
          ),
        ];
      }

      diagnostics.push(diag);
    }

    this.collection.set(uri, diagnostics);
  }

  clear(): void {
    this.collection.clear();
  }

  dispose(): void {
    this.collection.dispose();
  }

  private mapSeverity(
    severity: string
  ): vscode.DiagnosticSeverity {
    switch (severity) {
      case "error":
        return vscode.DiagnosticSeverity.Error;
      case "warning":
        return vscode.DiagnosticSeverity.Warning;
      case "info":
        return vscode.DiagnosticSeverity.Information;
      case "success":
        return vscode.DiagnosticSeverity.Hint;
      default:
        return vscode.DiagnosticSeverity.Information;
    }
  }
}

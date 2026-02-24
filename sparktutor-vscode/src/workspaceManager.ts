/**
 * Exercise file management: writes starter code to persistent workspace files
 * and opens them in the VS Code editor.
 */

import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

export class WorkspaceManager {
  private readonly baseDir: string;
  private currentFile: vscode.Uri | null = null;

  /** For mult_question steps: stores the selected choice from the webview. */
  private selectedChoice: string | null = null;

  /** The current step type, so we know how to read user input. */
  private currentStepCls: string = "";

  constructor() {
    this.baseDir = path.join(os.homedir(), ".sparktutor", "workspace");
  }

  /**
   * Get the file path for a given exercise step.
   * Creates directories as needed.
   */
  getFilePath(courseId: string, lessonId: string, stepIdx: number): string {
    const dir = path.join(this.baseDir, courseId, lessonId);
    fs.mkdirSync(dir, { recursive: true });
    return path.join(dir, `step_${stepIdx}.py`);
  }

  /**
   * Track what kind of step we're on so getCurrentCode() knows where to look.
   */
  setStepType(cls: string): void {
    this.currentStepCls = cls;
    this.selectedChoice = null;
  }

  /**
   * Store a multiple-choice selection from the webview.
   */
  setSelectedChoice(choice: string): void {
    this.selectedChoice = choice;
  }

  /**
   * Write starter code (or restored code) to the file and open it in the editor.
   * If the file already exists and has content, preserve it (user may have edits).
   */
  async openExercise(
    courseId: string,
    lessonId: string,
    stepIdx: number,
    starterCode: string,
    restoredCode?: string
  ): Promise<vscode.Uri> {
    const filePath = this.getFilePath(courseId, lessonId, stepIdx);

    // Determine what code to write
    let code: string;
    if (restoredCode) {
      // Restored from previous session
      code = restoredCode;
    } else if (fs.existsSync(filePath)) {
      const existing = fs.readFileSync(filePath, "utf-8");
      if (existing.trim()) {
        // File already has content — preserve user edits
        code = existing;
      } else {
        code = starterCode;
      }
    } else {
      code = starterCode;
    }

    fs.writeFileSync(filePath, code, "utf-8");
    const uri = vscode.Uri.file(filePath);

    const doc = await vscode.workspace.openTextDocument(uri);
    await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);

    this.currentFile = uri;
    return uri;
  }

  /**
   * Read the user's current input for the step.
   * - For mult_question: returns the selected choice from the webview.
   * - For cmd_question/script: reads from the editor tab (unsaved changes included).
   * - For text: returns empty (nothing to submit).
   */
  getCurrentCode(): string {
    if (this.currentStepCls === "mult_question") {
      return this.selectedChoice || "";
    }

    if (!this.currentFile) {
      return "";
    }

    // Prefer reading from the open editor (may have unsaved changes)
    const editor = vscode.window.visibleTextEditors.find(
      (e) => e.document.uri.fsPath === this.currentFile?.fsPath
    );
    if (editor) {
      return editor.document.getText();
    }

    // Fallback: read from disk
    try {
      return fs.readFileSync(this.currentFile.fsPath, "utf-8");
    } catch {
      return "";
    }
  }

  getCurrentUri(): vscode.Uri | null {
    return this.currentFile;
  }

  /**
   * Write a solution file for diff comparison.
   */
  writeSolutionFile(
    courseId: string,
    lessonId: string,
    stepIdx: number,
    solutionCode: string
  ): vscode.Uri {
    const dir = path.join(this.baseDir, courseId, lessonId);
    fs.mkdirSync(dir, { recursive: true });
    const filePath = path.join(dir, `step_${stepIdx}_solution.py`);
    fs.writeFileSync(filePath, solutionCode, "utf-8");
    return vscode.Uri.file(filePath);
  }
}

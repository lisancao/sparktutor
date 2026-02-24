/**
 * Exercise file management.
 *
 * Each lesson gets ONE file (exercise.py) that accumulates code across steps.
 * When the user advances to a code step, any new starter code is appended
 * (with a comment separator) rather than overwriting. This makes the lesson
 * iterative — a SparkSession built in step 3 is still there in step 5.
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
   * Get the single exercise file path for a lesson.
   */
  private getLessonFilePath(courseId: string, lessonId: string): string {
    const dir = path.join(this.baseDir, courseId, lessonId);
    fs.mkdirSync(dir, { recursive: true });
    return path.join(dir, "exercise.py");
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
   * Open the lesson's exercise file in the editor.
   *
   * - If restoredCode is provided (resuming a session), use that.
   * - If the file already has content, keep it (user's accumulated work).
   * - If the file is empty/missing and starterCode is given, write it.
   * - If the file has content and new starterCode is given, append it
   *   with a comment separator (so previous work is preserved).
   */
  async openExercise(
    courseId: string,
    lessonId: string,
    stepIdx: number,
    starterCode: string,
    restoredCode?: string
  ): Promise<vscode.Uri> {
    const filePath = this.getLessonFilePath(courseId, lessonId);

    if (restoredCode && !(fs.existsSync(filePath) && fs.readFileSync(filePath, "utf-8").trim())) {
      // Resuming from a previous session AND no file on disk — write the restored code
      fs.writeFileSync(filePath, restoredCode, "utf-8");
    } else if (fs.existsSync(filePath)) {
      const existing = fs.readFileSync(filePath, "utf-8");
      if (existing.trim() && starterCode.trim()) {
        // File has content AND new step has starter code → append
        // But only if the starter code isn't already in the file
        if (!existing.includes(starterCode.trim())) {
          const separator = `\n\n# --- Step ${stepIdx + 1} ---\n`;
          fs.writeFileSync(
            filePath,
            existing.trimEnd() + separator + starterCode,
            "utf-8"
          );
        }
        // else: starter code already present, don't duplicate
      } else if (!existing.trim() && starterCode.trim()) {
        // Empty file, write starter
        fs.writeFileSync(filePath, starterCode, "utf-8");
      }
      // else: file has content but no new starter → keep as-is
    } else {
      // New file
      fs.writeFileSync(filePath, starterCode || "", "utf-8");
    }

    const uri = vscode.Uri.file(filePath);

    // Reuse existing editor tab if already open
    const existingEditor = vscode.window.visibleTextEditors.find(
      (e) => e.document.uri.fsPath === filePath
    );
    if (!existingEditor) {
      const doc = await vscode.workspace.openTextDocument(uri);
      await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);
    }

    this.currentFile = uri;
    return uri;
  }

  /**
   * Read the user's current input for the step.
   * - For mult_question: returns the selected choice from the webview.
   * - For cmd_question/script: reads from the editor tab (unsaved changes included).
   * - For text: returns empty (nothing to submit).
   */
  /**
   * Open the exercise file if it already exists on disk (for non-code steps
   * during resume, so the user's accumulated code stays visible).
   */
  async openExerciseIfExists(
    courseId: string,
    lessonId: string
  ): Promise<void> {
    const filePath = this.getLessonFilePath(courseId, lessonId);
    if (!fs.existsSync(filePath)) {
      return;
    }
    const content = fs.readFileSync(filePath, "utf-8");
    if (!content.trim()) {
      return;
    }

    const uri = vscode.Uri.file(filePath);
    const existingEditor = vscode.window.visibleTextEditors.find(
      (e) => e.document.uri.fsPath === filePath
    );
    if (!existingEditor) {
      const doc = await vscode.workspace.openTextDocument(uri);
      await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);
    }
    this.currentFile = uri;
  }

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
   * Delete the exercise file for a lesson (used by reset).
   */
  deleteExerciseFile(courseId: string, lessonId: string): void {
    const filePath = this.getLessonFilePath(courseId, lessonId);
    if (fs.existsSync(filePath)) {
      fs.unlinkSync(filePath);
    }
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

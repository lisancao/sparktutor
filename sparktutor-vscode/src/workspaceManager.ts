/**
 * Exercise file management.
 *
 * Each course gets ONE main file (exercise.py) that accumulates code across
 * lessons and steps. When the user advances to a code step, any new starter
 * code is appended (with a comment separator) rather than overwriting.
 * Supplementary files (data, configs) live in per-lesson subdirectories.
 *
 * Switching courses closes old tabs (configurable) and opens the new course's
 * exercise file.
 */

import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

export class WorkspaceManager {
  private readonly baseDir: string;
  private currentFile: vscode.Uri | null = null;
  private currentCourseId: string | null = null;

  /** For mult_question steps: stores the selected choice from the webview. */
  private selectedChoice: string | null = null;

  /** The current step type, so we know how to read user input. */
  private currentStepCls: string = "";

  constructor() {
    this.baseDir = path.join(os.homedir(), ".sparktutor", "workspace");
  }

  /**
   * Get the single exercise file path for a course (one main file per course).
   */
  private getLessonFilePath(courseId: string, _lessonId: string): string {
    const dir = path.join(this.baseDir, courseId);
    fs.mkdirSync(dir, { recursive: true });
    return path.join(dir, "exercise.py");
  }

  /**
   * Get directory for supplementary files (data files, configs) created by a
   * specific lesson.
   */
  getSupplementaryDir(courseId: string, lessonId: string): string {
    const dir = path.join(this.baseDir, courseId, lessonId);
    fs.mkdirSync(dir, { recursive: true });
    return dir;
  }

  /**
   * Switch to a different course workspace.
   * Saves current file, optionally closes old course tabs, opens new course file.
   */
  async switchCourse(newCourseId: string): Promise<void> {
    const oldCourseId = this.currentCourseId;
    if (oldCourseId === newCourseId) {
      return;
    }

    // Save any dirty editors belonging to the old course
    if (oldCourseId) {
      await this.saveCourseDirtyEditors(oldCourseId);
    }

    // Close old course tabs if setting is enabled
    const autoClose = vscode.workspace
      .getConfiguration("sparktutor")
      .get<boolean>("autoCloseTabs", true);
    if (autoClose && oldCourseId) {
      await this.closeCourseTabs(oldCourseId);
    }

    this.currentCourseId = newCourseId;

    // Open the new course's exercise.py if it exists on disk
    const newFilePath = path.join(this.baseDir, newCourseId, "exercise.py");
    if (fs.existsSync(newFilePath)) {
      const content = fs.readFileSync(newFilePath, "utf-8");
      if (content.trim()) {
        const uri = vscode.Uri.file(newFilePath);
        const doc = await vscode.workspace.openTextDocument(uri);
        await vscode.window.showTextDocument(doc, {
          viewColumn: vscode.ViewColumn.One,
          preserveFocus: false,
          preview: false,
        });
        this.currentFile = uri;
      }
    }
  }

  /**
   * Close all editor tabs whose file belongs to a course's workspace directory.
   */
  private async closeCourseTabs(courseId: string): Promise<void> {
    const courseDir = path.join(this.baseDir, courseId);
    const tabsToClose: vscode.Tab[] = [];

    for (const group of vscode.window.tabGroups.all) {
      for (const tab of group.tabs) {
        const input = tab.input;
        if (input instanceof vscode.TabInputText) {
          if (input.uri.fsPath.startsWith(courseDir)) {
            tabsToClose.push(tab);
          }
        } else if (input instanceof vscode.TabInputTextDiff) {
          if (
            input.original.fsPath.startsWith(courseDir) ||
            input.modified.fsPath.startsWith(courseDir)
          ) {
            tabsToClose.push(tab);
          }
        }
      }
    }

    if (tabsToClose.length > 0) {
      await vscode.window.tabGroups.close(tabsToClose);
    }
  }

  /**
   * Save any unsaved editors belonging to a course before switching away.
   */
  private async saveCourseDirtyEditors(courseId: string): Promise<void> {
    const courseDir = path.join(this.baseDir, courseId);
    for (const doc of vscode.workspace.textDocuments) {
      if (doc.isDirty && doc.uri.fsPath.startsWith(courseDir)) {
        await doc.save();
      }
    }
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
      await vscode.window.showTextDocument(doc, {
        viewColumn: vscode.ViewColumn.One,
        preserveFocus: false,
        preview: false,
      });
    }

    this.currentFile = uri;
    this.currentCourseId = courseId;
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
    lessonId: string,
    lessonTitle?: string,
    firstStarterCode?: string
  ): Promise<void> {
    const filePath = this.getLessonFilePath(courseId, lessonId);

    // If file doesn't exist or is empty, seed it so the editor pane is
    // always populated (avoids blank screen / Copilot chat taking over).
    // Prefer the first code step's starter code over a generic header.
    if (!fs.existsSync(filePath) || !fs.readFileSync(filePath, "utf-8").trim()) {
      const content = firstStarterCode?.trim()
        ? firstStarterCode
        : lessonTitle
          ? `# ${lessonTitle}\n# Write your code below as you work through the lesson.\n`
          : `# SparkTutor Exercise\n# Write your code below as you work through the lesson.\n`;
      fs.writeFileSync(filePath, content, "utf-8");
    }

    const uri = vscode.Uri.file(filePath);
    const existingEditor = vscode.window.visibleTextEditors.find(
      (e) => e.document.uri.fsPath === filePath
    );
    if (!existingEditor) {
      const doc = await vscode.workspace.openTextDocument(uri);
      await vscode.window.showTextDocument(doc, {
        viewColumn: vscode.ViewColumn.One,
        preserveFocus: false,
        preview: false,
      });
    }
    this.currentFile = uri;
    this.currentCourseId = courseId;
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
   * Delete the exercise file for a course (used by reset).
   * Clears the course-level exercise.py file.
   */
  deleteExerciseFile(courseId: string, _lessonId: string): void {
    const filePath = path.join(this.baseDir, courseId, "exercise.py");
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
    const dir = this.getSupplementaryDir(courseId, lessonId);
    const filePath = path.join(dir, `step_${stepIdx}_solution.py`);
    fs.writeFileSync(filePath, solutionCode, "utf-8");
    return vscode.Uri.file(filePath);
  }
}

/**
 * Exercise file management.
 *
 * Each code step gets its own file, <course>/<lesson>/step_NN.py, holding
 * that step's starter code and the learner's work on it. A submit sends only
 * that file, so one exercise never runs another's code (pipeline lessons
 * reuse dataset names, and every script has its own test harness).
 * Supplementary files (solutions for diffing) live in the same lesson folder.
 *
 * Switching courses closes old tabs (configurable) and opens the most recently
 * edited exercise of the new course.
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
   * The file for one code step of a lesson.
   */
  private getStepFilePath(courseId: string, lessonId: string, stepIdx: number): string {
    const dir = path.join(this.baseDir, courseId, lessonId);
    fs.mkdirSync(dir, { recursive: true });
    return path.join(dir, `step_${String(stepIdx + 1).padStart(2, "0")}.py`);
  }

  /**
   * The most recently modified exercise file under dir (searched recursively),
   * ignoring solution files written for diffs.
   */
  private latestExerciseFile(dir: string): string | null {
    if (!fs.existsSync(dir)) {
      return null;
    }
    let latest: { file: string; mtime: number } | null = null;
    const walk = (d: string) => {
      for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
        const full = path.join(d, entry.name);
        if (entry.isDirectory()) {
          walk(full);
        } else if (/^step_\d+\.py$/.test(entry.name)) {
          const mtime = fs.statSync(full).mtimeMs;
          if (!latest || mtime > latest.mtime) {
            latest = { file: full, mtime };
          }
        }
      }
    };
    walk(dir);
    return latest ? (latest as { file: string; mtime: number }).file : null;
  }

  private async showFile(filePath: string, courseId: string): Promise<vscode.Uri> {
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
    return uri;
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

    // Open the new course's most recently edited exercise, if any
    const latest = this.latestExerciseFile(path.join(this.baseDir, newCourseId));
    if (latest) {
      await this.showFile(latest, newCourseId);
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
   * Open a code step's exercise file in the editor.
   *
   * - A file that already has content is the learner's work: keep it.
   * - Otherwise write restoredCode (resuming a session) or the starter code.
   */
  async openExercise(
    courseId: string,
    lessonId: string,
    stepIdx: number,
    starterCode: string,
    restoredCode?: string
  ): Promise<vscode.Uri> {
    const filePath = this.getStepFilePath(courseId, lessonId, stepIdx);
    const existing = fs.existsSync(filePath) ? fs.readFileSync(filePath, "utf-8") : "";
    if (!existing.trim()) {
      fs.writeFileSync(filePath, restoredCode || starterCode || "", "utf-8");
    }
    return this.showFile(filePath, courseId);
  }

  /**
   * Read the user's current input for the step.
   * - For mult_question: returns the selected choice from the webview.
   * - For cmd_question/script: reads from the editor tab (unsaved changes included).
   * - For text: returns empty (nothing to submit).
   */
  /**
   * For non-code steps: keep an exercise of this lesson in view so the editor
   * pane isn't empty. Shows the current file if it belongs to this lesson,
   * else the lesson's most recent exercise, else seeds the first code step's
   * file with its starter code (when the server says which step that is).
   */
  async openExerciseIfExists(
    courseId: string,
    lessonId: string,
    firstStarterCode?: string,
    firstCodeStepIndex?: number
  ): Promise<void> {
    const lessonDir = path.join(this.baseDir, courseId, lessonId);
    if (this.currentFile && this.currentFile.fsPath.startsWith(lessonDir + path.sep)) {
      await this.showFile(this.currentFile.fsPath, courseId);
      return;
    }
    const latest = this.latestExerciseFile(lessonDir);
    if (latest) {
      await this.showFile(latest, courseId);
      return;
    }
    if (firstCodeStepIndex !== undefined && firstCodeStepIndex >= 0) {
      await this.openExercise(courseId, lessonId, firstCodeStepIndex, firstStarterCode || "");
    }
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
   * Delete a lesson's exercise files (used by reset).
   */
  deleteExerciseFile(courseId: string, lessonId: string): void {
    const lessonDir = path.join(this.baseDir, courseId, lessonId);
    if (!fs.existsSync(lessonDir)) {
      return;
    }
    for (const name of fs.readdirSync(lessonDir)) {
      if (/^step_\d+\.py$/.test(name)) {
        fs.unlinkSync(path.join(lessonDir, name));
      }
    }
    if (this.currentFile && this.currentFile.fsPath.startsWith(lessonDir + path.sep)) {
      this.currentFile = null;
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

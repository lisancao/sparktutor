/**
 * Exercise file management.
 *
 * Each lesson gets its own exercise.py so that switching between lessons
 * preserves each lesson's code independently. Within a lesson, code steps
 * append starter code with separators as the student progresses.
 *
 * Switching courses closes old tabs and opens the new course/lesson file.
 */

import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

export class WorkspaceManager {
  private readonly baseDir: string;
  private currentFile: vscode.Uri | null = null;
  private currentCourseId: string | null = null;
  private currentLessonId: string | null = null;

  /** For mult_question steps: stores the selected choice from the webview. */
  private selectedChoice: string | null = null;

  /** The current step type, so we know how to read user input. */
  private currentStepCls: string = "";

  constructor() {
    this.baseDir = path.join(os.homedir(), ".sparktutor", "workspace");
  }

  /**
   * Get the exercise file path for a specific lesson.
   */
  private getLessonFilePath(courseId: string, lessonId: string): string {
    const dir = path.join(this.baseDir, courseId, lessonId);
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
    this.currentLessonId = null;
    this.currentFile = null;
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
   * - If the file already has content, keep it (user's work from this lesson).
   * - If the file is empty/missing and starterCode is given, write it.
   * - If isStarterFile is true, the starter code is a complete script from
   *   a StarterFile — replace the file content rather than appending.
   * - Otherwise, append new step starter code with a separator.
   */
  async openExercise(
    courseId: string,
    lessonId: string,
    stepIdx: number,
    starterCode: string,
    restoredCode?: string,
    isStarterFile?: boolean
  ): Promise<vscode.Uri> {
    const filePath = this.getLessonFilePath(courseId, lessonId);

    if (restoredCode && !(fs.existsSync(filePath) && fs.readFileSync(filePath, "utf-8").trim())) {
      // Resuming from a previous session AND no file on disk — write the restored code
      fs.writeFileSync(filePath, restoredCode, "utf-8");
    } else if (fs.existsSync(filePath)) {
      const existing = fs.readFileSync(filePath, "utf-8");
      if (isStarterFile && starterCode.trim()) {
        // StarterFile: replace content (this is a complete standalone script)
        // Only replace if the file hasn't been meaningfully edited by the user
        // (i.e., still matches a previous starter or is a generic header)
        if (!existing.trim() || existing.includes("# Write your code below")) {
          fs.writeFileSync(filePath, starterCode, "utf-8");
        }
        // else: user has already modified the file, keep their work
      } else if (existing.trim() && starterCode.trim()) {
        // Scaffolding: append if not already present
        if (!existing.includes(starterCode.trim())) {
          const separator = `\n\n# --- Step ${stepIdx + 1} ---\n`;
          fs.writeFileSync(
            filePath,
            existing.trimEnd() + separator + starterCode,
            "utf-8"
          );
        }
      } else if (!existing.trim() && starterCode.trim()) {
        fs.writeFileSync(filePath, starterCode, "utf-8");
      }
    } else {
      // New file
      fs.writeFileSync(filePath, starterCode || "", "utf-8");
    }

    const uri = vscode.Uri.file(filePath);
    await this.showExerciseEditor(filePath, uri);
    this.currentFile = uri;
    this.currentCourseId = courseId;
    this.currentLessonId = lessonId;
    return uri;
  }

  /**
   * Open the exercise file for non-code steps.
   *
   * Seeds the file with the lesson's first starter code so the editor
   * is never empty — the user always sees a script to work with.
   */
  async openExerciseIfExists(
    courseId: string,
    lessonId: string,
    lessonTitle?: string,
    firstStarterCode?: string
  ): Promise<void> {
    const filePath = this.getLessonFilePath(courseId, lessonId);

    // If file doesn't exist or is empty, seed it so the editor pane is
    // always populated. Prefer the lesson's starter code over a generic header.
    if (!fs.existsSync(filePath) || !fs.readFileSync(filePath, "utf-8").trim()) {
      const content = firstStarterCode?.trim()
        ? firstStarterCode
        : lessonTitle
          ? `# ${lessonTitle}\n# Write your code below as you work through the lesson.\n`
          : `# SparkTutor Exercise\n# Write your code below as you work through the lesson.\n`;
      fs.writeFileSync(filePath, content, "utf-8");
    }

    const uri = vscode.Uri.file(filePath);
    await this.showExerciseEditor(filePath, uri);
    this.currentFile = uri;
    this.currentCourseId = courseId;
    this.currentLessonId = lessonId;
  }

  /**
   * Show the exercise file in the editor, reusing an existing tab if open.
   * Closes the previous lesson's tab if we're switching lessons.
   */
  private async showExerciseEditor(filePath: string, uri: vscode.Uri): Promise<void> {
    // Close previous lesson's exercise tab if switching lessons
    if (this.currentFile && this.currentFile.fsPath !== filePath) {
      const tabsToClose: vscode.Tab[] = [];
      for (const group of vscode.window.tabGroups.all) {
        for (const tab of group.tabs) {
          if (tab.input instanceof vscode.TabInputText &&
              tab.input.uri.fsPath === this.currentFile.fsPath) {
            tabsToClose.push(tab);
          }
        }
      }
      if (tabsToClose.length > 0) {
        await vscode.window.tabGroups.close(tabsToClose);
      }
    }

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
    const dir = this.getSupplementaryDir(courseId, lessonId);
    const filePath = path.join(dir, `step_${stepIdx}_solution.py`);
    fs.writeFileSync(filePath, solutionCode, "utf-8");
    return vscode.Uri.file(filePath);
  }
}

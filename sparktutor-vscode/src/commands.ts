/**
 * Command implementations for SparkTutor extension.
 */

import * as vscode from "vscode";
import { Bridge } from "./bridge";
import { CourseTreeProvider } from "./courseTree";
import { DiagnosticsManager } from "./diagnostics";
import { LessonPanel } from "./lessonPanel";
import { SparkOutputChannel } from "./outputChannel";
import { StatusBarManager } from "./statusBar";
import { WorkspaceManager } from "./workspaceManager";
import {
  AdvanceResult,
  EvalResult,
  ExecResult,
  GoBackResult,
  LoadLessonResult,
  StepResult,
} from "./types";

// Current lesson state
let currentCourseId: string | undefined;
let currentLessonId: string | undefined;
let currentLessonTitle: string | undefined;
let currentIndex = 0;
let totalSteps = 0;

export function registerCommands(
  context: vscode.ExtensionContext,
  bridge: Bridge,
  treeProvider: CourseTreeProvider,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager,
  outputChannel: SparkOutputChannel,
  statusBar: StatusBarManager
): void {
  // Wire up webview button callbacks
  lessonPanel.onSubmit = () =>
    vscode.commands.executeCommand("sparktutor.submit");
  lessonPanel.onRun = () =>
    vscode.commands.executeCommand("sparktutor.run");
  lessonPanel.onNext = () =>
    vscode.commands.executeCommand("sparktutor.next");
  lessonPanel.onBack = () =>
    vscode.commands.executeCommand("sparktutor.back");
  lessonPanel.onHint = () =>
    vscode.commands.executeCommand("sparktutor.hint");
  lessonPanel.onChat = (question: string) => {
    handleChat(bridge, lessonPanel, workspace, question);
  };

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "sparktutor.openLesson",
      async (courseId: string, lessonIdx: number) => {
        await openLesson(
          bridge,
          lessonPanel,
          workspace,
          diagnostics,
          statusBar,
          courseId,
          lessonIdx
        );
      }
    ),

    vscode.commands.registerCommand("sparktutor.run", async () => {
      await runCode(bridge, workspace, outputChannel);
    }),

    vscode.commands.registerCommand("sparktutor.submit", async () => {
      await submitCode(
        bridge,
        lessonPanel,
        workspace,
        diagnostics
      );
    }),

    vscode.commands.registerCommand("sparktutor.next", async () => {
      await nextStep(
        bridge,
        lessonPanel,
        workspace,
        diagnostics,
        statusBar
      );
    }),

    vscode.commands.registerCommand("sparktutor.back", async () => {
      await prevStep(
        bridge,
        lessonPanel,
        workspace,
        diagnostics,
        statusBar
      );
    }),

    vscode.commands.registerCommand("sparktutor.hint", async () => {
      await showHint(bridge, lessonPanel);
    }),

    vscode.commands.registerCommand("sparktutor.showSolution", async () => {
      // TODO: implement solution diff
      vscode.window.showInformationMessage(
        "Solution diff not yet available for this step."
      );
    }),

    vscode.commands.registerCommand("sparktutor.changeDepth", async () => {
      const pick = await vscode.window.showQuickPick(
        ["beginner", "intermediate", "advanced"],
        { placeHolder: "Select difficulty level" }
      );
      if (pick && currentCourseId !== undefined) {
        // Reload current lesson with new depth
        const lessonIdx = 0; // TODO: track current lesson idx
        await openLesson(
          bridge,
          lessonPanel,
          workspace,
          diagnostics,
          statusBar,
          currentCourseId,
          lessonIdx,
          pick
        );
      }
    })
  );
}

async function openLesson(
  bridge: Bridge,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager,
  statusBar: StatusBarManager,
  courseId: string,
  lessonIdx: number,
  depth?: string
): Promise<void> {
  try {
    const params: Record<string, unknown> = { courseId, lessonIdx };
    if (depth) {
      params.depth = depth;
    }

    const result = await bridge.call<LoadLessonResult>("loadLesson", params);

    currentCourseId = courseId;
    currentLessonId = result.lessonId;
    currentLessonTitle = result.lessonTitle;
    currentIndex = result.currentIndex;
    totalSteps = result.totalSteps;

    // Set context for keybinding "when" clauses
    vscode.commands.executeCommand("setContext", "sparktutor.active", true);

    // Update UI
    statusBar.setStep(currentIndex, totalSteps);
    lessonPanel.updateStep(
      result.step,
      result.currentIndex,
      result.totalSteps,
      result.lessonTitle
    );

    // Open exercise file if this step has code
    if (
      result.step.cls === "script" ||
      result.step.cls === "cmd_question"
    ) {
      await workspace.openExercise(
        courseId,
        result.lessonId,
        result.currentIndex,
        result.starterCode || "",
        result.restoredCode || undefined
      );
    }

    diagnostics.clear();
  } catch (err) {
    vscode.window.showErrorMessage(
      `Failed to load lesson: ${err instanceof Error ? err.message : err}`
    );
  }
}

async function runCode(
  bridge: Bridge,
  workspace: WorkspaceManager,
  outputChannel: SparkOutputChannel
): Promise<void> {
  const code = workspace.getCurrentCode();
  if (!code.trim()) {
    vscode.window.showWarningMessage("No code to run.");
    return;
  }

  outputChannel.clear();
  outputChannel.show();
  outputChannel.appendLine("--- Running code ---");

  try {
    const result = await bridge.call<ExecResult>("run", { code });
    outputChannel.appendLine(`--- Exit code: ${result.exitCode} ---`);
  } catch (err) {
    outputChannel.appendLine(
      `--- Error: ${err instanceof Error ? err.message : err} ---`
    );
  }
}

async function submitCode(
  bridge: Bridge,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager
): Promise<void> {
  const code = workspace.getCurrentCode();
  if (!code.trim()) {
    vscode.window.showWarningMessage("No code to submit.");
    return;
  }

  try {
    const result = await bridge.call<EvalResult>("submit", { code });
    lessonPanel.showFeedback(result);

    // Set diagnostics on the exercise file
    const uri = workspace.getCurrentUri();
    if (uri) {
      diagnostics.setFeedback(uri, result.feedback);
    }

    if (result.passed) {
      vscode.window.showInformationMessage(
        result.encouragement || "Correct!"
      );
    }
  } catch (err) {
    vscode.window.showErrorMessage(
      `Submit failed: ${err instanceof Error ? err.message : err}`
    );
  }
}

async function nextStep(
  bridge: Bridge,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager,
  statusBar: StatusBarManager
): Promise<void> {
  try {
    const result = await bridge.call<AdvanceResult>("advance");

    if (result.finished) {
      lessonPanel.showFinished();
      vscode.window.showInformationMessage(
        "Congratulations! You completed the lesson!"
      );
      return;
    }

    diagnostics.clear();
    currentIndex = result.currentIndex!;
    totalSteps = result.totalSteps!;
    statusBar.setStep(currentIndex, totalSteps);

    lessonPanel.updateStep(
      result.step!,
      result.currentIndex!,
      result.totalSteps!,
      currentLessonTitle || ""
    );

    // Open exercise file for code steps
    if (
      result.step &&
      (result.step.cls === "script" || result.step.cls === "cmd_question") &&
      currentCourseId &&
      currentLessonId
    ) {
      await workspace.openExercise(
        currentCourseId,
        currentLessonId,
        result.currentIndex!,
        result.starterCode || ""
      );
    }
  } catch (err) {
    vscode.window.showErrorMessage(
      `Navigation failed: ${err instanceof Error ? err.message : err}`
    );
  }
}

async function prevStep(
  bridge: Bridge,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager,
  statusBar: StatusBarManager
): Promise<void> {
  try {
    const result = await bridge.call<GoBackResult>("goBack");

    if (result.atStart) {
      vscode.window.showInformationMessage(
        "You're at the beginning of the lesson."
      );
      return;
    }

    diagnostics.clear();
    currentIndex = result.currentIndex!;
    totalSteps = result.totalSteps!;
    statusBar.setStep(currentIndex, totalSteps);

    lessonPanel.updateStep(
      result.step!,
      result.currentIndex!,
      result.totalSteps!,
      currentLessonTitle || ""
    );

    if (
      result.step &&
      (result.step.cls === "script" || result.step.cls === "cmd_question") &&
      currentCourseId &&
      currentLessonId
    ) {
      await workspace.openExercise(
        currentCourseId,
        currentLessonId,
        result.currentIndex!,
        result.starterCode || ""
      );
    }
  } catch (err) {
    vscode.window.showErrorMessage(
      `Navigation failed: ${err instanceof Error ? err.message : err}`
    );
  }
}

async function showHint(
  bridge: Bridge,
  lessonPanel: LessonPanel
): Promise<void> {
  try {
    const result = await bridge.call<{ hint: string }>("getHint");
    lessonPanel.showHint(result.hint);
  } catch (err) {
    vscode.window.showErrorMessage(
      `Hint failed: ${err instanceof Error ? err.message : err}`
    );
  }
}

async function handleChat(
  bridge: Bridge,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  question: string
): Promise<void> {
  try {
    const code = workspace.getCurrentCode();
    const result = await bridge.call<{ answer: string }>("chat", {
      question,
      code,
    });
    lessonPanel.showChatResponse(result.answer);
  } catch (err) {
    lessonPanel.showChatResponse(
      `Error: ${err instanceof Error ? err.message : err}`
    );
  }
}

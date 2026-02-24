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
  StepData,
} from "./types";

// Current lesson state
let currentCourseId: string | undefined;
let currentLessonId: string | undefined;
let currentLessonTitle: string | undefined;
let currentLessonIdx: number | undefined;
let currentIndex = 0;
let totalSteps = 0;
let currentStep: StepData | undefined;
let currentDepth: string | undefined;

/** Session state saved to globalState for resume-on-reload. */
interface SavedSession {
  courseId: string;
  lessonIdx: number;
  lessonId: string;
  lessonTitle: string;
  depth: string;
}

let extensionContext: vscode.ExtensionContext;

function saveSession(): void {
  if (currentCourseId && currentLessonIdx !== undefined && currentLessonId && currentDepth) {
    const session: SavedSession = {
      courseId: currentCourseId,
      lessonIdx: currentLessonIdx,
      lessonId: currentLessonId,
      lessonTitle: currentLessonTitle || "",
      depth: currentDepth,
    };
    extensionContext.globalState.update("sparktutorSession", session);
  }
}

export function getSavedSession(): SavedSession | undefined {
  return extensionContext?.globalState.get<SavedSession>("sparktutorSession");
}

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
  extensionContext = context;
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
  lessonPanel.onChoiceSelect = (choice: string) => {
    workspace.setSelectedChoice(choice);
  };

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "sparktutor.openLesson",
      async (courseId: string, lessonIdx: number, depth?: string) => {
        if (depth) {
          currentDepth = depth; // pre-set so pickDepth isn't triggered
        }
        await openLesson(
          bridge,
          lessonPanel,
          workspace,
          diagnostics,
          outputChannel,
          statusBar,
          courseId,
          lessonIdx,
          depth
        );
      }
    ),

    vscode.commands.registerCommand("sparktutor.run", async () => {
      await runCode(bridge, lessonPanel, workspace, outputChannel);
    }),

    vscode.commands.registerCommand("sparktutor.submit", async () => {
      await submitCode(
        bridge,
        lessonPanel,
        workspace,
        diagnostics,
        outputChannel
      );
    }),

    vscode.commands.registerCommand("sparktutor.next", async () => {
      await nextStep(
        bridge,
        treeProvider,
        lessonPanel,
        workspace,
        diagnostics,
        outputChannel,
        statusBar
      );
    }),

    vscode.commands.registerCommand("sparktutor.back", async () => {
      await prevStep(
        bridge,
        lessonPanel,
        workspace,
        diagnostics,
        outputChannel,
        statusBar
      );
    }),

    vscode.commands.registerCommand("sparktutor.hint", async () => {
      await showHint(bridge, lessonPanel);
    }),

    vscode.commands.registerCommand("sparktutor.showSolution", async () => {
      if (
        !currentStep ||
        !currentCourseId ||
        !currentLessonId
      ) {
        vscode.window.showWarningMessage("No lesson is currently open.");
        return;
      }

      // Get solution code from the step
      const solutionCode = currentStep.solutionCode;
      if (!solutionCode) {
        vscode.window.showInformationMessage(
          "No solution available for this step."
        );
        return;
      }

      // Load solution from the lesson directory via bridge
      try {
        const result = await bridge.call<{ solution: string }>("getSolution");
        if (!result.solution) {
          vscode.window.showInformationMessage(
            "No solution available for this step."
          );
          return;
        }

        const solutionUri = workspace.writeSolutionFile(
          currentCourseId,
          currentLessonId,
          currentIndex,
          result.solution
        );

        const exerciseUri = workspace.getCurrentUri();
        if (exerciseUri) {
          await vscode.commands.executeCommand(
            "vscode.diff",
            exerciseUri,
            solutionUri,
            `Your Code ↔ Solution (Step ${currentIndex + 1})`
          );
        } else {
          // No exercise file open, just show the solution
          const doc = await vscode.workspace.openTextDocument(solutionUri);
          await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);
        }
      } catch (err) {
        vscode.window.showErrorMessage(
          `Failed to load solution: ${err instanceof Error ? err.message : err}`
        );
      }
    }),

    vscode.commands.registerCommand("sparktutor.changeDepth", async () => {
      const pick = await pickDepth();
      if (pick && currentCourseId !== undefined && currentLessonIdx !== undefined) {
        currentDepth = pick;
        await openLesson(
          bridge,
          lessonPanel,
          workspace,
          diagnostics,
          outputChannel,
          statusBar,
          currentCourseId,
          currentLessonIdx,
          pick
        );
      }
    }),

    vscode.commands.registerCommand("sparktutor.resetLesson", async () => {
      if (!currentCourseId || !currentLessonId || currentLessonIdx === undefined) {
        vscode.window.showWarningMessage("No lesson is currently open.");
        return;
      }

      const confirm = await vscode.window.showWarningMessage(
        `Reset "${currentLessonTitle || currentLessonId}"? This will clear all progress and saved code for this lesson.`,
        { modal: true },
        "Reset"
      );
      if (confirm !== "Reset") {
        return;
      }

      try {
        await bridge.call("resetLesson", {
          courseId: currentCourseId,
          lessonId: currentLessonId,
        });

        // Delete the exercise file on disk
        workspace.deleteExerciseFile(currentCourseId, currentLessonId);

        // Refresh tree and re-open the lesson from step 0
        treeProvider.refresh();
        await openLesson(
          bridge,
          lessonPanel,
          workspace,
          diagnostics,
          outputChannel,
          statusBar,
          currentCourseId,
          currentLessonIdx,
          currentDepth
        );

        vscode.window.showInformationMessage("Lesson reset successfully.");
      } catch (err) {
        vscode.window.showErrorMessage(
          `Reset failed: ${err instanceof Error ? err.message : err}`
        );
      }
    })
  );
}

async function pickDepth(): Promise<string | undefined> {
  const items: vscode.QuickPickItem[] = [
    {
      label: "Beginner",
      description: "Core concepts, guided examples, encouraging feedback",
      detail: "Best if you're new to Spark or PySpark",
    },
    {
      label: "Intermediate",
      description: "Patterns, trade-offs, configuration tuning",
      detail: "You know DataFrames but want to go deeper",
    },
    {
      label: "Advanced",
      description: "Internals, performance, production readiness",
      detail: "You've run Spark in production and want mastery",
    },
  ];
  const pick = await vscode.window.showQuickPick(items, {
    placeHolder: "Choose your experience level",
    title: "SparkTutor — Set Your Level",
  });
  return pick?.label.toLowerCase();
}

async function openLesson(
  bridge: Bridge,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager,
  outputChannel: SparkOutputChannel,
  statusBar: StatusBarManager,
  courseId: string,
  lessonIdx: number,
  depth?: string
): Promise<void> {
  try {
    // Prompt for depth on first lesson open
    if (!depth && !currentDepth) {
      const picked = await pickDepth();
      if (!picked) {
        return; // user cancelled
      }
      currentDepth = picked;
      depth = picked;
    }
    const effectiveDepth = depth || currentDepth || "beginner";

    const params: Record<string, unknown> = {
      courseId,
      lessonIdx,
      depth: effectiveDepth,
    };

    const result = await bridge.call<LoadLessonResult>("loadLesson", params);

    currentCourseId = courseId;
    currentLessonId = result.lessonId;
    currentLessonTitle = result.lessonTitle;
    currentLessonIdx = lessonIdx;
    currentIndex = result.currentIndex;
    totalSteps = result.totalSteps;
    currentStep = result.step;
    currentDepth = effectiveDepth;

    // Set context for keybinding "when" clauses
    vscode.commands.executeCommand("setContext", "sparktutor.active", true);

    // Track step type so workspace knows where to read input from
    workspace.setStepType(result.step.cls);

    // Update UI
    statusBar.setStep(currentIndex, totalSteps);
    statusBar.setDepth(effectiveDepth);
    lessonPanel.updateStep(
      result.step,
      result.currentIndex,
      result.totalSteps,
      result.lessonTitle,
      effectiveDepth
    );

    // Open exercise file for code steps, or re-open existing file on resume
    if (result.step.cls === "script" || result.step.cls === "cmd_question") {
      await workspace.openExercise(
        courseId,
        result.lessonId,
        result.currentIndex,
        result.starterCode || "",
        result.restoredCode || undefined
      );
    } else if (result.restoredCode || result.currentIndex > 0) {
      // Non-code step but resuming — open the exercise file if it exists
      // so the user's accumulated code stays visible
      await workspace.openExerciseIfExists(courseId, result.lessonId);
    }

    diagnostics.clear();
    outputChannel.clear();
    saveSession();
  } catch (err) {
    vscode.window.showErrorMessage(
      `Failed to load lesson: ${err instanceof Error ? err.message : err}`
    );
  }
}

async function runCode(
  bridge: Bridge,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  outputChannel: SparkOutputChannel
): Promise<void> {
  const code = workspace.getCurrentCode();
  if (!code.trim()) {
    vscode.window.showWarningMessage(
      "No code to run. Write your code in the editor tab on the left."
    );
    lessonPanel.notifyExecDone();
    return;
  }

  outputChannel.clear();
  outputChannel.show();
  outputChannel.appendLine("--- Running code ---\n");

  try {
    const result = await bridge.call<ExecResult>("run", { code });
    outputChannel.appendLine(`\n--- Exit code: ${result.exitCode} (${result.mode}) ---`);
  } catch (err) {
    outputChannel.appendLine(
      `\n--- Error: ${err instanceof Error ? err.message : err} ---`
    );
  } finally {
    lessonPanel.notifyExecDone();
  }
}

async function submitCode(
  bridge: Bridge,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager,
  outputChannel: SparkOutputChannel
): Promise<void> {
  const code = workspace.getCurrentCode();
  if (!code.trim()) {
    if (currentStep?.cls === "mult_question") {
      vscode.window.showWarningMessage(
        "Select an answer choice first, then click Submit."
      );
    } else {
      vscode.window.showWarningMessage(
        "No code to submit. Write your code in the editor tab on the left, then click Submit."
      );
    }
    return;
  }

  // Show progress
  outputChannel.clear();
  outputChannel.show();
  outputChannel.appendLine("--- Submitting... ---\n");

  try {
    const result = await bridge.call<EvalResult>("submit", { code });
    lessonPanel.showFeedback(result);

    // Set diagnostics on the exercise file (code steps only)
    const uri = workspace.getCurrentUri();
    if (uri && currentStep?.cls !== "mult_question") {
      diagnostics.setFeedback(uri, result.feedback);
    }

    if (result.passed) {
      outputChannel.appendLine("--- PASSED ---");
      vscode.window.showInformationMessage(
        result.encouragement || "Correct! Click Next to continue."
      );
    } else {
      outputChannel.appendLine("--- NOT PASSED --- check feedback in the lesson panel");
      // Log feedback to output too
      for (const fb of result.feedback) {
        const lineInfo = fb.line ? `Line ${fb.line}: ` : "";
        outputChannel.appendLine(`[${fb.severity}] ${lineInfo}${fb.message}`);
        if (fb.suggestion) {
          outputChannel.appendLine(`  suggestion: ${fb.suggestion}`);
        }
      }
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    outputChannel.appendLine(`\n--- Error: ${msg} ---`);
    vscode.window.showErrorMessage(`Submit failed: ${msg}`);
  }
}

async function loadStepUI(
  step: StepData,
  stepIndex: number,
  stepTotal: number,
  starterCode: string,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager,
  outputChannel: SparkOutputChannel,
  statusBar: StatusBarManager
): Promise<void> {
  currentIndex = stepIndex;
  totalSteps = stepTotal;
  currentStep = step;

  diagnostics.clear();
  outputChannel.clear();
  workspace.setStepType(step.cls);
  statusBar.setStep(stepIndex, stepTotal);

  lessonPanel.updateStep(
    step, stepIndex, stepTotal, currentLessonTitle || "", currentDepth || "beginner"
  );

  // Open exercise file for code steps
  if (
    (step.cls === "script" || step.cls === "cmd_question") &&
    currentCourseId &&
    currentLessonId
  ) {
    await workspace.openExercise(
      currentCourseId,
      currentLessonId,
      stepIndex,
      starterCode
    );
  }
}

async function nextStep(
  bridge: Bridge,
  treeProvider: CourseTreeProvider,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager,
  outputChannel: SparkOutputChannel,
  statusBar: StatusBarManager
): Promise<void> {
  try {
    // Send current code so the server persists it for resume
    const code = workspace.getCurrentCode();
    const result = await bridge.call<AdvanceResult>("advance", { code });

    if (result.finished) {
      lessonPanel.showFinished();
      treeProvider.refresh();
      vscode.window.showInformationMessage(
        "Congratulations! You completed the lesson!"
      );
      return;
    }

    await loadStepUI(
      result.step!,
      result.currentIndex!,
      result.totalSteps!,
      result.starterCode || "",
      lessonPanel,
      workspace,
      diagnostics,
      outputChannel,
      statusBar
    );
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
  outputChannel: SparkOutputChannel,
  statusBar: StatusBarManager
): Promise<void> {
  try {
    // Send current code so the server persists it for resume
    const code = workspace.getCurrentCode();
    const result = await bridge.call<GoBackResult>("goBack", { code });

    if (result.atStart) {
      vscode.window.showInformationMessage(
        "You're at the beginning of the lesson."
      );
      return;
    }

    await loadStepUI(
      result.step!,
      result.currentIndex!,
      result.totalSteps!,
      result.starterCode || "",
      lessonPanel,
      workspace,
      diagnostics,
      outputChannel,
      statusBar
    );
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

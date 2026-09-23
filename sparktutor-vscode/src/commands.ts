/**
 * Command implementations for SparkTutor extension.
 */

import * as vscode from "vscode";
import { AiRouter } from "./aiRouter";
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

export function clearSavedSession(): void {
  extensionContext?.globalState.update("sparktutorSession", undefined);
}

export function registerCommands(
  context: vscode.ExtensionContext,
  bridge: Bridge,
  treeProvider: CourseTreeProvider,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager,
  outputChannel: SparkOutputChannel,
  statusBar: StatusBarManager,
  aiRouter: AiRouter
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
    handleChat(aiRouter, lessonPanel, workspace, question);
  };
  lessonPanel.onChoiceSelect = (choice: string) => {
    workspace.setSelectedChoice(choice);
  };

  context.subscriptions.push(
    vscode.commands.registerCommand(
      "sparktutor.openLesson",
      async (courseId: string, lessonIdx: number, depth?: string, skipResumePrompt?: boolean) => {
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
          depth,
          skipResumePrompt
        );
      }
    ),

    vscode.commands.registerCommand("sparktutor.run", async () => {
      await runCode(bridge, lessonPanel, workspace, outputChannel);
    }),

    vscode.commands.registerCommand("sparktutor.submit", async () => {
      await submitCode(
        aiRouter,
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
        vscode.window.showWarningMessage("当前没有打开的课程。");
        return;
      }

      // Get solution code from the step
      const solutionCode = currentStep.solutionCode;
      if (!solutionCode) {
        vscode.window.showInformationMessage(
          "本步骤暂无参考答案。"
        );
        return;
      }

      // Load solution from the lesson directory via bridge
      try {
        const result = await bridge.call<{ solution: string }>("getSolution");
        if (!result.solution) {
          vscode.window.showInformationMessage(
            "本步骤暂无参考答案。"
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
            `你的代码 ↔ 参考答案（第 ${currentIndex + 1} 步）`
          );
        } else {
          // No exercise file open, just show the solution
          const doc = await vscode.workspace.openTextDocument(solutionUri);
          await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);
        }
      } catch (err) {
        vscode.window.showErrorMessage(
          `加载参考答案失败：${err instanceof Error ? err.message : err}`
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

    vscode.commands.registerCommand("sparktutor.changeMode", async () => {
      await pickExecutionMode();
    }),

    vscode.commands.registerCommand("sparktutor.resetLesson", async () => {
      if (!currentCourseId || !currentLessonId || currentLessonIdx === undefined) {
        vscode.window.showWarningMessage("当前没有打开的课程。");
        return;
      }

      const confirm = await vscode.window.showWarningMessage(
        `重置「${currentLessonTitle || currentLessonId}」？这将清除本课程的所有进度和已保存的代码。`,
        { modal: true },
        "重置"
      );
      if (confirm !== "重置") {
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
          currentDepth,
          true // skipResumePrompt — we just reset
        );

        vscode.window.showInformationMessage("课程已成功重置。");
      } catch (err) {
        vscode.window.showErrorMessage(
          `重置失败：${err instanceof Error ? err.message : err}`
        );
      }
    }),

    vscode.commands.registerCommand(
      "sparktutor.checkAiConnection",
      async () => {
        await checkAiConnection(aiRouter, outputChannel);
      }
    )
  );
}

async function checkAiConnection(
  aiRouter: AiRouter,
  outputChannel: SparkOutputChannel
): Promise<void> {
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "SparkTutor: Checking AI connection…",
    },
    async () => {
      const result = await aiRouter.checkConnection();
      outputChannel.appendLine(`[ai] ${result.message}`);
      if (result.ok) {
        vscode.window.showInformationMessage(`SparkTutor: ${result.message}`);
      } else {
        vscode.window.showErrorMessage(`SparkTutor: ${result.message}`);
      }
    }
  );
}

async function pickExecutionMode(): Promise<string | undefined> {
  const items: vscode.QuickPickItem[] = [
    {
      label: "Local",
      description: "pip install pyspark —— 无需 Docker",
      detail: "在同一 Python 环境中运行 Spark",
    },
    {
      label: "Lakehouse",
      description: "带 Kafka、Iceberg 等的 Docker 容器",
      detail: "需要 lakehouse-stack 和 Docker Desktop",
    },
    {
      label: "Databricks",
      description: "通过 Spark Connect 连接远程 Databricks 集群",
      detail: "需要 databricks-connect 和集群访问权限",
    },
    {
      label: "Auto",
      description: "自动检测",
      detail: "容器运行时使用 Lakehouse，否则使用 Local",
    },
  ];
  const pick = await vscode.window.showQuickPick(items, {
    placeHolder: "SparkTutor 应如何运行 Spark 代码？",
    title: "SparkTutor —— 执行模式",
  });
  if (!pick) {
    return undefined;
  }
  const value = pick.label.toLowerCase();
  await vscode.workspace
    .getConfiguration("sparktutor")
    .update("executionMode", value, vscode.ConfigurationTarget.Global);
  return value;
}

async function pickDepth(): Promise<string | undefined> {
  const items: vscode.QuickPickItem[] = [
    {
      label: "Beginner",
      description: "核心概念、引导式示例、鼓励性反馈",
      detail: "适合 Spark 或 PySpark 新手",
    },
    {
      label: "Intermediate",
      description: "设计模式、权衡分析、配置调优",
      detail: "已了解 DataFrame，希望深入学习",
    },
    {
      label: "Advanced",
      description: "内部原理、性能优化、生产就绪",
      detail: "已有生产环境 Spark 经验，追求精通",
    },
  ];
  const pick = await vscode.window.showQuickPick(items, {
    placeHolder: "选择你的经验水平",
    title: "SparkTutor —— 设置你的水平",
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
  depth?: string,
  skipResumePrompt?: boolean
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

    // Detect course switch and handle tab/workspace transition
    if (currentCourseId && courseId !== currentCourseId) {
      await workspace.switchCourse(courseId);
    }

    const params: Record<string, unknown> = {
      courseId,
      lessonIdx,
      depth: effectiveDepth,
    };

    let result = await bridge.call<LoadLessonResult>("loadLesson", params);

    // If there's saved progress, ask whether to resume or start fresh
    if (result.currentIndex > 0 && !skipResumePrompt) {
      const choice = await vscode.window.showInformationMessage(
        `「${result.lessonTitle}」—— 从第 ${result.currentIndex + 1}/${result.totalSteps} 步继续？`,
        "继续",
        "从头开始"
      );
      if (choice === "从头开始") {
        await bridge.call("resetLesson", {
          courseId,
          lessonId: result.lessonId,
        });
        workspace.deleteExerciseFile(courseId, result.lessonId);
        result = await bridge.call<LoadLessonResult>("loadLesson", params);
      } else if (!choice) {
        return; // dismissed — do nothing
      }
    }

    // Prepend prerequisites banner to the first lesson's first step
    if (result.coursePrerequisites?.length) {
      const prereqMd = "## 前置要求\n\n" +
        result.coursePrerequisites.map(p => `- ${p}`).join("\n") +
        "\n\n---\n\n";
      result.step.output = prereqMd + result.step.output;
    }

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

    // Update status bar
    statusBar.setStep(currentIndex, totalSteps);
    statusBar.setDepth(effectiveDepth);

    // Open exercise file FIRST (in Column One)
    if (result.step.cls === "script" || result.step.cls === "cmd_question") {
      // Code steps: create/append starter code
      await workspace.openExercise(
        courseId,
        result.lessonId,
        result.currentIndex,
        result.starterCode || "",
        result.restoredCode || undefined
      );
    } else {
      // Non-code steps: open exercise file (pre-populated with first starter code if missing)
      await workspace.openExerciseIfExists(courseId, result.lessonId, result.lessonTitle, result.firstStarterCode);
    }

    // THEN show the lesson panel (in Column Two) so it doesn't get displaced
    lessonPanel.updateStep(
      result.step,
      result.currentIndex,
      result.totalSteps,
      result.lessonTitle,
      effectiveDepth
    );

    diagnostics.clear();
    outputChannel.clear();
    saveSession();
  } catch (err) {
    vscode.window.showErrorMessage(
      `加载课程失败：${err instanceof Error ? err.message : err}`
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
      "没有可运行的代码。请在左侧编辑器标签页中编写代码。"
    );
    lessonPanel.notifyExecDone();
    return;
  }

  outputChannel.clear();
  outputChannel.show();
  outputChannel.appendLine("--- 运行代码 ---\n");

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
  aiRouter: AiRouter,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  diagnostics: DiagnosticsManager,
  outputChannel: SparkOutputChannel
): Promise<void> {
  const code = workspace.getCurrentCode();
  if (!code.trim()) {
    if (currentStep?.cls === "mult_question") {
      vscode.window.showWarningMessage(
        "请先选择一个答案选项，然后点击提交。"
      );
    } else {
      vscode.window.showWarningMessage(
        "没有可提交的代码。请在左侧编辑器标签页中编写代码，然后点击提交。"
      );
    }
    return;
  }

  // Show progress
  outputChannel.clear();
  outputChannel.show();
  outputChannel.appendLine("--- 提交中... ---\n");

  try {
    const result = await aiRouter.submitCode({ code });
    lessonPanel.showFeedback(result);

    // Set diagnostics on the exercise file (code steps only)
    const uri = workspace.getCurrentUri();
    if (uri && currentStep?.cls !== "mult_question") {
      diagnostics.setFeedback(uri, result.feedback);
    }

    if (result.passed) {
      outputChannel.appendLine("--- 已通过 ---");
      vscode.window.showInformationMessage(
        result.encouragement || "回答正确！点击下一步继续。"
      );
    } else {
      outputChannel.appendLine("--- 未通过 --- 请在课程面板中查看反馈");
      // Log feedback to output too
      for (const fb of result.feedback) {
        const lineInfo = fb.line ? `第 ${fb.line} 行：` : "";
        outputChannel.appendLine(`[${fb.severity}] ${lineInfo}${fb.message}`);
        if (fb.suggestion) {
          outputChannel.appendLine(`  建议：${fb.suggestion}`);
        }
      }
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    outputChannel.appendLine(`\n--- 错误：${msg} ---`);
    vscode.window.showErrorMessage(`提交失败：${msg}`);
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

  // Open exercise file FIRST (Column One)
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
  } else if (currentCourseId && currentLessonId) {
    await workspace.openExerciseIfExists(currentCourseId, currentLessonId, currentLessonTitle);
  }

  // THEN show lesson panel (Column Two) so it stays visible
  lessonPanel.updateStep(
    step, stepIndex, stepTotal, currentLessonTitle || "", currentDepth || "beginner"
  );
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
        "恭喜！你已完成本课程！"
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
      `导航失败：${err instanceof Error ? err.message : err}`
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
        "你已经在课程的开头了。"
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
      `导航失败：${err instanceof Error ? err.message : err}`
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
      `获取提示失败：${err instanceof Error ? err.message : err}`
    );
  }
}

async function handleChat(
  aiRouter: AiRouter,
  lessonPanel: LessonPanel,
  workspace: WorkspaceManager,
  question: string
): Promise<void> {
  try {
    const code = workspace.getCurrentCode();
    const result = await aiRouter.chat({ question, code });
    lessonPanel.showChatResponse(result.answer);
  } catch (err) {
    lessonPanel.showChatResponse(
      `错误：${err instanceof Error ? err.message : err}`
    );
  }
}

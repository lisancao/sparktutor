/**
 * SparkTutor VS Code extension entry point.
 */

import * as vscode from "vscode";
import { AiRouter } from "./aiRouter";
import { Bridge } from "./bridge";
import { clearSavedSession, getSavedSession, registerCommands } from "./commands";
import { CourseTreeProvider } from "./courseTree";
import { DiagnosticsManager } from "./diagnostics";
import { LessonPanel } from "./lessonPanel";
import { SparkOutputChannel } from "./outputChannel";
import { StatusBarManager } from "./statusBar";
import { WorkspaceManager } from "./workspaceManager";

let bridge: Bridge;

export async function activate(
  context: vscode.ExtensionContext
): Promise<void> {
  const outputChannel = new SparkOutputChannel();

  // Start the Python JSON-lines server
  bridge = new Bridge(context.extensionPath);
  bridge.on("log", (text: string) => outputChannel.appendLine(`[server] ${text}`));

  try {
    await bridge.start();
    outputChannel.appendLine("SparkTutor server started successfully");
  } catch (err) {
    const msg =
      err instanceof Error ? err.message : "Unknown error starting server";
    vscode.window.showErrorMessage(`SparkTutor: ${msg}`);
    return;
  }

  // Initialize managers
  const diagnostics = new DiagnosticsManager();
  const workspace = new WorkspaceManager();
  const statusBar = new StatusBarManager();
  const lessonPanel = new LessonPanel(context.extensionUri);

  // Register course tree view
  const treeProvider = new CourseTreeProvider(bridge);
  vscode.window.registerTreeDataProvider("sparktutorCourses", treeProvider);

  // Create AI router (resolves provider after startup)
  const aiRouter = new AiRouter(bridge);

  // Register all commands
  registerCommands(
    context,
    bridge,
    treeProvider,
    lessonPanel,
    workspace,
    diagnostics,
    outputChannel,
    statusBar,
    aiRouter
  );

  // Stream output notifications to the output channel
  bridge.onNotification("output", (params) => {
    outputChannel.appendLine(params.line as string);
  });

  // Detect execution mode on startup
  bridge
    .call<{ mode: string }>("detectMode")
    .then((result) => {
      statusBar.setMode(result.mode);
    })
    .catch(() => {
      statusBar.setMode("unknown");
    });

  // Resolve AI provider on startup and show in status bar
  aiRouter
    .resolveProvider()
    .then((provider) => {
      statusBar.setAiProvider(provider);
    })
    .catch(() => {
      statusBar.setAiProvider("none");
    });

  context.subscriptions.push({
    dispose: () => {
      bridge.dispose();
      diagnostics.dispose();
      outputChannel.dispose();
      statusBar.dispose();
      lessonPanel.dispose();
    },
  });

  // Show the output channel so the user knows it exists
  outputChannel.show();
  outputChannel.appendLine("SparkTutor extension activated");

  // Auto-focus the SparkTutor sidebar so courses are visible on startup
  vscode.commands.executeCommand("sparktutorCourses.focus").then(
    () => {},
    () => {} // Silently ignore if view isn't ready yet
  );

  // Check for a saved session and offer to resume
  const saved = getSavedSession();
  if (saved) {
    const resume = await vscode.window.showInformationMessage(
      `Resume "${saved.lessonTitle}" (${saved.depth})?`,
      "Resume",
      "Start Fresh"
    );
    if (resume === "Resume") {
      vscode.commands.executeCommand(
        "sparktutor.openLesson",
        saved.courseId,
        saved.lessonIdx,
        saved.depth,
        true, // skipResumePrompt — user already confirmed
      );
    } else if (resume === "Start Fresh") {
      clearSavedSession();
    }
  }
}

export function deactivate(): void {
  bridge?.dispose();
}

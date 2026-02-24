/**
 * SparkTutor VS Code extension entry point.
 */

import * as vscode from "vscode";
import { Bridge } from "./bridge";
import { registerCommands } from "./commands";
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

  // Register all commands
  registerCommands(
    context,
    bridge,
    treeProvider,
    lessonPanel,
    workspace,
    diagnostics,
    outputChannel,
    statusBar
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
  outputChannel.appendLine("SparkTutor extension activated — select a lesson from the sidebar to begin");
}

export function deactivate(): void {
  bridge?.dispose();
}

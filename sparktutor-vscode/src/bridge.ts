/**
 * Bridge: spawns the Python JSON-lines server as a subprocess
 * and provides typed RPC communication.
 */

import { ChildProcess, spawn } from "child_process";
import { EventEmitter } from "events";
import * as fs from "fs";
import * as path from "path";
import * as readline from "readline";
import * as vscode from "vscode";

export class Bridge extends EventEmitter {
  private proc: ChildProcess | null = null;
  private rl: readline.Interface | null = null;
  private nextId = 1;
  private pending = new Map<
    number,
    {
      resolve: (value: unknown) => void;
      reject: (reason: Error) => void;
      timer: NodeJS.Timeout;
    }
  >();
  private restartAttempted = false;
  private pythonPath: string;
  private extensionDir: string;

  constructor(extensionDir: string) {
    super();
    this.extensionDir = extensionDir;
    this.pythonPath =
      vscode.workspace
        .getConfiguration("sparktutor")
        .get<string>("pythonPath") || "python3";
  }

  async start(): Promise<void> {
    return this.spawn();
  }

  private spawn(): Promise<void> {
    return new Promise((resolve, reject) => {
      let settled = false;

      // Resolve the Python src/ directory.
      // Priority: 1) sparktutor.projectPath setting, 2) relative to extension dir, 3) extensionDir itself
      const config = vscode.workspace.getConfiguration("sparktutor");
      const projectPath = config.get<string>("projectPath") || "";
      let srcDir: string;
      if (projectPath && fs.existsSync(path.join(projectPath, "src", "sparktutor"))) {
        srcDir = path.join(projectPath, "src");
      } else if (fs.existsSync(path.resolve(this.extensionDir, "..", "src", "sparktutor"))) {
        // Dev mode: extension is at sparktutor-vscode/, src/ is at ../src/
        srcDir = path.resolve(this.extensionDir, "..", "src");
      } else if (fs.existsSync(path.join(this.extensionDir, "python_src", "sparktutor"))) {
        // Installed VSIX: Python source bundled inside the extension
        srcDir = path.join(this.extensionDir, "python_src");
      } else {
        srcDir = path.join(this.extensionDir, "src");
      }

      // Merge PYTHONPATH so sparktutor is importable
      const env = { ...process.env };
      env.PYTHONPATH = env.PYTHONPATH
        ? `${srcDir}:${env.PYTHONPATH}`
        : srcDir;

      // Forward VS Code settings as environment variables for the Python server
      const apiKey = config.get<string>("anthropicApiKey");
      if (apiKey) {
        env.ANTHROPIC_API_KEY = apiKey;
      }
      const model = config.get<string>("claudeModel");
      if (model) {
        env.SPARKTUTOR_CLAUDE_MODEL = model;
      }

      this.proc = spawn(this.pythonPath, ["-m", "sparktutor.server"], {
        stdio: ["pipe", "pipe", "pipe"],
        env,
      });

      if (!this.proc.stdout || !this.proc.stdin) {
        reject(new Error("Failed to open stdio pipes"));
        return;
      }

      this.rl = readline.createInterface({ input: this.proc.stdout });

      this.rl.on("line", (line: string) => {
        this.handleLine(line);
      });

      this.proc.stderr?.on("data", (data: Buffer) => {
        const text = data.toString().trim();
        if (!settled && text.includes("sparktutor-server: ready")) {
          settled = true;
          resolve();
        }
        // Forward server logs to output channel
        this.emit("log", text);
      });

      this.proc.on("close", (code: number | null) => {
        this.rejectAll(new Error(`Server exited with code ${code}`));
        this.emit("close", code);

        if (!settled) {
          settled = true;
          reject(new Error(`Server exited during startup (code ${code})`));
          return;
        }

        if (!this.restartAttempted) {
          this.restartAttempted = true;
          this.spawn().catch(() => {
            vscode.window.showErrorMessage(
              "SparkTutor server crashed and could not restart."
            );
          });
        }
      });

      this.proc.on("error", (err: Error) => {
        if (!settled) {
          settled = true;
          reject(err);
        }
      });

      // Timeout for initial startup
      setTimeout(() => {
        if (!settled) {
          settled = true;
          reject(new Error("Server startup timed out after 10s"));
        }
      }, 10000);
    });
  }

  private handleLine(line: string): void {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(line);
    } catch {
      return;
    }

    // Notification (no id field)
    if (!("id" in msg) && typeof msg.method === "string") {
      this.emit(
        `notification:${msg.method}`,
        msg.params as Record<string, unknown>
      );
      return;
    }

    // Response
    const id = msg.id as number;
    const entry = this.pending.get(id);
    if (!entry) {
      return;
    }

    this.pending.delete(id);
    clearTimeout(entry.timer);

    if (msg.error) {
      entry.reject(new Error(msg.error as string));
    } else {
      entry.resolve(msg.result);
    }
  }

  /** Check if the server process is alive and responsive. */
  isAlive(): boolean {
    return !!(this.proc && !this.proc.killed && this.proc.stdin?.writable);
  }

  async call<T = unknown>(
    method: string,
    params: Record<string, unknown> = {},
    timeoutMs = 120000
  ): Promise<T> {
    if (!this.isAlive()) {
      throw new Error(
        "SparkTutor server is not running. Try reloading the window (Ctrl+Shift+P → Reload Window)."
      );
    }

    const id = this.nextId++;

    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(
          new Error(
            `Request "${method}" timed out after ${Math.round(timeoutMs / 1000)}s. ` +
              "The server may be overloaded — try again or reload the window."
          )
        );
      }, timeoutMs);

      this.pending.set(id, {
        resolve: resolve as (value: unknown) => void,
        reject,
        timer,
      });

      const line = JSON.stringify({ id, method, params }) + "\n";
      this.proc!.stdin!.write(line);
    });
  }

  onNotification(
    method: string,
    callback: (params: Record<string, unknown>) => void
  ): void {
    this.on(`notification:${method}`, callback);
  }

  private rejectAll(err: Error): void {
    for (const [, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(err);
    }
    this.pending.clear();
  }

  dispose(): void {
    this.rejectAll(new Error("Bridge disposed"));
    this.rl?.close();
    this.proc?.kill();
    this.proc = null;
  }
}

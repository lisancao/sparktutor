/**
 * Bridge: spawns the Python JSON-lines server as a subprocess
 * and provides typed RPC communication.
 */

import { ChildProcess, spawn } from "child_process";
import { EventEmitter } from "events";
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

  constructor() {
    super();
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
      this.proc = spawn(this.pythonPath, ["-m", "sparktutor.server"], {
        stdio: ["pipe", "pipe", "pipe"],
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
        if (text.includes("sparktutor-server: ready")) {
          resolve();
        }
        // Forward server logs to output channel
        this.emit("log", text);
      });

      this.proc.on("close", (code: number | null) => {
        this.rejectAll(new Error(`Server exited with code ${code}`));
        this.emit("close", code);

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
        reject(err);
      });

      // Timeout for initial startup
      setTimeout(() => {
        reject(new Error("Server startup timed out"));
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

  async call<T = unknown>(
    method: string,
    params: Record<string, unknown> = {},
    timeoutMs = 120000
  ): Promise<T> {
    if (!this.proc?.stdin?.writable) {
      throw new Error("Server not running");
    }

    const id = this.nextId++;

    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Request ${method} timed out after ${timeoutMs}ms`));
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
    for (const [id, entry] of this.pending) {
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

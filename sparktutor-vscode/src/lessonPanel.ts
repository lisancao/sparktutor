/**
 * Lesson webview panel: renders step content, feedback, navigation, and chat.
 */

import * as vscode from "vscode";
import { EvalResult, StepData } from "./types";

export class LessonPanel {
  private panel: vscode.WebviewPanel | null = null;
  private readonly extensionUri: vscode.Uri;

  // Callbacks for webview -> extension messages
  public onSubmit?: () => void;
  public onRun?: () => void;
  public onNext?: () => void;
  public onBack?: () => void;
  public onHint?: () => void;
  public onChat?: (question: string) => void;
  public onChoiceSelect?: (choice: string) => void;

  constructor(extensionUri: vscode.Uri) {
    this.extensionUri = extensionUri;
  }

  show(): void {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Two);
      return;
    }

    this.panel = vscode.window.createWebviewPanel(
      "sparktutorLesson",
      "SparkTutor Lesson",
      vscode.ViewColumn.Two,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          vscode.Uri.joinPath(this.extensionUri, "media"),
        ],
      }
    );

    this.panel.onDidDispose(() => {
      this.panel = null;
    });

    this.panel.webview.onDidReceiveMessage((msg) => {
      switch (msg.type) {
        case "submit":
          this.onSubmit?.();
          break;
        case "run":
          this.onRun?.();
          break;
        case "next":
          this.onNext?.();
          break;
        case "back":
          this.onBack?.();
          break;
        case "hint":
          this.onHint?.();
          break;
        case "chat":
          this.onChat?.(msg.question);
          break;
        case "choiceSelect":
          this.onChoiceSelect?.(msg.choice);
          break;
      }
    });
  }

  updateStep(
    step: StepData,
    currentIndex: number,
    totalSteps: number,
    lessonTitle: string,
    depth: string = "beginner"
  ): void {
    this.show();
    this.setHtml(step, currentIndex, totalSteps, lessonTitle, depth);
  }

  showFeedback(result: EvalResult): void {
    this.panel?.webview.postMessage({
      type: "feedback",
      passed: result.passed,
      feedback: result.feedback,
      encouragement: result.encouragement,
    });
  }

  showHint(hint: string): void {
    this.panel?.webview.postMessage({
      type: "hint",
      hint,
    });
  }

  showChatResponse(answer: string): void {
    this.panel?.webview.postMessage({
      type: "chatResponse",
      answer,
    });
  }

  notifyExecDone(): void {
    this.panel?.webview.postMessage({
      type: "execDone",
    });
  }

  showFinished(): void {
    this.panel?.webview.postMessage({
      type: "finished",
    });
  }

  private setHtml(
    step: StepData,
    currentIndex: number,
    totalSteps: number,
    lessonTitle: string,
    depth: string = "beginner"
  ): void {
    if (!this.panel) {
      return;
    }

    const cssUri = this.panel.webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "lesson.css")
    );
    const jsUri = this.panel.webview.asWebviewUri(
      vscode.Uri.joinPath(this.extensionUri, "media", "lesson.js")
    );

    const progressPercent = Math.round(
      ((currentIndex + 1) / totalSteps) * 100
    );

    // Build step-type-specific content
    let instructionHtml = "";
    let choicesHtml = "";
    let actionButtonsHtml = "";

    if (step.cls === "text") {
      // Read-only content step — just Next
      instructionHtml = `<div class="instruction-banner info">Read the content above, then click <strong>Next</strong> to continue.</div>`;
      actionButtonsHtml = `<div class="actions">
        <button class="btn btn-primary" onclick="send('next')">Next &rarr;</button>
      </div>`;
    } else if (step.cls === "mult_question") {
      // Multiple choice — pick an answer, then Submit
      const choices = step.answerChoices
        ? step.answerChoices.split(";").map((c) => c.trim())
        : [];
      instructionHtml = `<div class="instruction-banner prompt">Select an answer below, then click <strong>Submit</strong>.</div>`;
      choicesHtml = `<div class="choices">${choices
        .map(
          (c) =>
            `<button class="choice-btn" onclick="selectChoice('${escapeHtml(c)}')">${escapeHtml(c)}</button>`
        )
        .join("")}</div>`;
      actionButtonsHtml = `<div class="actions">
        <button class="btn btn-success" onclick="send('submit')">&check; Submit</button>
      </div>`;
    } else if (step.cls === "cmd_question" || step.cls === "script") {
      // Code step — write code in editor, Run/Submit
      const label =
        step.cls === "script"
          ? "Write your solution in the <strong>editor tab on the left</strong>, then Run or Submit."
          : "Write your code in the <strong>editor tab on the left</strong>, then click Submit.";
      instructionHtml = `<div class="instruction-banner prompt">${label}</div>`;
      actionButtonsHtml = `<div class="actions">
        <button class="btn btn-primary" onclick="send('run')">&#9654; Run</button>
        <button class="btn btn-success" onclick="send('submit')">&check; Submit</button>
      </div>`;
    }

    this.panel.webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="${cssUri}">
  <title>SparkTutor</title>
</head>
<body>
  <div class="lesson-header">
    <h2>${escapeHtml(lessonTitle)}</h2>
    <div class="progress-bar">
      <div class="progress-fill" style="width: ${progressPercent}%"></div>
    </div>
    <div class="step-meta">
      <span class="step-label">Step ${currentIndex + 1} of ${totalSteps}</span>
      <span class="depth-badge depth-${depth}">${depth.charAt(0).toUpperCase() + depth.slice(1)}</span>
    </div>
  </div>

  <div class="step-content">
    <div class="step-output">${markdownToHtml(step.output)}</div>
    ${choicesHtml}
  </div>

  ${instructionHtml}

  <div id="loading-overlay" class="loading-overlay hidden">
    <div class="loading-spinner"></div>
    <span class="loading-text">Processing...</span>
  </div>

  <div id="feedback-section" class="feedback-section hidden"></div>

  ${actionButtonsHtml}

  <div class="nav-buttons">
    <button class="btn btn-secondary" onclick="send('back')">&larr; Back</button>
    <button class="btn btn-secondary" onclick="send('hint')">Hint</button>
    <button class="btn btn-secondary" onclick="send('next')">Next &rarr;</button>
  </div>

  <div id="hint-section" class="hint-section hidden"></div>

  <hr>
  <div class="chat-section">
    <h3>Ask the Tutor</h3>
    <div id="chat-messages" class="chat-messages"></div>
    <div class="chat-input-row">
      <input type="text" id="chat-input" placeholder="Ask a question about this step..." onkeydown="if(event.key==='Enter')sendChat()">
      <button class="btn btn-primary" onclick="sendChat()">Send</button>
    </div>
  </div>

  <script src="${jsUri}"></script>
</body>
</html>`;
  }

  dispose(): void {
    this.panel?.dispose();
    this.panel = null;
  }
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Markdown-to-HTML: code blocks, inline code, bold, italic, lists, links, paragraphs. */
function markdownToHtml(md: string): string {
  // Extract fenced code blocks BEFORE escaping (they need raw content)
  const codeBlocks: string[] = [];
  let processed = md.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    (_m, lang, code) => {
      codeBlocks.push(
        `<pre><code${lang ? ` class="language-${lang}"` : ""}>${escapeHtml(code)}</code></pre>`
      );
      return `%%CODE_BLOCK_${codeBlocks.length - 1}%%`;
    }
  );

  // Now escape the rest
  processed = escapeHtml(processed);

  // Restore code blocks (already escaped internally)
  codeBlocks.forEach((block, i) => {
    processed = processed.replace(`%%CODE_BLOCK_${i}%%`, block);
  });

  // Inline code: `...`
  processed = processed.replace(/`([^`\n]+)`/g, "<code>$1</code>");

  // Bold: **...**
  processed = processed.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // Italic: *...* (but not inside <strong>)
  processed = processed.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");

  // Links: [text](url)
  processed = processed.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
    '<a href="$2">$1</a>'
  );

  // Numbered lists: lines starting with 1. 2. etc
  processed = processed.replace(/^(\d+)\. (.+)$/gm, "<li>$2</li>");
  processed = processed.replace(/((?:<li>.*<\/li>\n?)+)/g, (match) => {
    // Detect if original had numbers (ol) or bullets (ul) — we already converted both to <li>
    return `<ol>${match}</ol>`;
  });

  // Bullet lists: lines starting with - or *  (after numbered, so * doesn't clash)
  processed = processed.replace(/^[*-] (.+)$/gm, "<li>$1</li>");
  processed = processed.replace(/((?:<li>.*<\/li>\n?)+)/g, (match) => {
    // If already wrapped in <ol>, skip
    if (match.startsWith("<ol>")) { return match; }
    return `<ul>${match}</ul>`;
  });

  // Paragraphs: split on blank lines, wrap non-block content in <p>
  const blocks = processed.split(/\n{2,}/);
  const result = blocks
    .map((block) => {
      const trimmed = block.trim();
      if (!trimmed) { return ""; }
      // Don't wrap block-level elements
      if (
        trimmed.startsWith("<pre>") ||
        trimmed.startsWith("<ul>") ||
        trimmed.startsWith("<ol>") ||
        trimmed.startsWith("<h")
      ) {
        return trimmed;
      }
      // Convert single newlines within a paragraph to <br>
      return `<p>${trimmed.replace(/\n/g, "<br>")}</p>`;
    })
    .join("\n");

  return result;
}

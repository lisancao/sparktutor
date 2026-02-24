/** SparkTutor lesson webview interactivity. */

// VS Code webview API
const vscode = acquireVsCodeApi();

/**
 * Send a message to the extension (for button clicks).
 */
function send(type) {
  vscode.postMessage({ type });
}

/**
 * Handle multiple-choice selection.
 */
function selectChoice(choice) {
  // Highlight selected button
  document.querySelectorAll('.choice-btn').forEach(btn => {
    btn.classList.remove('selected');
    if (btn.textContent.trim() === choice) {
      btn.classList.add('selected');
    }
  });
  vscode.postMessage({ type: 'choiceSelect', choice });
}

/**
 * Send a chat question.
 */
function sendChat() {
  const input = document.getElementById('chat-input');
  if (!input) return;
  const question = input.value.trim();
  if (!question) return;

  // Show user message
  addChatMessage(question, 'user');
  input.value = '';

  vscode.postMessage({ type: 'chat', question });
}

function addChatMessage(text, role) {
  const container = document.getElementById('chat-messages');
  if (!container) return;
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  div.textContent = text;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

/**
 * Handle messages from the extension.
 */
window.addEventListener('message', event => {
  const msg = event.data;

  switch (msg.type) {
    case 'feedback':
      showFeedback(msg);
      break;
    case 'hint':
      showHint(msg.hint);
      break;
    case 'chatResponse':
      addChatMessage(msg.answer, 'tutor');
      break;
    case 'finished':
      showFinished();
      break;
  }
});

function showFeedback(data) {
  const section = document.getElementById('feedback-section');
  if (!section) return;

  section.classList.remove('hidden', 'feedback-passed', 'feedback-failed');
  section.classList.add(data.passed ? 'feedback-passed' : 'feedback-failed');

  let html = '';

  if (data.feedback && data.feedback.length > 0) {
    for (const item of data.feedback) {
      const lineInfo = item.line ? `Line ${item.line}: ` : '';
      html += `<div class="feedback-item feedback-${item.severity}">`;
      html += `<strong>${lineInfo}${item.message}</strong>`;
      if (item.suggestion) {
        html += `<br><em>${item.suggestion}</em>`;
      }
      html += `</div>`;
    }
  }

  if (data.encouragement) {
    html += `<div class="encouragement">${data.encouragement}</div>`;
  }

  if (!html) {
    html = data.passed
      ? '<div class="feedback-item feedback-success"><strong>Correct!</strong></div>'
      : '<div class="feedback-item feedback-error"><strong>Not quite. Try again.</strong></div>';
  }

  section.innerHTML = html;
}

function showHint(hint) {
  const section = document.getElementById('hint-section');
  if (!section) return;
  section.classList.remove('hidden');
  section.textContent = hint;
}

function showFinished() {
  const content = document.querySelector('.step-content');
  if (content) {
    content.innerHTML = `
      <div class="finished-banner">
        <h2>Lesson Complete!</h2>
        <p>Great job! Select another lesson from the sidebar to continue learning.</p>
      </div>
    `;
  }
  // Hide action buttons
  const actions = document.querySelector('.actions');
  if (actions) actions.style.display = 'none';
}

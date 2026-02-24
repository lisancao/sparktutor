/** SparkTutor lesson webview interactivity. */

// VS Code webview API
const vscode = acquireVsCodeApi();

// --- Markdown rendering ---

/**
 * Escape HTML entities to prevent XSS.
 */
function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Convert markdown text to HTML.
 * Handles: fenced code blocks, inline code, bold, italic, bullet lists, links, line breaks.
 */
function markdownToHtml(md) {
  let html = escapeHtml(md);

  // Fenced code blocks: ```lang\n...\n```
  html = html.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    function (_, lang, code) {
      const cls = lang ? ' class="language-' + lang + '"' : '';
      return '<pre><code' + cls + '>' + code + '</code></pre>';
    }
  );

  // Inline code: `...`
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');

  // Bold: **...**
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Italic: *...*  (but not inside <strong> tags from above)
  html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');

  // Links: [text](url)
  html = html.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g,
    '<a href="$2">$1</a>'
  );

  // Bullet lists: lines starting with - or *
  html = html.replace(/^([*-]) (.+)$/gm, '<li>$2</li>');
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

  // Line breaks — but not inside <pre> blocks
  // First protect <pre> blocks, then convert \n to <br>, then restore
  const preBlocks = [];
  html = html.replace(/<pre>[\s\S]*?<\/pre>/g, function (match) {
    preBlocks.push(match);
    return '%%PRE_BLOCK_' + (preBlocks.length - 1) + '%%';
  });
  html = html.replace(/\n/g, '<br>');
  preBlocks.forEach(function (block, i) {
    html = html.replace('%%PRE_BLOCK_' + i + '%%', block);
  });

  return html;
}

// --- Message sending ---

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
  document.querySelectorAll('.choice-btn').forEach(function (btn) {
    btn.classList.remove('selected');
    if (btn.textContent.trim() === choice) {
      btn.classList.add('selected');
    }
  });
  vscode.postMessage({ type: 'choiceSelect', choice: choice });
}

/**
 * Send a chat question.
 */
function sendChat() {
  const input = document.getElementById('chat-input');
  if (!input) return;
  const question = input.value.trim();
  if (!question) return;

  addChatMessage(question, 'user');
  input.value = '';

  vscode.postMessage({ type: 'chat', question: question });
}

function addChatMessage(text, role) {
  const container = document.getElementById('chat-messages');
  if (!container) return;
  const div = document.createElement('div');
  div.className = 'chat-msg ' + role;
  // User messages: plain text. Tutor messages: render markdown.
  if (role === 'tutor') {
    div.innerHTML = markdownToHtml(text);
  } else {
    div.textContent = text;
  }
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// --- Message handling ---

window.addEventListener('message', function (event) {
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

  // Clear pass/fail banner
  if (data.passed) {
    html += '<div class="feedback-verdict feedback-verdict-pass">&#10004; Passed</div>';
  } else {
    html += '<div class="feedback-verdict feedback-verdict-fail">&#10008; Not Passed</div>';
  }

  if (data.feedback && data.feedback.length > 0) {
    // Group feedback by category
    var bugs = [];
    var conventions = [];
    var bestPractices = [];
    var other = [];

    for (var i = 0; i < data.feedback.length; i++) {
      var item = data.feedback[i];
      if (item.category === 'bug') bugs.push(item);
      else if (item.category === 'convention') conventions.push(item);
      else if (item.category === 'best_practice') bestPractices.push(item);
      else other.push(item);
    }

    function renderGroup(items, label, cssClass) {
      if (items.length === 0) return '';
      var out = '<div class="feedback-group">';
      out += '<div class="feedback-group-label ' + cssClass + '">' + label + '</div>';
      for (var j = 0; j < items.length; j++) {
        var item = items[j];
        var lineInfo = item.line ? 'Line ' + item.line + ': ' : '';
        out += '<div class="feedback-item feedback-' + item.severity + '">';
        out += '<strong>' + lineInfo + markdownToHtml(item.message) + '</strong>';
        if (item.suggestion) {
          out += '<br><em>' + markdownToHtml(item.suggestion) + '</em>';
        }
        out += '</div>';
      }
      out += '</div>';
      return out;
    }

    html += renderGroup(bugs, 'Bugs', 'label-bug');
    html += renderGroup(conventions, 'Convention', 'label-convention');
    html += renderGroup(bestPractices, 'Best Practice (optional)', 'label-best-practice');
    html += renderGroup(other, '', 'label-other');
  }

  if (data.encouragement) {
    html += '<div class="encouragement">' + markdownToHtml(data.encouragement) + '</div>';
  }

  section.innerHTML = html;
}

function showHint(hint) {
  const section = document.getElementById('hint-section');
  if (!section) return;
  section.classList.remove('hidden');
  section.innerHTML = markdownToHtml(hint);
}

function showFinished() {
  const content = document.querySelector('.step-content');
  if (content) {
    content.innerHTML =
      '<div class="finished-banner">' +
      '<h2>Lesson Complete!</h2>' +
      '<p>Great job! Select another lesson from the sidebar to continue learning.</p>' +
      '</div>';
  }
  const actions = document.querySelector('.actions');
  if (actions) actions.style.display = 'none';
}

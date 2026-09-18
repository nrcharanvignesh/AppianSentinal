/* ==========================================================================
   Appian Sentinel -- Client-side chat & session management
   ========================================================================== */

(function () {
  "use strict";

  /* ----- Constants ------------------------------------------------------ */

  const RECONNECT_DELAY_MS = 2000;
  const MAX_RECONNECT_DELAY_MS = 30000;
  const STEP_NAMES = {
    1: "Requirement Analysis",
    2: "Codebase Analysis",
    3: "Design",
    4: "Implementation",
    5: "Dependency Check",
    6: "Performance Check",
    7: "Code Quality Check",
    8: "Test Case Generation",
    9: "Final Packaging",
  };

  /* ----- DOM refs ------------------------------------------------------- */

  const dom = {
    messages: document.getElementById("chat-messages"),
    textarea: document.getElementById("chat-textarea"),
    sendBtn: document.getElementById("chat-send"),
    statusBadge: document.getElementById("header-status"),
    connectionDot: document.getElementById("connection-dot"),
    themeToggle: document.getElementById("theme-toggle"),

    // Left sidebar
    zipUpload: document.getElementById("zip-upload"),
    zipInput: document.getElementById("zip-input"),
    storyUpload: document.getElementById("story-upload"),
    storyInput: document.getElementById("story-input"),
    objectTree: document.getElementById("object-tree"),
    codebaseSummary: document.getElementById("codebase-summary"),

    // Right sidebar
    stepList: document.getElementById("step-list"),
    iterationBadge: document.getElementById("iteration-badge"),
    testResults: document.getElementById("test-results"),
    downloadBtn: document.getElementById("download-btn"),

    // Settings modal
    settingsBtn: document.getElementById("settings-btn"),
    settingsOverlay: document.getElementById("settings-overlay"),
    settingsClose: document.getElementById("settings-close"),
    settingsCancel: document.getElementById("settings-cancel"),
    settingsSave: document.getElementById("settings-save"),
    settingsTest: document.getElementById("settings-test"),
    settingBaseUrl: document.getElementById("setting-base-url"),
    settingApiKey: document.getElementById("setting-api-key"),
    settingPrimaryModel: document.getElementById("setting-primary-model"),
    settingFastModel: document.getElementById("setting-fast-model"),
    connectionStatus: document.getElementById("connection-status"),
  };

  /* ----- State ---------------------------------------------------------- */

  let ws = null;
  let reconnectDelay = RECONNECT_DELAY_MS;
  let sessionId = new URLSearchParams(window.location.search).get("session") || "default";

  /* ----- Theme ---------------------------------------------------------- */

  function initTheme() {
    const saved = localStorage.getItem("sentinel-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    updateThemeIcon();
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("sentinel-theme", next);
    updateThemeIcon();
  }

  function updateThemeIcon() {
    if (!dom.themeToggle) return;
    const isDark = document.documentElement.getAttribute("data-theme") !== "light";
    dom.themeToggle.textContent = isDark ? "☀" : "☾";
    dom.themeToggle.title = isDark ? "Switch to light theme" : "Switch to dark theme";
  }

  /* ----- WebSocket ------------------------------------------------------ */

  function connectWS() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws?session_id=${sessionId}`;
    ws = new WebSocket(url);

    ws.onopen = function () {
      reconnectDelay = RECONNECT_DELAY_MS;
      setConnected(true);
    };

    ws.onclose = function () {
      setConnected(false);
      scheduleReconnect();
    };

    ws.onerror = function () {
      setConnected(false);
    };

    ws.onmessage = function (event) {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (_) {
        return;
      }
      handleServerMessage(payload);
    };
  }

  function scheduleReconnect() {
    setTimeout(function () {
      connectWS();
      reconnectDelay = Math.min(reconnectDelay * 1.5, MAX_RECONNECT_DELAY_MS);
    }, reconnectDelay);
  }

  function setConnected(flag) {
    if (!dom.connectionDot) return;
    dom.connectionDot.className = flag
      ? "connection-dot connection-dot--connected"
      : "connection-dot connection-dot--disconnected";
  }

  function wsSend(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  /* ----- Incoming message routing --------------------------------------- */

  function handleServerMessage(payload) {
    switch (payload.type) {
      case "message":
        var msg = payload.data;
        if (msg && msg.metadata && msg.metadata.progress) {
          renderProgress(msg);
        } else {
          renderMessage(msg);
        }
        break;
      case "state":
        applyStateSnapshot(payload);
        break;
      case "ack":
        break;
      case "pong":
        break;
      default:
        console.log("Unknown WS message type:", payload.type);
    }
  }

  /* ----- Progress bar rendering ------------------------------------------ */

  var _progressEl = null;

  function renderProgress(msg) {
    var meta = msg.metadata || {};
    var current = meta.current || 0;
    var total = meta.total || 1;
    var phase = meta.phase || "";
    var pct = Math.min(100, Math.round((current / total) * 100));
    var detail = msg.content || "";

    if (!_progressEl) {
      _progressEl = document.createElement("div");
      _progressEl.className = "progress-card";
      _progressEl.innerHTML =
        '<div class="progress-card__header">' +
          '<span class="progress-card__phase"></span>' +
          '<span class="progress-card__pct"></span>' +
        '</div>' +
        '<div class="progress-card__bar-track">' +
          '<div class="progress-card__bar-fill"></div>' +
        '</div>' +
        '<div class="progress-card__detail"></div>';
      dom.messages.appendChild(_progressEl);
    }

    var phaseLabel = {
      upload: "Uploading",
      extract: "Extracting ZIP",
      metadata: "Reading metadata",
      parsing: "Parsing objects",
      dependencies: "Building dependencies",
      complete: "Complete",
    }[phase] || phase;

    _progressEl.querySelector(".progress-card__phase").textContent = phaseLabel;
    _progressEl.querySelector(".progress-card__pct").textContent = pct + "%";
    _progressEl.querySelector(".progress-card__bar-fill").style.width = pct + "%";
    _progressEl.querySelector(".progress-card__detail").textContent = detail;

    if (phase === "complete") {
      _progressEl.classList.add("progress-card--done");
      _progressEl = null;
    }

    scrollToBottom();
  }

  /* ----- State snapshot ------------------------------------------------- */

  function applyStateSnapshot(payload) {
    const data = payload.data || {};
    updateStatusBadge(data.status);
    updateStepProgress(data.current_step);
    updateIterationBadge(data.iteration, data.max_iterations);

    // Re-render conversation history
    if (payload.messages && payload.messages.length) {
      dom.messages.innerHTML = "";
      payload.messages.forEach(function (m) {
        renderMessage(m);
      });
    }

    // Show any pending questions
    if (payload.pending_questions && payload.pending_questions.length) {
      payload.pending_questions.forEach(function (q) {
        renderQuestion(q);
      });
    }
  }

  /* ----- Message rendering ---------------------------------------------- */

  function renderMessage(msg) {
    const el = document.createElement("div");
    const role = msg.role || "assistant";
    const mtype = msg.message_type || "text";

    // Base classes
    el.className = "message message--" + role;
    if (mtype === "error") el.classList.add("message--error");
    if (mtype === "question") el.classList.add("message--question");

    // Step badge
    if (msg.step && role !== "user") {
      const badge = document.createElement("div");
      badge.className = "message__step-badge";
      badge.textContent = "Step " + msg.step + ": " + (STEP_NAMES[msg.step] || "");
      el.appendChild(badge);
    }

    // Content
    const content = document.createElement("div");
    if (mtype === "code" || mtype === "diff") {
      content.innerHTML = renderCodeContent(msg.content, mtype);
    } else {
      content.innerHTML = renderMarkdown(msg.content);
    }
    el.appendChild(content);

    // Question options
    if (mtype === "question" && msg.metadata && msg.metadata.options) {
      const opts = document.createElement("div");
      opts.className = "question-options";
      msg.metadata.options.forEach(function (opt) {
        const btn = document.createElement("button");
        btn.textContent = opt;
        btn.onclick = function () {
          sendMessage(opt);
        };
        opts.appendChild(btn);
      });
      el.appendChild(opts);
    }

    dom.messages.appendChild(el);
    scrollToBottom();
  }

  function renderQuestion(q) {
    const el = document.createElement("div");
    el.className = "message message--assistant message--question";

    const content = document.createElement("div");
    content.innerHTML = renderMarkdown(q.question);
    el.appendChild(content);

    if (q.options && q.options.length) {
      const opts = document.createElement("div");
      opts.className = "question-options";
      q.options.forEach(function (opt) {
        const btn = document.createElement("button");
        btn.textContent = opt;
        btn.onclick = function () {
          wsSend({ type: "answer", question_id: q.id, answer: opt });
        };
        opts.appendChild(btn);
      });
      el.appendChild(opts);
    }

    dom.messages.appendChild(el);
    scrollToBottom();
  }

  /* ----- Markdown / code rendering (lightweight) ------------------------ */

  function renderMarkdown(text) {
    if (!text) return "";
    let html = escapeHtml(text);

    // Code blocks (```lang ... ```)
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
      return '<pre><code class="language-' + lang + '">' + code + "</code></pre>";
    });

    // Inline code
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

    // Italic
    html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

    // Headings (### ... )
    html = html.replace(/^### (.+)$/gm, "<h4>$1</h4>");
    html = html.replace(/^## (.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^# (.+)$/gm, "<h2>$1</h2>");

    // Unordered lists
    html = html.replace(/^- (.+)$/gm, "<li>$1</li>");

    // Line breaks
    html = html.replace(/\n/g, "<br>");

    return html;
  }

  function renderCodeContent(text, mtype) {
    if (!text) return "";
    const escaped = escapeHtml(text);
    if (mtype === "diff") {
      const lines = escaped.split("\n").map(function (line) {
        if (line.startsWith("+")) return '<span class="diff-line--added">' + line + "</span>";
        if (line.startsWith("-")) return '<span class="diff-line--removed">' + line + "</span>";
        return line;
      });
      return "<pre><code>" + lines.join("\n") + "</code></pre>";
    }
    return "<pre><code>" + escaped + "</code></pre>";
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  /* ----- Send message --------------------------------------------------- */

  function sendMessage(text) {
    text = (text || "").trim();
    if (!text) return;

    wsSend({ type: "chat", content: text });
    dom.textarea.value = "";
    autoResize();
  }

  /* ----- Sidebar updates ------------------------------------------------ */

  function updateStatusBadge(status) {
    if (!dom.statusBadge) return;
    dom.statusBadge.textContent = (status || "idle").replace(/_/g, " ");
    dom.statusBadge.className = "header__status header__status--" + (status || "idle");
  }

  function updateStepProgress(currentStep) {
    if (!dom.stepList) return;
    const items = dom.stepList.querySelectorAll(".step-progress__item");
    items.forEach(function (item) {
      const step = parseInt(item.dataset.step, 10);
      item.classList.remove("step-progress__item--active", "step-progress__item--done");
      if (step === currentStep) {
        item.classList.add("step-progress__item--active");
      } else if (step < currentStep) {
        item.classList.add("step-progress__item--done");
      }
    });
  }

  function updateIterationBadge(iteration, maxIterations) {
    if (!dom.iterationBadge) return;
    dom.iterationBadge.innerHTML =
      'Fix iteration: <span class="iteration-badge__count">' +
      (iteration || 0) +
      "</span> / " +
      (maxIterations || 20);
  }

  function updateObjectTree(codebase) {
    if (!dom.objectTree || !codebase) return;
    dom.objectTree.innerHTML = "";

    var byType = codebase.by_type || {};

    // Update summary text
    if (dom.codebaseSummary) {
      var totalObjects = 0;
      Object.keys(byType).forEach(function (t) {
        totalObjects += (byType[t] || []).length;
      });
      var appName = codebase.app_name || "Unknown";
      var version = codebase.appian_version || "";
      dom.codebaseSummary.innerHTML =
        '<strong>' + escapeHtml(appName) + '</strong><br>' +
        totalObjects + ' objects' +
        (version ? ' &middot; v' + escapeHtml(version) : '');
    }
    Object.keys(byType)
      .sort()
      .forEach(function (typeName) {
        const group = document.createElement("div");
        group.className = "object-tree__group";

        const label = document.createElement("div");
        label.className = "object-tree__group-label";
        label.textContent = typeName + " (" + byType[typeName].length + ")";
        group.appendChild(label);

        var nameMap = codebase.uuid_to_name || {};
        byType[typeName].slice(0, 50).forEach(function (uid) {
          var displayName = (typeof uid === "string")
            ? (nameMap[uid] || uid)
            : (uid.name || uid.uuid || "unnamed");
          const item = document.createElement("div");
          item.className = "object-tree__item";
          item.innerHTML =
            '<span class="object-tree__icon">■</span>' +
            '<span class="truncate">' +
            escapeHtml(displayName) +
            "</span>";
          group.appendChild(item);
        });

        dom.objectTree.appendChild(group);
      });
  }

  function updateTestResults(results) {
    if (!dom.testResults || !results) return;
    dom.testResults.innerHTML = "";

    if (results.status === "no_results") {
      dom.testResults.textContent = "No test results yet.";
      return;
    }

    const passed = results.passed;
    const failures = results.failures || [];

    const summary = document.createElement("div");
    summary.className = "test-results__summary";
    summary.innerHTML = passed
      ? '<span class="test-results__badge test-results__badge--pass">ALL PASSED</span>'
      : '<span class="test-results__badge test-results__badge--fail">' +
        failures.length +
        " FAILED</span>";
    dom.testResults.appendChild(summary);

    if (failures.length) {
      const list = document.createElement("ul");
      list.className = "test-results__list";
      failures.forEach(function (f) {
        const li = document.createElement("li");
        li.className = "test-results__item test-results__item--fail";
        li.textContent = (f.name || "unknown") + ": " + (f.message || "");
        list.appendChild(li);
      });
      dom.testResults.appendChild(list);
    }
  }

  /* ----- File upload ---------------------------------------------------- */

  function setupUpload(dropArea, fileInput, endpoint, label) {
    if (!dropArea || !fileInput) return;

    dropArea.addEventListener("click", function () {
      fileInput.click();
    });

    dropArea.addEventListener("dragover", function (e) {
      e.preventDefault();
      dropArea.classList.add("upload-area--dragover");
    });

    dropArea.addEventListener("dragleave", function () {
      dropArea.classList.remove("upload-area--dragover");
    });

    dropArea.addEventListener("drop", function (e) {
      e.preventDefault();
      dropArea.classList.remove("upload-area--dragover");
      if (e.dataTransfer.files.length) {
        uploadFile(e.dataTransfer.files[0], endpoint, label);
      }
    });

    fileInput.addEventListener("change", function () {
      if (fileInput.files.length) {
        uploadFile(fileInput.files[0], endpoint, label);
        fileInput.value = "";
      }
    });
  }

  async function uploadFile(file, endpoint, label) {
    const form = new FormData();
    form.append("file", file);

    // Show uploading status in chat
    renderMessage({
      role: "system",
      content: "Uploading " + label + ": " + file.name + " ...",
      message_type: "status",
    });

    try {
      const resp = await fetch(endpoint + "?session_id=" + sessionId, {
        method: "POST",
        body: form,
      });

      if (!resp.ok) {
        const err = await resp.json().catch(function () {
          return { detail: resp.statusText };
        });
        renderMessage({
          role: "system",
          content: "Upload failed: " + (err.detail || "Unknown error"),
          message_type: "error",
        });
        return;
      }

      const data = await resp.json();
      renderMessage({
        role: "system",
        content: label + " uploaded successfully.",
        message_type: "status",
      });

      // Refresh codebase tree if this was a ZIP upload
      if (endpoint.includes("/upload")) {
        fetchCodebase();
      }
    } catch (e) {
      renderMessage({
        role: "system",
        content: "Upload error: " + e.message,
        message_type: "error",
      });
    }
  }

  async function fetchCodebase() {
    try {
      const resp = await fetch("/api/codebase?session_id=" + sessionId);
      if (resp.ok) {
        const data = await resp.json();
        updateObjectTree(data);
      }
    } catch (_) {
      /* ignore */
    }
  }

  /* ----- Download ------------------------------------------------------- */

  function downloadZip() {
    window.open("/api/download?session_id=" + sessionId, "_blank");
  }

  /* ----- Auto-resize textarea ------------------------------------------ */

  function autoResize() {
    if (!dom.textarea) return;
    dom.textarea.style.height = "auto";
    dom.textarea.style.height = Math.min(dom.textarea.scrollHeight, 150) + "px";
  }

  function scrollToBottom() {
    if (!dom.messages) return;
    dom.messages.scrollTop = dom.messages.scrollHeight;
  }

  /* ----- Periodic polling (fallback for status + test results) ---------- */

  async function pollStatus() {
    try {
      const resp = await fetch("/api/status?session_id=" + sessionId);
      if (resp.ok) {
        const data = await resp.json();
        updateStatusBadge(data.status);
        updateStepProgress(data.current_step);
        updateIterationBadge(data.iteration, data.max_iterations);

        if (data.has_output_zip && dom.downloadBtn) {
          dom.downloadBtn.disabled = false;
        }
      }
    } catch (_) {
      /* ignore */
    }

    try {
      const resp = await fetch("/api/test-results?session_id=" + sessionId);
      if (resp.ok) {
        const data = await resp.json();
        updateTestResults(data);
      }
    } catch (_) {
      /* ignore */
    }
  }

  /* ----- Settings modal ------------------------------------------------- */

  function openSettings() {
    if (!dom.settingsOverlay) return;
    loadSettings();
    dom.settingsOverlay.classList.remove("hidden");
    hideConnectionStatus();
  }

  function closeSettings() {
    if (!dom.settingsOverlay) return;
    dom.settingsOverlay.classList.add("hidden");
    hideConnectionStatus();
  }

  async function loadSettings() {
    try {
      var resp = await fetch("/api/settings");
      if (!resp.ok) return;
      var data = await resp.json();
      if (dom.settingBaseUrl) dom.settingBaseUrl.value = data.base_url || "";
      if (dom.settingApiKey) dom.settingApiKey.value = "";
      if (dom.settingApiKey) dom.settingApiKey.placeholder = data.api_key || "Enter API key";
      if (dom.settingPrimaryModel) dom.settingPrimaryModel.value = data.primary_model || "";
      if (dom.settingFastModel) dom.settingFastModel.value = data.fast_model || "";
    } catch (_) {
      /* ignore */
    }
  }

  async function saveSettings() {
    var payload = {};
    if (dom.settingBaseUrl && dom.settingBaseUrl.value.trim()) {
      payload.base_url = dom.settingBaseUrl.value.trim();
    }
    if (dom.settingApiKey && dom.settingApiKey.value.trim()) {
      payload.api_key = dom.settingApiKey.value.trim();
    }
    if (dom.settingPrimaryModel && dom.settingPrimaryModel.value.trim()) {
      payload.primary_model = dom.settingPrimaryModel.value.trim();
    }
    if (dom.settingFastModel && dom.settingFastModel.value.trim()) {
      payload.fast_model = dom.settingFastModel.value.trim();
    }

    if (dom.settingsSave) dom.settingsSave.disabled = true;

    try {
      var resp = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (resp.ok) {
        showConnectionStatus("Settings saved successfully.", "success");
        setTimeout(closeSettings, 800);
      } else {
        var err = await resp.json().catch(function () { return { detail: resp.statusText }; });
        showConnectionStatus("Save failed: " + (err.detail || "Unknown error"), "error");
      }
    } catch (e) {
      showConnectionStatus("Save error: " + e.message, "error");
    } finally {
      if (dom.settingsSave) dom.settingsSave.disabled = false;
    }
  }

  async function testConnection() {
    showConnectionStatus("Saving settings & testing connection...", "loading");
    if (dom.settingsTest) dom.settingsTest.disabled = true;

    try {
      // Save current form values first so the test uses them
      var payload = {};
      if (dom.settingBaseUrl && dom.settingBaseUrl.value.trim()) {
        payload.base_url = dom.settingBaseUrl.value.trim();
      }
      if (dom.settingApiKey && dom.settingApiKey.value.trim()) {
        payload.api_key = dom.settingApiKey.value.trim();
      }
      if (dom.settingPrimaryModel && dom.settingPrimaryModel.value.trim()) {
        payload.primary_model = dom.settingPrimaryModel.value.trim();
      }
      if (dom.settingFastModel && dom.settingFastModel.value.trim()) {
        payload.fast_model = dom.settingFastModel.value.trim();
      }

      var saveResp = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!saveResp.ok) {
        showConnectionStatus("Failed to save settings before testing.", "error");
        return;
      }

      showConnectionStatus("Testing connection...", "loading");
      var resp = await fetch("/api/settings/test");
      var data = await resp.json();
      if (resp.ok) {
        showConnectionStatus(data.message || "Connection successful.", "success");
      } else {
        showConnectionStatus(data.message || "Connection failed.", "error");
      }
    } catch (e) {
      showConnectionStatus("Test error: " + e.message, "error");
    } finally {
      if (dom.settingsTest) dom.settingsTest.disabled = false;
    }
  }

  function showConnectionStatus(message, type) {
    if (!dom.connectionStatus) return;
    dom.connectionStatus.textContent = message;
    dom.connectionStatus.className = "connection-status connection-status--" + type;
    dom.connectionStatus.classList.remove("hidden");
  }

  function hideConnectionStatus() {
    if (!dom.connectionStatus) return;
    dom.connectionStatus.classList.add("hidden");
  }

  /* ----- Keyboard handling ---------------------------------------------- */

  function onTextareaKeydown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(dom.textarea.value);
    }
  }

  /* ----- Init ----------------------------------------------------------- */

  function init() {
    initTheme();
    connectWS();

    // Event listeners
    if (dom.themeToggle) dom.themeToggle.addEventListener("click", toggleTheme);
    if (dom.sendBtn) dom.sendBtn.addEventListener("click", function () { sendMessage(dom.textarea.value); });
    if (dom.textarea) {
      dom.textarea.addEventListener("keydown", onTextareaKeydown);
      dom.textarea.addEventListener("input", autoResize);
    }
    if (dom.downloadBtn) dom.downloadBtn.addEventListener("click", downloadZip);

    // Settings modal
    if (dom.settingsBtn) dom.settingsBtn.addEventListener("click", openSettings);
    if (dom.settingsClose) dom.settingsClose.addEventListener("click", closeSettings);
    if (dom.settingsCancel) dom.settingsCancel.addEventListener("click", closeSettings);
    if (dom.settingsSave) dom.settingsSave.addEventListener("click", saveSettings);
    if (dom.settingsTest) dom.settingsTest.addEventListener("click", testConnection);
    if (dom.settingsOverlay) {
      dom.settingsOverlay.addEventListener("click", function (e) {
        if (e.target === dom.settingsOverlay) closeSettings();
      });
    }

    // File uploads
    setupUpload(dom.zipUpload, dom.zipInput, "/api/upload", "Appian ZIP");
    setupUpload(dom.storyUpload, dom.storyInput, "/api/story", "User Story PDF");

    // Fallback polling every 5s
    setInterval(pollStatus, 5000);
  }

  // Run on DOM ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

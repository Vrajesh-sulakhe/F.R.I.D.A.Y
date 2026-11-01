/**
 * FRIDAY Web Client - Voice & Brain Core
 */

class FridayClient {
  constructor() {
    this.sessionHistory = [];
    this.activeProvider = "ollama_local";
    this.activeProviderName = "Ollama (Local)";
    this.activeModel = "qwen3.5:9b";
    this.activeVoice = "Jarvis (Local)";
    this.socket = null;
    this.isStreaming = false;

    // DOM Elements
    this.brainBadge = document.getElementById("active-brain-text");
    this.voiceBadge = document.getElementById("active-voice-text");
    this.liveStatus = document.getElementById("live-status-text");
    this.latencyMetric = document.getElementById("metric-latency");
    this.tokensMetric = document.getElementById("metric-tokens");
    this.costMetric = document.getElementById("metric-cost");
    this.messagesStream = document.getElementById("messages-stream");
    this.chatForm = document.getElementById("chat-form");
    this.userInput = document.getElementById("user-input");
    this.settingsModal = document.getElementById("settings-modal");
    this.providersList = document.getElementById("providers-list");

    this.init();
  }

  async init() {
    this.bindEvents();
    this.connectWebSocket();
    await this.fetchFreshSession();
  }

  bindEvents() {
    // Chat submit
    this.chatForm.addEventListener("submit", (e) => {
      e.preventDefault();
      this.handleUserSubmit();
    });

    // Quick command chips
    document.querySelectorAll(".cmd-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const cmd = btn.getAttribute("data-cmd");
        if (cmd) {
          this.userInput.value = cmd;
          this.handleUserSubmit();
        }
      });
    });

    // Settings modal open/close
    document.getElementById("open-settings-btn").addEventListener("click", () => {
      this.openSettingsModal();
    });
    document.getElementById("close-settings-btn").addEventListener("click", () => {
      this.closeSettingsModal();
    });
    document.getElementById("refresh-providers-btn").addEventListener("click", () => {
      this.loadProvidersSettings();
    });
    this.settingsModal.addEventListener("click", (e) => {
      if (e.target === this.settingsModal) this.closeSettingsModal();
    });
  }

  connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

    try {
      this.socket = new WebSocket(wsUrl);

      this.socket.onopen = () => {
        this.updateStatus("Neural link established. Standing by, sir.");
      };

      this.socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        this.handleSocketMessage(data);
      };

      this.socket.onclose = () => {
        this.updateStatus("Link interrupted. Reconnecting in 3s...");
        setTimeout(() => this.connectWebSocket(), 3000);
      };

      this.socket.onerror = (err) => {
        console.warn("WebSocket error, falling back to HTTP endpoints:", err);
      };
    } catch (e) {
      console.warn("WebSocket initialization failed:", e);
    }
  }

  async fetchFreshSession() {
    try {
      const res = await fetch("/api/session/fresh");
      if (res.ok) {
        const data = await res.json();
        this.activeProvider = data.active_provider;
        this.activeModel = data.active_model;
        this.updateHUD();
        this.updateStatus("System initialized. Standing by, sir.");
      }
    } catch (e) {
      console.error("Failed to load session:", e);
    }
  }

  updateHUD() {
    this.brainBadge.textContent = `${this.activeProviderName || this.activeProvider} / ${this.activeModel}`;
    this.voiceBadge.textContent = this.activeVoice;
  }

  updateStatus(text) {
    this.liveStatus.textContent = text;
  }

  updateMetrics(latencyMs, tokens, cost) {
    if (latencyMs !== undefined) this.latencyMetric.textContent = `Latency: ${latencyMs.toFixed(0)} ms`;
    if (tokens !== undefined) this.tokensMetric.textContent = `Tokens: ${tokens}`;
    if (cost !== undefined) this.costMetric.textContent = `Cost: $${cost.toFixed(4)}`;
  }

  appendMessage(role, content, meta = null) {
    const wrapper = document.createElement("div");
    wrapper.className = `message-wrapper ${role}`;

    const avatar = document.createElement("div");
    avatar.className = role === "assistant" ? "avatar-jarvis" : "avatar-user";
    avatar.textContent = role === "assistant" ? "F" : "U";

    const body = document.createElement("div");
    body.className = "message-body";

    const header = document.createElement("div");
    header.className = "message-header";
    header.innerHTML = `<span>${role === "assistant" ? "FRIDAY" : "Sir"}</span> <span class="time-stamp">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>`;

    const contentDiv = document.createElement("div");
    contentDiv.className = "message-content";
    contentDiv.textContent = content;

    body.appendChild(header);
    body.appendChild(contentDiv);
    wrapper.appendChild(avatar);
    wrapper.appendChild(body);

    this.messagesStream.appendChild(wrapper);
    this.messagesStream.scrollTop = this.messagesStream.scrollHeight;

    return contentDiv;
  }

  async handleUserSubmit() {
    const text = this.userInput.value.trim();
    if (!text || this.isStreaming) return;

    this.userInput.value = "";
    this.appendMessage("user", text);
    this.sessionHistory.push({ role: "user", content: text });

    this.updateStatus("Reaching for cognitive core...");

    // If WebSocket is active, send via WebSocket
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.isStreaming = true;
      this.socket.send(JSON.stringify({
        action: "chat",
        message: text,
        session_history: this.sessionHistory.slice(-10),
      }));
    } else {
      // Fallback to HTTP POST /api/chat
      await this.sendChatHttp(text);
    }
  }

  async sendChatHttp(text) {
    try {
      this.isStreaming = true;
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_history: this.sessionHistory.slice(-10),
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Request failed");
      }

      const data = await res.json();
      this.appendMessage("assistant", data.reply);
      this.sessionHistory.push({ role: "assistant", content: data.reply });

      this.activeProviderName = data.provider;
      this.activeModel = data.model;
      this.updateHUD();
      this.updateMetrics(data.latency_ms, data.prompt_tokens + data.completion_tokens, data.estimated_cost_usd);
      this.updateStatus("Standing by, sir.");
    } catch (e) {
      this.appendMessage("assistant", `I apologize, sir. Error: ${e.message}`);
      this.updateStatus("Cognitive error encountered.");
    } finally {
      this.isStreaming = false;
    }
  }

  handleSocketMessage(data) {
    switch (data.type) {
      case "init":
        this.activeProvider = data.active_provider;
        this.activeProviderName = data.active_provider_name;
        this.activeModel = data.active_model;
        this.updateHUD();
        break;

      case "brain_switch":
        this.activeProvider = data.active_provider;
        this.activeProviderName = data.active_provider_name;
        this.activeModel = data.active_model;
        this.updateHUD();
        this.appendMessage("assistant", data.reply);
        this.sessionHistory.push({ role: "assistant", content: data.reply });
        this.updateStatus(`Brain switched to ${this.activeProviderName} (${this.activeModel})`);
        this.isStreaming = false;
        break;

      case "stream_start":
        this.currentStreamContentDiv = this.appendMessage("assistant", "");
        this.currentAccumulatedText = "";
        this.updateStatus(`Streaming from ${data.provider} (${data.model})...`);
        break;

      case "stream_chunk":
        if (data.content && this.currentStreamContentDiv) {
          this.currentAccumulatedText += data.content;
          this.currentStreamContentDiv.textContent = this.currentAccumulatedText;
          this.messagesStream.scrollTop = this.messagesStream.scrollHeight;
        }
        if (data.usage) {
          this.updateMetrics(data.usage.latency_ms, data.usage.total_tokens, data.usage.estimated_cost_usd);
        }
        break;

      case "stream_end":
        if (this.currentAccumulatedText) {
          this.sessionHistory.push({ role: "assistant", content: this.currentAccumulatedText });
        }
        this.isStreaming = false;
        this.updateStatus("Standing by, sir.");
        break;

      default:
        break;
    }
  }

  // Settings Modal logic
  async openSettingsModal() {
    this.settingsModal.classList.remove("hidden");
    await this.loadProvidersSettings();
  }

  closeSettingsModal() {
    this.settingsModal.classList.add("hidden");
  }

  async loadProvidersSettings() {
    try {
      const res = await fetch("/api/providers");
      if (!res.ok) return;
      const data = await res.json();
      this.renderProvidersList(data.providers, data.active_provider, data.active_model);
    } catch (e) {
      console.error("Failed to load providers:", e);
    }
  }

  renderProvidersList(providers, activeProvId, currentModel) {
    this.providersList.innerHTML = "";

    providers.forEach((p) => {
      const card = document.createElement("div");
      card.className = `provider-card ${p.id === activeProvId ? "active-card" : ""}`;

      const head = document.createElement("div");
      head.className = "provider-head";
      head.innerHTML = `
        <div>
          <span class="provider-title">${p.name}</span>
          <span style="font-size:0.75rem; color:${p.is_configured ? '#10b981' : '#f43f5e'}; margin-left:0.5rem;">
            ${p.is_configured ? '● Configured' : '○ Missing Key'}
          </span>
        </div>
      `;

      const actions = document.createElement("div");
      actions.className = "provider-actions";

      // Select model dropdown
      const select = document.createElement("select");
      select.className = "action-btn";
      p.models.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        if (p.id === activeProvId && m === currentModel) opt.selected = true;
        select.appendChild(opt);
      });

      // Activate button
      const activateBtn = document.createElement("button");
      activateBtn.className = `action-btn ${p.id === activeProvId ? "primary" : ""}`;
      activateBtn.textContent = p.id === activeProvId ? "Active Brain" : "Activate";
      activateBtn.addEventListener("click", async () => {
        await this.switchProvider(p.id, select.value);
      });

      // Test Connection button
      const testBtn = document.createElement("button");
      testBtn.className = "action-btn";
      testBtn.textContent = "Test Link";
      testBtn.addEventListener("click", async () => {
        testBtn.textContent = "Testing...";
        const tRes = await fetch("/api/providers/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider_id: p.id, model: select.value }),
        });
        const tData = await tRes.json();
        alert(`[${p.name}] ${tData.success ? 'Success' : 'Failed'}: ${tData.message}`);
        testBtn.textContent = "Test Link";
      });

      actions.appendChild(select);
      actions.appendChild(activateBtn);
      actions.appendChild(testBtn);
      head.appendChild(actions);
      card.appendChild(head);

      // Key input row (only for commercial providers)
      if (p.id !== "ollama_local") {
        const keyRow = document.createElement("div");
        keyRow.className = "key-input-row";
        keyRow.innerHTML = `
          <input type="password" placeholder="${p.masked_key ? 'Key configured: ' + p.masked_key : 'Paste API Key here...'}" id="key-input-${p.id}">
          <button class="action-btn" id="save-key-btn-${p.id}">Save Key</button>
        `;
        card.appendChild(keyRow);

        setTimeout(() => {
          const saveBtn = document.getElementById(`save-key-btn-${p.id}`);
          const input = document.getElementById(`key-input-${p.id}`);
          if (saveBtn && input) {
            saveBtn.addEventListener("click", async () => {
              const newKey = input.value.trim();
              if (!newKey) return;
              const res = await fetch("/api/providers/key", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ provider_id: p.id, api_key: newKey }),
              });
              const rData = await res.json();
              alert(rData.message);
              input.value = "";
              this.loadProvidersSettings();
            });
          }
        }, 0);
      }

      this.providersList.appendChild(card);
    });
  }

  async switchProvider(providerId, model) {
    try {
      const res = await fetch("/api/providers/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: providerId, model: model }),
      });
      const data = await res.json();
      if (res.ok) {
        this.activeProvider = data.active_provider;
        this.activeProviderName = data.active_provider_name;
        this.activeModel = data.active_model;
        this.updateHUD();
        this.loadProvidersSettings();
        this.updateStatus(`Brain switched to ${this.activeProviderName} (${this.activeModel})`);
      } else {
        alert(data.detail || "Switch failed");
      }
    } catch (e) {
      alert(`Switch error: ${e.message}`);
    }
  }
}

// Instantiate on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  window.friday = new FridayClient();
});

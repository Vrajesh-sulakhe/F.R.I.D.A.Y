/**
 * FRIDAY Web Client - 100% Dynamically Rendered AI Assistant Interface
 */

class FridayClient {
  constructor() {
    this.sessionHistory = [];
    this.systemState = null;
    this.socket = null;
    this.isStreaming = false;
    this.currentStreamContentDiv = null;
    this.currentAccumulatedText = "";

    // DOM Elements
    this.systemTitle = document.getElementById("system-title");
    this.systemSubtitle = document.getElementById("system-subtitle");
    this.brainBadge = document.getElementById("active-brain-text");
    this.voiceBadge = document.getElementById("active-voice-text");
    this.liveStatus = document.getElementById("live-status-text");
    this.latencyMetric = document.getElementById("metric-latency");
    this.tokensMetric = document.getElementById("metric-tokens");
    this.costMetric = document.getElementById("metric-cost");
    this.messagesStream = document.getElementById("messages-stream");
    this.quickCommandsContainer = document.getElementById("quick-commands-container");
    this.toolsChipsList = document.getElementById("tools-chips-list");
    this.chatForm = document.getElementById("chat-form");
    this.userInput = document.getElementById("user-input");
    this.settingsModal = document.getElementById("settings-modal");
    this.providersList = document.getElementById("providers-list");
    this.voicePickerSelect = document.getElementById("voice-picker-select");
    this.applyVoiceBtn = document.getElementById("apply-voice-btn");
    this.readingPanel = document.getElementById("reading-panel");
    this.panelTitle = document.getElementById("panel-title");
    this.panelContent = document.getElementById("panel-content");
    this.readAloudBtn = document.getElementById("read-aloud-btn");
    this.closeReadingPanelBtn = document.getElementById("close-reading-panel-btn");

    this.init();
  }

  async init() {
    this.bindEvents();
    // 1. Fetch fresh session to reset state on load/refresh
    await this.fetchFreshSession();
    // 2. Connect WebSocket for real-time telemetry
    this.connectWebSocket();
  }

  bindEvents() {
    // Chat submit
    this.chatForm.addEventListener("submit", (e) => {
      e.preventDefault();
      this.handleUserSubmit();
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

    // Apply voice button
    this.applyVoiceBtn.addEventListener("click", () => {
      const selectedVoice = this.voicePickerSelect.value;
      if (selectedVoice) {
        this.switchVoice(selectedVoice);
      }
    });

    // Reading panel controls
    this.closeReadingPanelBtn.addEventListener("click", () => {
      this.closeReadingPanel();
    });
    this.readAloudBtn.addEventListener("click", () => {
      this.userInput.value = "read it out loud";
      this.handleUserSubmit();
    });
  }

  connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

    try {
      this.socket = new WebSocket(wsUrl);

      this.socket.onopen = () => {
        this.updateStatus("Neural telemetry link active. Standing by, sir.");
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
        this.applyDynamicState(data.state);
        // Clear messages and inject initial greeting dynamically
        this.messagesStream.innerHTML = "";
        this.appendMessage("assistant", data.greeting);
        this.sessionHistory = [{ role: "assistant", content: data.greeting }];
        this.updateStatus("System initialized. Standing by, sir.");
      }
    } catch (e) {
      console.error("Failed to fetch fresh session:", e);
    }
  }

  applyDynamicState(state) {
    if (!state) return;
    this.systemState = state;

    // 1. Identity & Titles
    if (state.identity) {
      this.systemTitle.textContent = state.identity.title || "F.R.I.D.A.Y.";
      this.systemSubtitle.textContent = state.identity.subtitle || "Butler Intelligence";
    }

    // 2. Brain Badge
    if (state.brain) {
      this.brainBadge.textContent = `${state.brain.provider_name} / ${state.brain.model}`;
      const brainDot = document.getElementById("brain-dot");
      if (brainDot) {
        brainDot.className = state.brain.is_local ? "badge-dot pulse-cyan" : "badge-dot pulse-amber";
      }
    }

    // 3. Voice Badge
    if (state.voice) {
      this.voiceBadge.textContent = state.voice.voice_name;
      // Populate voice picker select if empty
      this.renderVoicePicker(state.voice.available_voices, state.voice.voice_name);
    }

    // 4. Dynamic Quick Commands Chips
    if (state.quick_commands) {
      this.renderQuickCommands(state.quick_commands);
    }

    // 5. Dynamic Tools Bar
    if (state.tools) {
      this.renderToolsBar(state.tools);
    }
  }

  renderVoicePicker(availableVoices, activeVoice) {
    if (!this.voicePickerSelect || !availableVoices) return;
    this.voicePickerSelect.innerHTML = "";
    availableVoices.forEach((voice) => {
      const opt = document.createElement("option");
      opt.value = voice;
      opt.textContent = voice;
      if (voice === activeVoice) opt.selected = true;
      this.voicePickerSelect.appendChild(opt);
    });
  }

  renderQuickCommands(commands) {
    this.quickCommandsContainer.innerHTML = "";
    const label = document.createElement("span");
    label.className = "quick-label";
    label.textContent = "Dynamic Commands:";
    this.quickCommandsContainer.appendChild(label);

    commands.forEach((item) => {
      const btn = document.createElement("button");
      btn.className = "cmd-chip";
      btn.textContent = item.label;
      btn.setAttribute("data-cmd", item.command);
      btn.addEventListener("click", () => {
        this.userInput.value = item.command;
        this.handleUserSubmit();
      });
      this.quickCommandsContainer.appendChild(btn);
    });
  }

  renderToolsBar(tools) {
    this.toolsChipsList.innerHTML = "";
    tools.forEach((tool) => {
      const chip = document.createElement("div");
      chip.className = "tool-chip";
      chip.title = `Tool: ${tool.name} (${tool.status})`;

      chip.innerHTML = `
        <span class="tool-status-dot"></span>
        <span class="tool-name">${tool.name}</span>
        <span class="tool-status-text">[${tool.status}]</span>
      `;

      chip.addEventListener("click", () => {
        if (tool.id === "calendar") {
          this.userInput.value = "FRIDAY, what meetings do I have tomorrow?";
          this.handleUserSubmit();
        } else if (tool.id === "rea") {
          this.userInput.value = "FRIDAY, can you reverse engineer igloo.inc for me?";
          this.handleUserSubmit();
        } else if (tool.id === "second_brain") {
          this.userInput.value = "FRIDAY, can you pull up my brand voice?";
          this.handleUserSubmit();
        } else {
          this.updateStatus(`Tool selected: ${tool.name}. Reaching for tools...`);
        }
      });

      this.toolsChipsList.appendChild(chip);
    });
  }

  updateStatus(text) {
    this.liveStatus.textContent = text;
  }

  updateMetrics(latencyMs, tokens, cost) {
    if (latencyMs !== undefined) this.latencyMetric.textContent = `Latency: ${latencyMs.toFixed(0)} ms`;
    if (tokens !== undefined) this.tokensMetric.textContent = `Tokens: ${tokens}`;
    if (cost !== undefined) this.costMetric.textContent = `Cost: $${cost.toFixed(4)}`;
  }

  appendMessage(role, content) {
    const wrapper = document.createElement("div");
    wrapper.className = `message-wrapper ${role}`;

    const avatar = document.createElement("div");
    avatar.className = role === "assistant" ? "avatar-jarvis" : "avatar-user";
    avatar.textContent = role === "assistant" ? "F" : "U";

    const body = document.createElement("div");
    body.className = "message-body";

    const header = document.createElement("div");
    header.className = "message-header";
    const speaker = role === "assistant" ? (this.systemState?.identity?.name || "FRIDAY") : "Sir";
    header.innerHTML = `<span>${speaker}</span> <span class="time-stamp">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>`;

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

  openReadingPanel(title, content) {
    this.panelTitle.textContent = title;
    this.panelContent.textContent = content;
    this.readingPanel.classList.remove("hidden");
  }

  closeReadingPanel() {
    this.readingPanel.classList.add("hidden");
  }

  async handleUserSubmit() {
    const text = this.userInput.value.trim();
    if (!text || this.isStreaming) return;

    this.userInput.value = "";
    this.appendMessage("user", text);
    this.sessionHistory.push({ role: "user", content: text });

    // Dynamic status text for tools or general queries
    if (text.toLowerCase().includes("calendar") || text.toLowerCase().includes("meetings")) {
      this.updateStatus("Let me see if I have the tools for that, sir.");
      setTimeout(() => this.updateStatus("Reaching for tools..."), 600);
    } else if (text.toLowerCase().includes("reverse engineer") || text.toLowerCase().includes("teardown")) {
      this.updateStatus("Opening site in clean browser while REA takes it apart...");
    } else {
      this.updateStatus("Cognitive core engaged...");
    }

    // Transmit via WebSocket if connected
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.isStreaming = true;
      this.socket.send(JSON.stringify({
        action: "chat",
        message: text,
        session_history: this.sessionHistory.slice(-10),
      }));
    } else {
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

      // Refresh dynamic state
      const stateRes = await fetch("/api/system/state");
      if (stateRes.ok) {
        const freshState = await stateRes.json();
        this.applyDynamicState(freshState);
      }

      this.updateMetrics(data.latency_ms, data.prompt_tokens + data.completion_tokens, data.estimated_cost_usd);
      this.updateStatus("Standing by, sir.");
    } catch (e) {
      this.appendMessage("assistant", `I apologize, sir. Error: ${e.message}`);
      this.updateStatus("Cognitive exception encountered.");
    } finally {
      this.isStreaming = false;
    }
  }

  handleSocketMessage(data) {
    switch (data.type) {
      case "init":
        this.applyDynamicState(data.state);
        break;

      case "state_update":
        this.applyDynamicState(data.state);
        if (data.reply) {
          this.appendMessage("assistant", data.reply);
          this.sessionHistory.push({ role: "assistant", content: data.reply });
        }
        this.isStreaming = false;
        this.updateStatus("Standing by, sir.");
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
          // If long output (e.g. teardown report), open reading panel
          if (this.currentAccumulatedText.length > 500) {
            this.openReadingPanel("Full Report Dossier", this.currentAccumulatedText);
          }
        }
        this.isStreaming = false;
        this.updateStatus("Standing by, sir.");
        break;

      default:
        break;
    }
  }

  async switchVoice(voiceName) {
    try {
      const res = await fetch("/api/voice/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voice_name: voiceName }),
      });
      const data = await res.json();
      if (res.ok) {
        this.applyDynamicState(data.state);
        this.updateStatus(`Voice profile updated to ${voiceName}`);
      }
    } catch (e) {
      console.error("Failed to switch voice:", e);
    }
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
        this.applyDynamicState(data.state);
        this.loadProvidersSettings();
        this.updateStatus(`Brain switched to ${data.active_provider_name} (${data.active_model})`);
      } else {
        alert(data.detail || "Switch failed");
      }
    } catch (e) {
      alert(`Switch error: ${e.message}`);
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

      const totalCount = p.total_models_count || p.models?.length || 0;
      const freeCount = p.free_models_count || 0;

      const head = document.createElement("div");
      head.className = "provider-head";
      head.innerHTML = `
        <div style="display:flex; align-items:center; flex-wrap:wrap; gap:0.4rem;">
          <span class="provider-title">${p.name}</span>
          <span style="font-size:0.75rem; color:${p.is_configured ? '#10b981' : '#f43f5e'};">
            ${p.is_configured ? '● Configured' : '○ Missing Key'}
          </span>
          ${totalCount > 0 ? `<span class="model-count-badge">${totalCount} Models</span>` : ''}
          ${freeCount > 0 ? `<span class="free-badge">🎁 ${freeCount} Free</span>` : ''}
        </div>
      `;
      card.appendChild(head);

      // Model selector with search and free-filtering
      const modelContainer = document.createElement("div");
      modelContainer.className = "model-selector-container";

      // Filter row
      const filterRow = document.createElement("div");
      filterRow.className = "model-filter-row";

      const searchInput = document.createElement("input");
      searchInput.type = "text";
      searchInput.className = "model-filter-input";
      searchInput.placeholder = `🔍 Search ${totalCount} models (e.g. 'free', 'claude', 'deepseek', 'llama')...`;

      const allBtn = document.createElement("button");
      allBtn.className = "model-filter-btn active";
      allBtn.textContent = `All (${totalCount})`;

      const freeBtn = document.createElement("button");
      freeBtn.className = "model-filter-btn";
      freeBtn.textContent = `🎁 Free Only (${freeCount})`;

      filterRow.appendChild(searchInput);
      if (freeCount > 0) {
        filterRow.appendChild(allBtn);
        filterRow.appendChild(freeBtn);
      }
      modelContainer.appendChild(filterRow);

      // Select dropdown
      const select = document.createElement("select");
      select.className = "model-select-dropdown";

      const modelsDetails = p.models_details && p.models_details.length > 0 
        ? p.models_details 
        : p.models.map(m => ({ id: m, name: m, is_free: m.includes(":free") }));

      let filterFreeOnly = false;
      let filterQuery = "";

      const populateOptions = () => {
        select.innerHTML = "";
        const query = filterQuery.toLowerCase().trim();

        const filtered = modelsDetails.filter((m) => {
          if (filterFreeOnly && !m.is_free) return false;
          if (query) {
            return m.id.toLowerCase().includes(query) || (m.name && m.name.toLowerCase().includes(query));
          }
          return true;
        });

        const freeGroup = filtered.filter(m => m.is_free);
        const regularGroup = filtered.filter(m => !m.is_free);

        if (freeGroup.length > 0) {
          const optGroup = document.createElement("optgroup");
          optGroup.label = `🎁 Free Models (Zero API Cost) — ${freeGroup.length} available`;
          freeGroup.forEach((m) => {
            const opt = document.createElement("option");
            opt.value = m.id;
            opt.textContent = `[FREE] ${m.name || m.id}`;
            if (p.id === activeProvId && m.id === currentModel) opt.selected = true;
            optGroup.appendChild(opt);
          });
          select.appendChild(optGroup);
        }

        if (regularGroup.length > 0) {
          const optGroup = document.createElement("optgroup");
          optGroup.label = `⚡ Commercial & Flagship Models — ${regularGroup.length} available`;
          regularGroup.forEach((m) => {
            const opt = document.createElement("option");
            opt.value = m.id;
            opt.textContent = `${m.name || m.id}`;
            if (p.id === activeProvId && m.id === currentModel) opt.selected = true;
            optGroup.appendChild(opt);
          });
          select.appendChild(optGroup);
        }

        if (filtered.length === 0) {
          const opt = document.createElement("option");
          opt.textContent = "No models matching filter";
          opt.disabled = true;
          select.appendChild(opt);
        }
      };

      populateOptions();

      // Search listeners
      searchInput.addEventListener("input", (e) => {
        filterQuery = e.target.value;
        populateOptions();
      });

      allBtn.addEventListener("click", () => {
        filterFreeOnly = false;
        allBtn.classList.add("active");
        freeBtn.classList.remove("active");
        populateOptions();
      });

      freeBtn.addEventListener("click", () => {
        filterFreeOnly = true;
        freeBtn.classList.add("active");
        allBtn.classList.remove("active");
        populateOptions();
      });

      modelContainer.appendChild(select);

      // Model action buttons
      const actionsRow = document.createElement("div");
      actionsRow.className = "model-actions-row";

      const activateBtn = document.createElement("button");
      activateBtn.className = `action-btn ${p.id === activeProvId ? "primary" : ""}`;
      activateBtn.textContent = p.id === activeProvId ? "Active Brain" : "Activate Selected Model";
      activateBtn.addEventListener("click", async () => {
        if (!select.value || select.value === "No models matching filter") return;
        await this.switchProvider(p.id, select.value);
      });

      const testBtn = document.createElement("button");
      testBtn.className = "action-btn";
      testBtn.textContent = "Test Link with Selected";
      testBtn.addEventListener("click", async () => {
        if (!select.value || select.value === "No models matching filter") return;
        testBtn.textContent = "Testing...";
        const tRes = await fetch("/api/providers/test", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider_id: p.id, model: select.value }),
        });
        const tData = await tRes.json();
        alert(`[${p.name}] ${tData.success ? 'Success' : 'Failed'}: ${tData.message}`);
        testBtn.textContent = "Test Link with Selected";
      });

      actionsRow.appendChild(activateBtn);
      actionsRow.appendChild(testBtn);
      modelContainer.appendChild(actionsRow);
      card.appendChild(modelContainer);

      // Key input row (for commercial providers)
      if (p.id !== "ollama_local") {
        const keyRow = document.createElement("div");
        keyRow.className = "key-input-row";
        keyRow.innerHTML = `
          <input type="password" placeholder="${p.masked_key ? 'Key configured: ' + p.masked_key : 'Paste API Key here...'}" id="key-input-${p.id}">
          <button class="action-btn" id="save-key-btn-${p.id}">Save Key & Discover Models</button>
        `;
        card.appendChild(keyRow);

        setTimeout(() => {
          const saveBtn = document.getElementById(`save-key-btn-${p.id}`);
          const input = document.getElementById(`key-input-${p.id}`);
          if (saveBtn && input) {
            saveBtn.addEventListener("click", async () => {
              const newKey = input.value.trim();
              if (!newKey) return;
              saveBtn.textContent = "Discovering Models...";
              saveBtn.disabled = true;
              try {
                const res = await fetch("/api/providers/key", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ provider_id: p.id, api_key: newKey }),
                });
                const rData = await res.json();
                input.value = "";
                await this.loadProvidersSettings();
                alert(`${rData.message}\nModels catalog dynamically updated!`);
              } catch (err) {
                alert(`Error saving key: ${err.message}`);
              } finally {
                saveBtn.textContent = "Save Key & Discover Models";
                saveBtn.disabled = false;
              }
            });
          }
        }, 0);
      }

      this.providersList.appendChild(card);
    });
  }
}

// Instantiate on DOM ready
document.addEventListener("DOMContentLoaded", () => {
  window.friday = new FridayClient();
});

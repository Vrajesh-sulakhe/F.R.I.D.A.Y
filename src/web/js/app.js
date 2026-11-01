/**
 * FRIDAY Web Client - Voice Controller, Three.js 3D Second Brain & Mac App Tools
 */

class FridayClient {
  constructor() {
    this.sessionHistory = [];
    this.systemState = null;
    this.socket = null;
    this.isStreaming = false;

    // Speech Recognition & Synthesis
    this.recognition = null;
    this.isListening = false;
    this.synth = window.speechSynthesis;
    this.waveAnimId = null;

    // DOM Elements
    this.graphContainer = document.getElementById("graph-canvas-container");
    this.messagesStream = document.getElementById("messages-stream");
    this.chatForm = document.getElementById("chat-form");
    this.userInput = document.getElementById("user-input");
    this.micToggleBtn = document.getElementById("mic-toggle-btn");
    this.dockMicBtn = document.getElementById("dock-mic-btn");
    this.micDot = document.getElementById("mic-dot");
    this.micStatusText = document.getElementById("mic-status-text");
    this.reactorSubstatus = document.getElementById("reactor-substatus");
    this.hudModelText = document.getElementById("hud-model-text");
    this.waveCanvas = document.getElementById("voice-wave-canvas");
    this.waveCtx = this.waveCanvas ? this.waveCanvas.getContext("2d") : null;

    // Inspector & Left Sidebar
    this.inspectorDetails = document.getElementById("inspector-details");
    this.inspectorDesc = document.getElementById("inspector-desc");
    this.inspectorBadge = document.getElementById("inspector-badge");
    this.inspectorTitle = document.getElementById("inspector-title");
    this.inspectorText = document.getElementById("inspector-text");
    this.inspectorMeta = document.getElementById("inspector-meta");
    this.hubsList = document.getElementById("hubs-list");
    this.filterItemsList = document.getElementById("filter-items-list");
    this.brainSearchInput = document.getElementById("brain-search-input");

    // Reading Panel
    this.readingPanel = document.getElementById("reading-panel");
    this.panelTitle = document.getElementById("panel-title");
    this.panelContent = document.getElementById("panel-content");
    this.readAloudBtn = document.getElementById("read-aloud-btn");
    this.closeReadingPanelBtn = document.getElementById("close-reading-panel-btn");

    // Settings Modal
    this.settingsModal = document.getElementById("settings-modal");
    this.providersList = document.getElementById("providers-list");
    this.voicePickerSelect = document.getElementById("voice-picker-select");
    this.applyVoiceBtn = document.getElementById("apply-voice-btn");

    this.init();
  }

  async init() {
    this.init3DGalaxyGraph();
    this.initSpeechRecognition();
    this.bindEvents();
    this.startReactorWaveAnimation();
    await this.fetchFreshSession();
    this.connectWebSocket();
  }

  init3DGalaxyGraph() {
    if (window.GalaxyGraph) {
      this.galaxy = new GalaxyGraph("graph-canvas-container", (nodeData) => {
        this.displayNodeInInspector(nodeData);
      });
      this.renderHubsList();
      this.renderFilterList();
    }
  }

  renderHubsList() {
    if (!this.hubsList || !this.galaxy) return;
    this.hubsList.innerHTML = "";

    this.galaxy.hubs.forEach((hub) => {
      const row = document.createElement("div");
      row.className = "hub-item-row";

      const hex = "#" + hub.color.toString(16).padStart(6, "0");
      row.innerHTML = `
        <div class="hub-name-group">
          <span class="hub-color-dot" style="background:${hex}; box-shadow:0 0 6px ${hex};"></span>
          <span>${hub.name}</span>
        </div>
        <span class="hub-count">${hub.count}</span>
      `;

      row.addEventListener("click", () => {
        this.galaxy.focusHub(hub.name);
        this.userInput.value = `FRIDAY, pull up ${hub.name}`;
      });

      this.hubsList.appendChild(row);
    });
  }

  renderFilterList() {
    if (!this.filterItemsList || !this.galaxy) return;
    this.filterItemsList.innerHTML = "";

    Object.entries(this.galaxy.categories).forEach(([name, data]) => {
      const row = document.createElement("div");
      row.className = "filter-item-row";

      const hex = "#" + data.color.toString(16).padStart(6, "0");
      row.innerHTML = `
        <div class="filter-cat-group">
          <span class="hub-color-dot" style="background:${hex}; box-shadow:0 0 5px ${hex};"></span>
          <span>${name}</span>
        </div>
        <span class="filter-count">${data.count}</span>
      `;

      row.addEventListener("click", () => {
        this.galaxy.highlightByQuery(name);
      });

      this.filterItemsList.appendChild(row);
    });
  }

  displayNodeInInspector(node) {
    if (!this.inspectorDetails) return;
    this.inspectorDesc.style.display = "none";
    this.inspectorDetails.classList.remove("hidden");

    this.inspectorBadge.textContent = node.type || "Node";
    this.inspectorTitle.textContent = node.name || "Untitled";
    this.inspectorText.textContent = node.summary || "No notes attached.";
    this.inspectorMeta.textContent = `${node.hub ? 'Hub: ' + node.hub : 'Cluster Core'} · ${node.category || 'General'}`;
  }

  initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn("Speech Recognition API not supported in this browser.");
      if (this.micStatusText) this.micStatusText.textContent = "NO MIC API";
      return;
    }

    try {
      this.recognition = new SpeechRecognition();
      this.recognition.continuous = true;
      this.recognition.interimResults = true;
      this.recognition.lang = "en-US";

      this.recognition.onstart = () => {
        this.isListening = true;
        this.updateListeningUI(true);
      };

      this.recognition.onresult = (event) => {
        let interimTranscript = "";
        let finalTranscript = "";

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }

        const currentText = (finalTranscript || interimTranscript).trim();
        if (currentText) {
          this.userInput.value = currentText;
          this.reactorSubstatus.textContent = `heard: "${currentText.slice(-20)}"`;
        }

        if (finalTranscript) {
          this.handleUserSubmit();
        }
      };

      this.recognition.onerror = (e) => {
        console.warn("Speech recognition error:", e.error);
        if (e.error !== "no-speech") {
          this.stopListening();
        }
      };

      this.recognition.onend = () => {
        if (this.isListening) {
          // Restart if still marked as listening
          try { this.recognition.start(); } catch (err) {}
        } else {
          this.updateListeningUI(false);
        }
      };
    } catch (e) {
      console.warn("Failed to initialize speech recognition:", e);
    }
  }

  toggleListening() {
    if (!this.recognition) {
      alert("Microphone recognition requires Chrome, Brave, or Safari with microphone permissions granted.");
      return;
    }
    if (this.isListening) {
      this.stopListening();
    } else {
      this.startListening();
    }
  }

  startListening() {
    if (!this.recognition) return;
    this.isListening = true;
    try {
      this.recognition.start();
    } catch (e) {
      // already started
    }
    this.updateListeningUI(true);
  }

  stopListening() {
    this.isListening = false;
    if (this.recognition) {
      try { this.recognition.stop(); } catch (e) {}
    }
    this.updateListeningUI(false);
  }

  updateListeningUI(listening) {
    if (listening) {
      if (this.micStatusText) this.micStatusText.textContent = "LISTENING";
      if (this.micDot) this.micDot.className = "badge-dot pulse-emerald";
      if (this.dockMicBtn) this.dockMicBtn.classList.add("active");
      if (this.reactorSubstatus) this.reactorSubstatus.textContent = "listening...";
    } else {
      if (this.micStatusText) this.micStatusText.textContent = "CLICK TO TALK";
      if (this.micDot) this.micDot.className = "badge-dot pulse-cyan";
      if (this.dockMicBtn) this.dockMicBtn.classList.remove("active");
      if (this.reactorSubstatus) this.reactorSubstatus.textContent = "standing by, sir.";
    }
  }

  speakResponse(text) {
    if (!this.synth) return;
    try {
      this.synth.cancel(); // Stop prior speech
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1.05;
      utterance.pitch = 0.95;

      // Prefer British / Jarvis style voice if available
      const voices = this.synth.getVoices();
      const ukVoice = voices.find(v => v.lang.includes("en-GB") || v.name.includes("Daniel") || v.name.includes("Oliver"));
      if (ukVoice) utterance.voice = ukVoice;

      utterance.onstart = () => {
        this.reactorSubstatus.textContent = "speaking, sir...";
      };
      utterance.onend = () => {
        this.reactorSubstatus.textContent = this.isListening ? "listening..." : "standing by, sir.";
      };

      this.synth.speak(utterance);
    } catch (e) {
      console.warn("Speech synthesis error:", e);
    }
  }

  startReactorWaveAnimation() {
    if (!this.waveCanvas || !this.waveCtx) return;

    let phase = 0;
    const draw = () => {
      this.waveAnimId = requestAnimationFrame(draw);
      this.waveCtx.clearRect(0, 0, this.waveCanvas.width, this.waveCanvas.height);

      const centerX = this.waveCanvas.width / 2;
      const centerY = this.waveCanvas.height / 2;
      const baseRadius = 54;
      const waveCount = 3;

      phase += 0.04;
      const activeFactor = (this.isListening || this.synth.speaking) ? 1.8 : 0.4;

      for (let w = 0; w < waveCount; w++) {
        this.waveCtx.beginPath();
        this.waveCtx.strokeStyle = this.isListening ? `rgba(16, 185, 129, ${0.4 - w * 0.1})` : `rgba(56, 189, 248, ${0.35 - w * 0.1})`;
        this.waveCtx.lineWidth = 1.5;

        for (let angle = 0; angle <= Math.PI * 2; angle += 0.1) {
          const distortion = Math.sin(angle * 6 + phase + w) * (3.5 * activeFactor);
          const r = baseRadius + distortion + w * 4;
          const x = centerX + Math.cos(angle) * r;
          const y = centerY + Math.sin(angle) * r;
          if (angle === 0) {
            this.waveCtx.moveTo(x, y);
          } else {
            this.waveCtx.lineTo(x, y);
          }
        }
        this.waveCtx.closePath();
        this.waveCtx.stroke();
      }
    };
    draw();
  }

  bindEvents() {
    // Form submit
    this.chatForm.addEventListener("submit", (e) => {
      e.preventDefault();
      this.handleUserSubmit();
    });

    // Mic button toggles
    if (this.micToggleBtn) {
      this.micToggleBtn.addEventListener("click", () => this.toggleListening());
    }
    if (this.dockMicBtn) {
      this.dockMicBtn.addEventListener("click", () => this.toggleListening());
    }

    // Brain search input
    if (this.brainSearchInput) {
      this.brainSearchInput.addEventListener("input", (e) => {
        if (this.galaxy) this.galaxy.highlightByQuery(e.target.value);
      });
    }

    // Tool icons in dock
    document.getElementById("tool-canva-btn")?.addEventListener("click", async () => {
      this.userInput.value = "open Canva";
      this.handleUserSubmit();
    });

    document.getElementById("tool-calendar-btn")?.addEventListener("click", () => {
      this.userInput.value = "FRIDAY, what meetings do I have tomorrow?";
      this.handleUserSubmit();
    });

    document.getElementById("tool-gmail-btn")?.addEventListener("click", () => {
      this.userInput.value = "open Mail";
      this.handleUserSubmit();
    });

    document.getElementById("tool-rea-btn")?.addEventListener("click", () => {
      this.userInput.value = "FRIDAY, can you reverse engineer igloo.inc for me?";
      this.handleUserSubmit();
    });

    // Settings modal open/close
    document.getElementById("open-settings-btn")?.addEventListener("click", () => {
      this.openSettingsModal();
    });
    document.getElementById("close-settings-btn")?.addEventListener("click", () => {
      this.closeSettingsModal();
    });
    document.getElementById("refresh-providers-btn")?.addEventListener("click", () => {
      this.loadProvidersSettings();
    });
    this.settingsModal.addEventListener("click", (e) => {
      if (e.target === this.settingsModal) this.closeSettingsModal();
    });

    // Apply voice button
    this.applyVoiceBtn?.addEventListener("click", () => {
      const selectedVoice = this.voicePickerSelect.value;
      if (selectedVoice) this.switchVoice(selectedVoice);
    });

    // Reading panel controls
    this.closeReadingPanelBtn?.addEventListener("click", () => this.closeReadingPanel());
    this.readAloudBtn?.addEventListener("click", () => {
      const textToRead = this.panelContent.textContent;
      if (textToRead) this.speakResponse(textToRead);
    });

    // HUD Toggles (Eyes, Watch, Holo, Focus)
    document.querySelectorAll(".toggle-switch-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const toggleName = btn.getAttribute("data-toggle");
        const isActive = btn.classList.toggle("active");
        btn.textContent = isActive ? "on" : "off";
        if (toggleName === "holo" && this.galaxy) {
          this.galaxy.nodeGroup.visible = isActive;
        }
      });
    });
  }

  connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

    try {
      this.socket = new WebSocket(wsUrl);

      this.socket.onopen = () => {
        this.reactorSubstatus.textContent = "online. standing by.";
      };

      this.socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        this.handleSocketMessage(data);
      };

      this.socket.onclose = () => {
        this.reactorSubstatus.textContent = "reconnecting...";
        setTimeout(() => this.connectWebSocket(), 3000);
      };
    } catch (e) {
      console.warn("WebSocket init failed:", e);
    }
  }

  async fetchFreshSession() {
    try {
      const res = await fetch("/api/session/fresh");
      if (res.ok) {
        const data = await res.json();
        this.applyDynamicState(data.state);
        this.appendMessage("assistant", data.greeting);
        this.sessionHistory = [{ role: "assistant", content: data.greeting }];
        // Speak initial greeting
        this.speakResponse(data.greeting);
      }
    } catch (e) {
      console.error("Fresh session failed:", e);
    }
  }

  applyDynamicState(state) {
    if (!state) return;
    this.systemState = state;

    if (state.brain && this.hudModelText) {
      this.hudModelText.textContent = `${state.brain.model.toUpperCase()}`;
    }

    if (state.voice && this.voicePickerSelect) {
      this.renderVoicePicker(state.voice.available_voices, state.voice.voice_name);
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

  appendMessage(role, content) {
    const msg = document.createElement("div");
    msg.className = `floating-msg ${role}`;
    msg.textContent = `${role === 'assistant' ? 'FRIDAY: ' : 'You: '} ${content}`;

    this.messagesStream.appendChild(msg);
    this.messagesStream.scrollTop = this.messagesStream.scrollHeight;

    // Prune old floating messages
    while (this.messagesStream.children.length > 5) {
      this.messagesStream.removeChild(this.messagesStream.firstChild);
    }
    return msg;
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
    this.reactorSubstatus.textContent = "computing, sir...";

    // Highlight 3D graph if query matches keywords
    if (this.galaxy) {
      this.galaxy.highlightByQuery(text);
    }

    // Direct Mac App Launcher check
    const lower = text.toLowerCase();
    if (lower.startsWith("open ") || lower.startsWith("launch ")) {
      const appName = text.replace(/^(open|launch)\s+/i, "").trim();
      const appRes = await fetch("/api/tools/open_app", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app_name: appName }),
      });
      if (appRes.ok) {
        const appData = await appRes.json();
        const reply = appData.success
          ? `Opening ${appData.app_name} for you, sir. Right away.`
          : `I attempted to launch ${appData.app_name}, sir, but macOS encountered an issue: ${appData.message}`;
        this.appendMessage("assistant", reply);
        this.sessionHistory.push({ role: "assistant", content: reply });
        this.speakResponse(reply);
        this.reactorSubstatus.textContent = `Tool run: ${appData.app_name}`;
        return;
      }
    }

    // Send via WebSocket or HTTP
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

      // Speak aloud in voice
      this.speakResponse(data.reply);

      // Open reading panel if long report
      if (data.reply.length > 350) {
        this.openReadingPanel("Detailed Analysis", data.reply);
      }

      // Refresh state
      const stateRes = await fetch("/api/system/state");
      if (stateRes.ok) {
        const freshState = await stateRes.json();
        this.applyDynamicState(freshState);
      }

      this.reactorSubstatus.textContent = "standing by, sir.";
    } catch (e) {
      this.appendMessage("assistant", `I apologize, sir: ${e.message}`);
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
          this.speakResponse(data.reply);
        }
        this.isStreaming = false;
        this.reactorSubstatus.textContent = "standing by, sir.";
        break;

      case "stream_start":
        this.currentAccumulatedText = "";
        this.reactorSubstatus.textContent = `streaming from ${data.model}...`;
        break;

      case "stream_chunk":
        if (data.content) {
          this.currentAccumulatedText += data.content;
        }
        break;

      case "stream_end":
        if (this.currentAccumulatedText) {
          this.appendMessage("assistant", this.currentAccumulatedText);
          this.sessionHistory.push({ role: "assistant", content: this.currentAccumulatedText });
          this.speakResponse(this.currentAccumulatedText);
          if (this.currentAccumulatedText.length > 350) {
            this.openReadingPanel("Detailed Analysis", this.currentAccumulatedText);
          }
        }
        this.isStreaming = false;
        this.reactorSubstatus.textContent = "standing by, sir.";
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
      if (res.ok) {
        const data = await res.json();
        this.applyDynamicState(data.state);
        this.speakResponse(`Voice switched to ${voiceName}, sir.`);
      }
    } catch (e) {
      console.error("Voice switch error:", e);
    }
  }

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

      const modelContainer = document.createElement("div");
      modelContainer.className = "model-selector-container";

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
        this.speakResponse(`Brain switched to ${data.active_provider_name}, running model ${data.active_model}, sir.`);
      } else {
        alert(data.detail || "Switch failed");
      }
    } catch (e) {
      alert(`Switch error: ${e.message}`);
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  window.friday = new FridayClient();
});

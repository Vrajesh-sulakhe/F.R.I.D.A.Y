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
    this.providersSegmentedNav = document.getElementById("providers-segmented-nav");
    this.voiceCardsGrid = document.getElementById("voice-cards-grid");
    this.voicePickerSelect = document.getElementById("voice-picker-select");
    this.applyVoiceBtn = document.getElementById("apply-voice-btn");
    this.selectedProviderId = null;
    this.cachedProvidersData = null;
    this.activeVoiceProfile = null;

    this.init();
  }

  async init() {
    // 1. Bind events immediately so all UI buttons, settings, and docks are interactive
    try {
      this.bindEvents();
    } catch (e) {
      console.error("Failed to bind UI events:", e);
    }

    // 2. Initialize 3D Galaxy Graph
    try {
      this.init3DGalaxyGraph();
    } catch (e) {
      console.error("Failed to init 3D Galaxy Graph:", e);
    }

    // 3. Initialize Speech Recognition
    try {
      this.initSpeechRecognition();
    } catch (e) {
      console.warn("Speech recognition init warning:", e);
    }

    // 4. Start Arc Reactor Wave Animation
    try {
      this.startReactorWaveAnimation();
    } catch (e) {
      console.warn("Reactor wave animation warning:", e);
    }

    // 5. Fetch fresh session greeting & dynamic state
    try {
      await this.fetchFreshSession();
    } catch (e) {
      console.error("Fresh session fetch error:", e);
    }

    // 6. Connect WebSocket
    try {
      this.connectWebSocket();
    } catch (e) {
      console.warn("WebSocket connect warning:", e);
    }
  }

  init3DGalaxyGraph() {
    if (window.GalaxyGraph) {
      this.galaxy = new GalaxyGraph("graph-canvas-container", (nodeData) => {
        this.displayNodeInInspector(nodeData);
      });
    }
  }

  renderHubsList(hubs = []) {
    this.renderRealHubsList(hubs || (this.galaxy ? this.galaxy.hubs : []));
  }

  renderFilterList(categories = {}) {
    this.renderRealFilterList(categories || (this.galaxy ? this.galaxy.categories : {}));
  }


  renderRealHubsList(hubs) {
    if (!this.hubsList) return;
    this.hubsList.innerHTML = "";

    hubs.forEach((hub) => {
      const row = document.createElement("div");
      row.className = "hub-item-row";

      const hex = typeof hub.color === "number" ? "#" + hub.color.toString(16).padStart(6, "0") : (hub.color || "#38bdf8");
      row.innerHTML = `
        <div class="hub-name-group">
          <span class="hub-color-dot" style="background:${hex}; box-shadow:0 0 6px ${hex};"></span>
          <span>${hub.name}</span>
        </div>
        <span class="hub-count">${hub.count}</span>
      `;

      row.addEventListener("click", () => {
        if (this.galaxy) this.galaxy.focusHub(hub.name);
        this.userInput.value = `FRIDAY, pull up ${hub.name}`;
      });

      this.hubsList.appendChild(row);
    });
  }

  renderRealFilterList(categories) {
    if (!this.filterItemsList) return;
    this.filterItemsList.innerHTML = "";

    const catColors = {
      "Applications": "#38bdf8",
      "Projects": "#10b981",
      "Code": "#60a5fa",
      "Notes": "#facc15",
      "Docs": "#f97316",
      "Data": "#a855f7",
      "Tools": "#ef4444",
      "Files": "#94a3b8",
      "Folders": "#eab308",
    };

    Object.entries(categories).forEach(([name, count]) => {
      if (count <= 0) return;
      const row = document.createElement("div");
      row.className = "filter-item-row";
      const hex = catColors[name] || "#94a3b8";

      row.innerHTML = `
        <div class="filter-cat-group">
          <span class="hub-color-dot" style="background:${hex}; box-shadow:0 0 5px ${hex};"></span>
          <span>${name}</span>
        </div>
        <span class="filter-count">${count}</span>
      `;

      row.addEventListener("click", () => {
        if (this.galaxy) this.galaxy.highlightByQuery(name);
      });

      this.filterItemsList.appendChild(row);
    });
  }

  displayNodeInInspector(node) {
    if (!this.inspectorDetails) return;
    this.inspectorDesc.style.display = "none";
    this.inspectorDetails.classList.remove("hidden");

    const categoryIcons = {
      "Applications": "💻",
      "Utilities": "🛠️",
      "Projects": "📁",
      "Code": "🐍",
      "Documents": "📄",
      "Presentations": "📊",
      "Notes": "📝",
      "Data": "💾",
      "Config": "⚙️",
      "Media": "🖼️",
      "Archives": "📦",
      "Downloads": "⬇️",
      "Desktop": "🖥️",
      "Brain": "🧠",
      "Files": "📎",
    };

    const icon = categoryIcons[node.category] || (node.is_app ? "💻" : (node.is_dir ? "📁" : "📄"));
    this.inspectorBadge.textContent = `${icon} ${node.category || node.type || "Local Item"}`;
    this.inspectorTitle.textContent = node.name || "Untitled";
    this.inspectorText.textContent = node.summary || "No notes attached.";

    // Rich Metadata Display
    const sizePart = node.size_human ? ` • ${node.size_human}` : "";
    const mtimePart = node.mtime ? ` • ${node.mtime}` : "";
    const hubPart = node.hub ? `[${node.hub}] ` : "";
    this.inspectorMeta.textContent = `${hubPart}${node.path || 'Mac Local Item'}${sizePart}${mtimePart}`;

    // Remove existing action button container if present
    const oldContainer = document.getElementById("inspector-actions-container");
    if (oldContainer) oldContainer.remove();

    const actionsContainer = document.createElement("div");
    actionsContainer.id = "inspector-actions-container";
    actionsContainer.className = "inspector-actions-grid";
    actionsContainer.style.display = "flex";
    actionsContainer.style.flexDirection = "column";
    actionsContainer.style.gap = "0.5rem";
    actionsContainer.style.marginTop = "0.85rem";

    if (node.is_app) {
      // Application Actions
      const launchBtn = document.createElement("button");
      launchBtn.className = "action-btn primary";
      launchBtn.style.width = "100%";
      launchBtn.textContent = `🚀 Launch ${node.name} on Mac`;
      launchBtn.addEventListener("click", async () => {
        launchBtn.textContent = "Launching...";
        const res = await fetch("/api/tools/open_app", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ app_name: node.name }),
        });
        const d = await res.json();
        launchBtn.textContent = d.success ? "✓ Launched on Mac" : "Launch Failed";
        this.speakResponse(`Opening ${node.name} for you, sir. Right away.`);
        setTimeout(() => { launchBtn.textContent = `🚀 Launch ${node.name} on Mac`; }, 2500);
      });
      actionsContainer.appendChild(launchBtn);

      const revealBtn = document.createElement("button");
      revealBtn.className = "action-btn";
      revealBtn.style.width = "100%";
      revealBtn.textContent = `📂 Reveal ${node.name} in Finder`;
      revealBtn.addEventListener("click", async () => {
        revealBtn.textContent = "Revealing...";
        const res = await fetch("/api/tools/reveal_in_finder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: node.path }),
        });
        const d = await res.json();
        revealBtn.textContent = d.success ? "✓ Revealed in Finder" : "Failed";
        this.speakResponse(`Revealed ${node.name} in your macOS Finder, sir.`);
        setTimeout(() => { revealBtn.textContent = `📂 Reveal ${node.name} in Finder`; }, 2500);
      });
      actionsContainer.appendChild(revealBtn);

    } else {
      // Local File / Directory Actions
      const openBtn = document.createElement("button");
      openBtn.className = "action-btn primary";
      openBtn.style.width = "100%";
      openBtn.textContent = `📄 Open ${node.is_dir ? 'Folder' : 'File'} on Mac`;
      openBtn.addEventListener("click", async () => {
        openBtn.textContent = "Opening...";
        const res = await fetch("/api/tools/open_file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: node.path }),
        });
        const d = await res.json();
        openBtn.textContent = d.success ? "✓ Opened on Mac" : "Failed";
        this.speakResponse(`Opening ${node.name} for you, sir.`);
        setTimeout(() => { openBtn.textContent = `📄 Open ${node.is_dir ? 'Folder' : 'File'} on Mac`; }, 2500);
      });
      actionsContainer.appendChild(openBtn);

      const revealBtn = document.createElement("button");
      revealBtn.className = "action-btn";
      revealBtn.style.width = "100%";
      revealBtn.textContent = `📂 Reveal in Finder`;
      revealBtn.addEventListener("click", async () => {
        revealBtn.textContent = "Revealing...";
        const res = await fetch("/api/tools/reveal_in_finder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: node.path }),
        });
        const d = await res.json();
        revealBtn.textContent = d.success ? "✓ Revealed" : "Failed";
        this.speakResponse(`Revealed in Finder, sir.`);
        setTimeout(() => { revealBtn.textContent = `📂 Reveal in Finder`; }, 2500);
      });
      actionsContainer.appendChild(revealBtn);

      // If text/code readable, offer Preview panel
      if (node.is_text_readable) {
        const previewBtn = document.createElement("button");
        previewBtn.className = "action-btn";
        previewBtn.style.width = "100%";
        previewBtn.textContent = `📖 Inspect File Content`;
        previewBtn.addEventListener("click", async () => {
          previewBtn.textContent = "Loading file...";
          try {
            const res = await fetch(`/api/tools/read_file?path=${encodeURIComponent(node.path)}`);
            if (res.ok) {
              const fileData = await res.json();
              this.openReadingPanel(`${node.name} (${node.size_human})`, fileData.content);
              previewBtn.textContent = `📖 Inspect File Content`;
              this.speakResponse(`Displaying contents of ${node.name} on your reading panel, sir.`);
            } else {
              previewBtn.textContent = "Could not read";
            }
          } catch (e) {
            previewBtn.textContent = "Error reading";
          }
        });
        actionsContainer.appendChild(previewBtn);
      }

      // Voice read aloud
      const readBtn = document.createElement("button");
      readBtn.className = "action-btn";
      readBtn.style.width = "100%";
      readBtn.textContent = `🔊 Read Summary Aloud`;
      readBtn.addEventListener("click", () => {
        this.speakResponse(node.summary || `${node.name}, located at ${node.path}`);
      });
      actionsContainer.appendChild(readBtn);
    }

    this.inspectorDetails.appendChild(actionsContainer);
  }


  // ---------------------------------------------------------------------------
  // Voice input: always-on microphone with voice-activity detection (VAD).
  // Audio is captured in the browser, cut into utterances on silence, and sent
  // to the local Whisper endpoint (/api/stt). Works in Brave/Chrome/Safari.
  // ---------------------------------------------------------------------------
  initSpeechRecognition() {
    this.audioCtx = null;
    this.micStream = null;
    this.micProcessor = null;
    this.isSpeakingAudio = false;
    this.speakToken = 0;
    this.currentAudio = null;
    this.vad = {
      threshold: 0.018,      // RMS level that counts as speech
      silenceMs: 900,        // silence that ends an utterance
      minSpeechMs: 350,      // ignore clicks/pops shorter than this
      maxUtteranceMs: 20000, // hard cap per utterance
      preRollChunks: 4,      // keep a little audio before speech starts
    };
    this.resetVadState();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      if (this.micStatusText) this.micStatusText.textContent = "NO MIC API";
    }
  }

  resetVadState() {
    this.speechChunks = [];
    this.preRoll = [];
    this.inSpeech = false;
    this.speechStart = 0;
    this.lastVoiceAt = 0;
  }

  toggleListening() {
    if (this.isListening) this.stopListening();
    else this.startListening();
  }

  async startListening() {
    if (this.isListening) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      this.setMicError("Microphone API unavailable. Open http://localhost:4719 in Brave, Chrome or Safari.");
      return;
    }
    try {
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (e) {
      console.warn("Microphone permission error:", e);
      const denied = e && (e.name === "NotAllowedError" || e.name === "SecurityError");
      this.setMicError(denied
        ? "Microphone blocked. Click the lock icon in the address bar, allow Microphone, then press the mic again."
        : `Microphone unavailable: ${e.message || e.name}`);
      return;
    }

    const Ctx = window.AudioContext || window.webkitAudioContext;
    this.audioCtx = new Ctx();
    if (this.audioCtx.state === "suspended") await this.audioCtx.resume();

    const source = this.audioCtx.createMediaStreamSource(this.micStream);
    this.micProcessor = this.audioCtx.createScriptProcessor(4096, 1, 1);
    this.micProcessor.onaudioprocess = (ev) => this.onAudioChunk(ev.inputBuffer.getChannelData(0));
    // Route through a muted gain node so the processor runs without echoing the mic.
    const mute = this.audioCtx.createGain();
    mute.gain.value = 0;
    source.connect(this.micProcessor);
    this.micProcessor.connect(mute);
    mute.connect(this.audioCtx.destination);

    this.resetVadState();
    this.isListening = true;
    this.updateListeningUI(true);
  }

  stopListening() {
    this.isListening = false;
    try { this.micProcessor && this.micProcessor.disconnect(); } catch (e) {}
    try { this.micStream && this.micStream.getTracks().forEach(t => t.stop()); } catch (e) {}
    try { this.audioCtx && this.audioCtx.close(); } catch (e) {}
    this.micProcessor = null;
    this.micStream = null;
    this.audioCtx = null;
    this.resetVadState();
    this.updateListeningUI(false);
  }

  setMicError(message) {
    this.isListening = false;
    this.updateListeningUI(false);
    if (this.micStatusText) this.micStatusText.textContent = "MIC BLOCKED";
    if (this.reactorSubstatus) this.reactorSubstatus.textContent = message.slice(0, 60);
    this.appendMessage("assistant", message);
  }

  // True while FRIDAY is talking or thinking, so we never transcribe ourselves.
  isMicGated() {
    return this.isSpeakingAudio || this.isStreaming;
  }

  onAudioChunk(input) {
    if (!this.isListening) return;
    const chunk = new Float32Array(input); // copy; the buffer is reused by the browser
    const now = performance.now();

    if (this.isMicGated()) {
      this.resetVadState();
      return;
    }

    let sum = 0;
    for (let i = 0; i < chunk.length; i++) sum += chunk[i] * chunk[i];
    const rms = Math.sqrt(sum / chunk.length);
    const voiced = rms > this.vad.threshold;

    if (!this.inSpeech) {
      this.preRoll.push(chunk);
      if (this.preRoll.length > this.vad.preRollChunks) this.preRoll.shift();
      if (voiced) {
        this.inSpeech = true;
        this.speechStart = now;
        this.lastVoiceAt = now;
        this.speechChunks = [...this.preRoll];
        this.preRoll = [];
        if (this.reactorSubstatus) this.reactorSubstatus.textContent = "hearing you, sir...";
      }
      return;
    }

    this.speechChunks.push(chunk);
    if (voiced) this.lastVoiceAt = now;

    const silentFor = now - this.lastVoiceAt;
    const length = now - this.speechStart;
    if (silentFor > this.vad.silenceMs || length > this.vad.maxUtteranceMs) {
      const spoke = this.lastVoiceAt - this.speechStart;
      const chunks = this.speechChunks;
      const rate = this.audioCtx ? this.audioCtx.sampleRate : 48000;
      this.resetVadState();
      if (spoke >= this.vad.minSpeechMs) this.transcribeUtterance(chunks, rate);
    }
  }

  async transcribeUtterance(chunks, sampleRate) {
    if (this.reactorSubstatus) this.reactorSubstatus.textContent = "transcribing...";
    try {
      const wav = this.encodeWav16k(chunks, sampleRate);
      const res = await fetch("/api/stt", { method: "POST", body: wav });
      if (!res.ok) throw new Error(`STT ${res.status}`);
      const { text } = await res.json();
      const heard = (text || "").trim();
      if (heard) {
        this.userInput.value = heard;
        this.reactorSubstatus.textContent = `heard: "${heard.slice(0, 28)}"`;
        await this.handleUserSubmit();
      } else if (this.reactorSubstatus) {
        this.reactorSubstatus.textContent = "listening...";
      }
    } catch (e) {
      console.warn("Transcription error:", e);
      if (this.reactorSubstatus) this.reactorSubstatus.textContent = "didn't catch that, sir";
    }
  }

  // Float32 chunks at the device rate -> 16 kHz mono 16-bit PCM WAV.
  encodeWav16k(chunks, sampleRate) {
    let total = 0;
    chunks.forEach(c => { total += c.length; });
    const merged = new Float32Array(total);
    let offset = 0;
    chunks.forEach(c => { merged.set(c, offset); offset += c.length; });

    const targetRate = 16000;
    const ratio = sampleRate / targetRate;
    const outLen = Math.floor(merged.length / ratio);
    const pcm = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      // average over the source window (cheap low-pass) to limit aliasing
      const start = Math.floor(i * ratio);
      const end = Math.min(merged.length, Math.floor((i + 1) * ratio));
      let acc = 0;
      for (let j = start; j < end; j++) acc += merged[j];
      const s = Math.max(-1, Math.min(1, acc / Math.max(1, end - start)));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }

    const buffer = new ArrayBuffer(44 + pcm.length * 2);
    const view = new DataView(buffer);
    const writeStr = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
    writeStr(0, "RIFF");
    view.setUint32(4, 36 + pcm.length * 2, true);
    writeStr(8, "WAVE");
    writeStr(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, targetRate, true);
    view.setUint32(28, targetRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, "data");
    view.setUint32(40, pcm.length * 2, true);
    new Int16Array(buffer, 44).set(pcm);
    return new Blob([buffer], { type: "audio/wav" });
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

  // ---------------------------------------------------------------------------
  // Voice output: British butler voice rendered locally by the backend (/api/tts).
  // Falls back to the browser's en-GB voice (Daniel) if the backend is unreachable.
  // ---------------------------------------------------------------------------
  speakResponse(text) {
    if (!text) return;
    this.stopSpeaking();
    const token = ++this.speakToken;
    this.isSpeakingAudio = true; // gate the mic immediately, before audio arrives
    if (this.reactorSubstatus) this.reactorSubstatus.textContent = "speaking, sir...";

    fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    })
      .then(res => { if (!res.ok) throw new Error(`TTS ${res.status}`); return res.blob(); })
      .then(blob => {
        if (token !== this.speakToken) return; // superseded by newer speech
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        this.currentAudio = audio;
        const done = () => {
          URL.revokeObjectURL(url);
          if (token === this.speakToken) this.finishSpeaking();
        };
        audio.onended = done;
        audio.onerror = done;
        return audio.play().catch(() => done());
      })
      .catch(err => {
        console.warn("Server TTS failed, using browser voice:", err);
        if (token === this.speakToken) this.speakWithBrowserVoice(text, token);
      });
  }

  speakWithBrowserVoice(text, token) {
    if (!this.synth) return this.finishSpeaking();
    const utterance = new SpeechSynthesisUtterance(text);
    const voices = this.synth.getVoices();
    // Prioritize Irish female (Moira) matching Iron Man's F.R.I.D.A.Y.
    const voice = voices.find(v => v.name.includes("Moira")) ||
                  voices.find(v => v.lang === "en-IE") ||
                  voices.find(v => v.name.includes("Samantha")) ||
                  voices.find(v => v.lang.startsWith("en"));
    if (voice) utterance.voice = voice;
    utterance.rate = 1.05;
    utterance.pitch = 1.05;
    utterance.onend = utterance.onerror = () => {
      if (token === this.speakToken) this.finishSpeaking();
    };
    this.synth.speak(utterance);
  }

  stopSpeaking() {
    if (this.currentAudio) {
      try { this.currentAudio.pause(); } catch (e) {}
      this.currentAudio = null;
    }
    if (this.synth) { try { this.synth.cancel(); } catch (e) {} }
  }

  finishSpeaking() {
    this.currentAudio = null;
    // Small tail so the room echo of the last word isn't picked up by the mic.
    setTimeout(() => {
      this.isSpeakingAudio = false;
      if (this.reactorSubstatus) {
        this.reactorSubstatus.textContent = this.isListening ? "listening..." : "standing by, sir.";
      }
    }, 350);
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
      const activeFactor = (this.isListening || this.isSpeakingAudio) ? 1.8 : 0.4;

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
      const currentVal = this.userInput.value.trim();
      if (currentVal && !currentVal.toLowerCase().includes("reverse engineer") && !currentVal.toLowerCase().includes("teardown")) {
        this.userInput.value = `FRIDAY, can you reverse engineer ${currentVal} for me?`;
      } else if (!currentVal) {
        this.userInput.value = "FRIDAY, can you reverse engineer igloo.inc for me?";
      }
      this.handleUserSubmit();
    });

    // Settings modal open/close
    document.getElementById("open-settings-btn")?.addEventListener("click", () => {
      this.openSettingsModal();
    });
    document.getElementById("hud-model-badge")?.addEventListener("click", () => {
      this.openSettingsModal();
    });
    document.getElementById("close-settings-btn")?.addEventListener("click", () => {
      this.closeSettingsModal();
    });
    document.getElementById("refresh-providers-btn")?.addEventListener("click", () => {
      this.loadProvidersSettings();
    });
    this.settingsModal?.addEventListener("click", (e) => {
      if (e.target === this.settingsModal) this.closeSettingsModal();
    });

    // Modal tabs navigation
    document.querySelectorAll(".modal-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tabTarget = btn.getAttribute("data-tab");
        document.querySelectorAll(".modal-tab-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");

        document.querySelectorAll(".tab-pane").forEach((pane) => {
          pane.classList.remove("active");
          if (pane.id === tabTarget) {
            pane.classList.add("active");
          }
        });

        if (tabTarget === "tab-telemetry") {
          this.updateTelemetryTab();
        }
      });
    });

    // Top pill view buttons
    document.getElementById("fit-graph-btn")?.addEventListener("click", () => {
      if (this.galaxy) this.galaxy.fitView();
    });
    document.getElementById("reset-view-btn")?.addEventListener("click", () => {
      if (this.galaxy) this.galaxy.fitView();
    });
    document.getElementById("toggle-2d-btn")?.addEventListener("click", () => {
      if (this.galaxy) {
        this.galaxy.setViewMode(this.galaxy.viewMode === "face" ? "ring" : "face");
      }
    });
    document.getElementById("love-btn")?.addEventListener("click", () => {
      this.speakResponse("Always at your service, sir. All core heuristics running at peak efficiency.");
    });

    // Apply voice button
    this.applyVoiceBtn?.addEventListener("click", () => {
      const selectedVoice = this.voicePickerSelect.value;
      if (selectedVoice) this.switchVoice(selectedVoice);
    });

    // Reading panel controls
    this.closeReadingPanelBtn?.addEventListener("click", () => this.closeReadingPanel());
    this.readAloudBtn?.addEventListener("click", () => {
      const textToRead = this.lastTeardownSummary || this.panelContent.textContent.slice(0, 450);
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

    if (state.voice) {
      if (this.voicePickerSelect) {
        this.renderVoicePicker(state.voice.available_voices, state.voice.voice_name);
      }
      this.renderVoiceCards(state.voice.available_voices, state.voice.voice_name);
    }

    this.updateTelemetryTab();
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

  renderVoiceCards(availableVoices, activeVoice) {
    if (!this.voiceCardsGrid) return;
    this.voiceCardsGrid.innerHTML = "";
    this.activeVoiceProfile = activeVoice;

    const voiceMeta = {
      "FRIDAY (Local Irish)": {
        name: "F.R.I.D.A.Y. (Irish Female)",
        tag: "CANONICAL STARK AI",
        actor: "Kerry Condon Timbre",
        engine: "macOS Local Moira (en_IE) · 185 WPM",
        desc: "Tactical, quick-witted female Irish voice with zero latency and offline execution.",
        avatarBg: "rgba(56, 189, 248, 0.15)",
        avatarColor: "#38bdf8",
      },
      "FRIDAY (Moira)": {
        name: "F.R.I.D.A.Y. (Alternative Moira)",
        tag: "HIGH VELOCITY",
        actor: "Celtic Acoustic Timbre",
        engine: "macOS Local (en_IE) · 190 WPM",
        desc: "Fast-cadence Irish voice optimized for telemetry readout and rapid diagnostics.",
        avatarBg: "rgba(56, 189, 248, 0.15)",
        avatarColor: "#38bdf8",
      },
      "Jarvis (Daniel)": {
        name: "J.A.R.V.I.S. (Daniel UK)",
        tag: "BRITISH CLASSIC",
        actor: "Paul Bettany Cadence",
        engine: "macOS Local Speech Synth (Daniel)",
        desc: "Traditional UK English male assistant voice for classic Stark butler dialogue.",
        avatarBg: "rgba(168, 85, 247, 0.15)",
        avatarColor: "#c084fc",
      },
      "Daniel": {
        name: "Daniel (Local UK Classic)",
        tag: "BRITISH FORMAL",
        actor: "Traditional UK Assistant",
        engine: "macOS Local Speech Synth",
        desc: "Classic British English male voice for standard offline dialogue and alerts.",
        avatarBg: "rgba(168, 85, 247, 0.15)",
        avatarColor: "#c084fc",
      },
      "Samantha (Local)": {
        name: "Samantha (macOS Natural)",
        tag: "NATURAL AMERICAN",
        actor: "Conversational US",
        engine: "macOS Local Speech Synth",
        desc: "Standard natural American female assistant voice with warm, balanced pitch.",
        avatarBg: "rgba(234, 179, 8, 0.15)",
        avatarColor: "#facc15",
      },
      "Samantha": {
        name: "Samantha (macOS Natural)",
        tag: "NATURAL AMERICAN",
        actor: "Conversational US",
        engine: "macOS Local Speech Synth",
        desc: "Standard natural American female assistant voice with warm, balanced pitch.",
        avatarBg: "rgba(234, 179, 8, 0.15)",
        avatarColor: "#facc15",
      },
      "Jarvis (Cloud ElevenLabs)": {
        name: "J.A.R.V.I.S. (Cloud Neural)",
        tag: "NEURAL STUDIO QUALITY",
        actor: "Paul Bettany Timbre",
        engine: "ElevenLabs Streaming API",
        desc: "Refined, eloquent British male neural timbre running through cloud synthesis.",
        avatarBg: "rgba(56, 189, 248, 0.15)",
        avatarColor: "#38bdf8",
      },
    };

    const voicesToDisplay = (availableVoices && availableVoices.length > 0)
      ? availableVoices
      : Object.keys(voiceMeta);

    voicesToDisplay.forEach((vId) => {
      const meta = voiceMeta[vId] || {
        name: vId,
        tag: "CUSTOM VOICE",
        actor: "System Synth",
        engine: "System Audio Engine",
        desc: "Configured speech synthesizer profile.",
        avatarBg: "rgba(148, 163, 184, 0.15)",
        avatarColor: "#94a3b8",
      };

      const isActive = (vId === activeVoice);

      const card = document.createElement("div");
      card.className = `voice-card ${isActive ? "active-voice" : ""}`;
      card.innerHTML = `
        <div>
          <div class="voice-card-top">
            <div class="voice-card-identity">
              <div class="voice-card-avatar" style="background:${meta.avatarBg}; color:${meta.avatarColor};">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                  <line x1="12" y1="19" x2="12" y2="23"></line>
                </svg>
              </div>
              <div>
                <div class="voice-card-name">${meta.name}</div>
                <div class="voice-card-tag">${meta.tag}</div>
              </div>
            </div>
            ${isActive ? '<span class="voice-active-badge">● ACTIVE</span>' : ''}
          </div>
          <p class="voice-card-desc">${meta.desc}</p>
        </div>
        <div class="voice-card-bottom">
          <span class="voice-card-meta">${meta.engine}</span>
          <button type="button" class="voice-select-pill">
            ${isActive ? 'Active Identity' : 'Switch Voice'}
          </button>
        </div>
      `;

      card.addEventListener("click", async () => {
        if (vId === this.activeVoiceProfile) return;
        await this.switchVoice(vId);
        if (this.voicePickerSelect) {
          this.voicePickerSelect.value = vId;
        }
        this.renderVoiceCards(voicesToDisplay, vId);
      });

      this.voiceCardsGrid.appendChild(card);
    });
  }

  updateTelemetryTab() {
    const brainNameEl = document.getElementById("telemetry-brain-name");
    const brainModelEl = document.getElementById("telemetry-brain-model");
    const voiceNameEl = document.getElementById("telemetry-voice-name");
    const voiceEngineEl = document.getElementById("telemetry-voice-engine");
    const nodesCountEl = document.getElementById("telemetry-nodes-count");

    if (this.systemState?.brain) {
      if (brainNameEl) brainNameEl.textContent = (this.systemState.brain.provider || "OpenRouter").toUpperCase();
      if (brainModelEl) brainModelEl.textContent = this.systemState.brain.model || "Unknown";
    }

    if (this.systemState?.voice) {
      if (voiceNameEl) voiceNameEl.textContent = this.systemState.voice.voice_name || "FRIDAY (Local Irish)";
      if (voiceEngineEl) {
        const isEleven = (this.systemState.voice.voice_name || "").includes("ElevenLabs");
        voiceEngineEl.textContent = isEleven
          ? "ElevenLabs Cloud Neural API"
          : "Local macOS Speech Synthesis (Moira en_IE, 185 WPM)";
      }
    }

    if (nodesCountEl && this.galaxy?.graphData?.nodes) {
      nodesCountEl.textContent = `${this.galaxy.graphData.nodes.length} Nodes Indexed`;
    }
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

  formatMarkdown(md) {
    if (!md) return "";
    let html = md;

    // Code blocks
    html = html.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
      const escaped = code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      return `<pre class="dossier-code-block"><div class="code-lang-tag">${lang || 'code'}</div><code>${escaped}</code></pre>`;
    });

    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code class="dossier-inline-code">$1</code>');

    // Images
    html = html.replace(/!\[(.*?)\]\((.*?)\)/g, '<div class="dossier-img-wrap"><img src="$2" alt="$1" class="dossier-snapshot-img"><div class="img-caption">$1</div></div>');

    // Headers
    html = html.replace(/^### (.*$)/gim, '<h4 class="dossier-h4">$1</h4>');
    html = html.replace(/^## (.*$)/gim, '<h3 class="dossier-h3">$1</h3>');
    html = html.replace(/^# (.*$)/gim, '<h2 class="dossier-h2">$1</h2>');

    // Bold & italic
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

    // Horizontal rules
    html = html.replace(/^\s*---\s*$/gim, '<hr class="dossier-hr">');

    // Markdown tables
    html = html.replace(/((?:\|[^\n]+\|\r?\n)+)/g, (tableText) => {
      const rows = tableText.trim().split("\n");
      if (rows.length < 2) return tableText;
      let tableHtml = '<div class="dossier-table-wrap"><table class="dossier-table">';
      rows.forEach((row, idx) => {
        if (row.includes("---")) return;
        const cells = row.split("|").slice(1, -1);
        const tag = idx === 0 ? "th" : "td";
        tableHtml += "<tr>";
        cells.forEach(cell => {
          tableHtml += `<${tag}>${cell.trim()}</${tag}>`;
        });
        tableHtml += "</tr>";
      });
      tableHtml += "</table></div>";
      return tableHtml;
    });

    // Lists
    html = html.replace(/^\s*-\s+(.*$)/gim, '<li class="dossier-li">$1</li>');
    html = html.replace(/((?:<li class="dossier-li">.*?<\/li>\s*)+)/g, '<ul class="dossier-ul">$1</ul>');

    // Paragraph breaks
    html = html.replace(/\n\n/g, '<p class="dossier-p"></p>');

    return html;
  }

  extractTeardownTarget(text) {
    if (!text) return null;
    let clean = text.trim().replace(/[?!.]+$/, '');
    clean = clean.replace(/^(?:friday|jarvis)[,\s]+/i, '');
    const m = clean.match(/(?:can you\s+)?(?:reverse engineer|teardown|deconstruct|take apart|inspect stack of)\s+(.+?)(?:\s+for me|\s+please)?$/i);
    return m ? m[1].replace(/^["'`]|["'`]$/g, '').trim() : null;
  }

  openReadingPanel(title, content, isHtml = false) {
    this.panelTitle.textContent = title;
    if (isHtml || content.includes("#") || content.includes("```") || content.includes("|")) {
      this.panelContent.innerHTML = this.formatMarkdown(content);
    } else {
      this.panelContent.textContent = content;
    }
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

    // 0. Teardown / Reverse Engineering Check
    const tdTarget = this.extractTeardownTarget(text);
    if (tdTarget) {
      this.isStreaming = true;
      this.reactorSubstatus.textContent = "REA is reading the code";
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({
          action: "teardown",
          target: tdTarget,
        }));
        return;
      }
      try {
        const res = await fetch("/api/tools/teardown", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: tdTarget }),
        });
        const data = await res.json();
        const reply = data.spoken_summary || `Teardown of ${tdTarget} complete, sir.`;
        this.appendMessage("assistant", reply);
        this.sessionHistory.push({ role: "assistant", content: reply });
        this.speakResponse(reply);
        this.lastTeardownSummary = reply;
        if (data.dossier) {
          this.openReadingPanel(`Teardown Dossier: ${tdTarget}`, data.dossier, true);
        }
        this.reactorSubstatus.textContent = "standing by, sir.";
      } catch (err) {
        this.appendMessage("assistant", `Cognitive error during teardown: ${err.message}`);
      } finally {
        this.isStreaming = false;
      }
      return;
    }

    // 1. Direct Mac Action Check: "reveal ... in finder"
    const lower = text.toLowerCase();
    if (lower.startsWith("reveal ") || lower.includes("in finder") || lower.startsWith("show in finder")) {
      let query = text.replace(/^(reveal|show)\s+/i, "").replace(/\s+in finder$/i, "").trim();
      let matchedNode = this.galaxy?.nodes.find(n => n.userData.name.toLowerCase().includes(query.toLowerCase()) || (n.userData.path && n.userData.path.toLowerCase().includes(query.toLowerCase())));
      const targetPath = matchedNode ? matchedNode.userData.path : query;
      const res = await fetch("/api/tools/reveal_in_finder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: targetPath }),
      });
      const data = await res.json();
      const reply = data.success ? `Revealed ${matchedNode ? matchedNode.userData.name : query} in Finder for you, sir.` : `Could not reveal in Finder, sir: ${data.message}`;
      this.appendMessage("assistant", reply);
      this.sessionHistory.push({ role: "assistant", content: reply });
      this.speakResponse(reply);
      this.reactorSubstatus.textContent = `Tool run: Reveal Finder`;
      return;
    }

    // 2. Direct Mac Action Check: "pull up ..." or "focus ..."
    if (lower.startsWith("pull up ") || lower.startsWith("focus ")) {
      const query = text.replace(/^(pull up|focus)\s+/i, "").trim();
      const matchCount = this.galaxy ? this.galaxy.highlightByQuery(query) : 0;
      let matchedNode = this.galaxy?.nodes.find(n => n.userData.name.toLowerCase().includes(query.toLowerCase()));
      if (matchedNode) {
        this.galaxy.selectNode(matchedNode);
        if (this.galaxy.controls) {
          this.galaxy.controls.target.copy(matchedNode.position);
          this.galaxy.camera.position.set(matchedNode.position.x, matchedNode.position.y + 40, matchedNode.position.z + 180);
          this.galaxy.controls.update();
        }
      }
      const reply = matchedNode
        ? `Pulling up ${matchedNode.userData.name} from your second brain, sir. ${matchedNode.userData.summary}`
        : `I searched your second brain for "${query}", sir, and highlighted ${matchCount} matching nodes.`;
      this.appendMessage("assistant", reply);
      this.sessionHistory.push({ role: "assistant", content: reply });
      this.speakResponse(reply);
      this.reactorSubstatus.textContent = `Focused: ${query}`;
      return;
    }

    // 3. Direct Mac App / File Launcher check
    if (lower.startsWith("open ") || lower.startsWith("launch ")) {
      const targetName = text.replace(/^(open|launch)\s+/i, "").trim();
      // Check if it matches a file node
      let matchedFileNode = this.galaxy?.nodes.find(n => !n.userData.is_app && !n.userData.isHub && n.userData.name.toLowerCase() === targetName.toLowerCase());
      if (matchedFileNode) {
        const fileRes = await fetch("/api/tools/open_file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: matchedFileNode.userData.path }),
        });
        const fileData = await fileRes.json();
        const reply = fileData.success
          ? `Opening ${matchedFileNode.userData.name} on your Mac, sir.`
          : `I attempted to open ${matchedFileNode.userData.name}, sir: ${fileData.message}`;
        this.appendMessage("assistant", reply);
        this.sessionHistory.push({ role: "assistant", content: reply });
        this.speakResponse(reply);
        this.reactorSubstatus.textContent = `Tool run: Open File`;
        return;
      }

      // Otherwise launch application
      const appRes = await fetch("/api/tools/open_app", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app_name: targetName }),
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

      case "teardown_progress":
        if (this.reactorSubstatus) {
          this.reactorSubstatus.textContent = data.step;
        }
        break;

      case "teardown_complete":
        if (data.state) {
          this.applyDynamicState(data.state);
        }
        if (data.reply) {
          this.appendMessage("assistant", data.reply);
          this.sessionHistory.push({ role: "assistant", content: data.reply });
          this.speakResponse(data.reply);
        }
        this.lastTeardownSummary = data.reply;
        if (data.dossier) {
          this.openReadingPanel(`Teardown Dossier: ${data.target}`, data.dossier, true);
        }
        this.isStreaming = false;
        if (this.reactorSubstatus) {
          this.reactorSubstatus.textContent = this.isListening ? "listening..." : "standing by, sir.";
        }
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
        if (data.state) {
          this.applyDynamicState(data.state);
        }
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
    if (this.systemState?.voice) {
      this.renderVoiceCards(this.systemState.voice.available_voices, this.systemState.voice.voice_name);
    }
    this.updateTelemetryTab();
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
    this.cachedProvidersData = { providers, activeProvId, currentModel };
    if (!this.providersList) return;

    if (!this.selectedProviderId || !providers.some((p) => p.id === this.selectedProviderId)) {
      this.selectedProviderId = activeProvId || (providers[0] ? providers[0].id : null);
    }

    // 1. Render Segmented Provider Navigation Chips
    if (this.providersSegmentedNav) {
      this.providersSegmentedNav.innerHTML = "";
      providers.forEach((p) => {
        const isSelected = p.id === this.selectedProviderId;
        const isCurrentActiveBrain = p.id === activeProvId;
        const totalCount = p.total_models_count || p.models?.length || 0;

        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = `provider-chip-btn ${isSelected ? "active" : ""} ${isCurrentActiveBrain ? "is-active-brain" : ""}`;
        chip.innerHTML = `
          <span class="provider-chip-dot ${p.is_configured ? 'online' : 'offline'}"></span>
          <span>${p.name}</span>
          ${totalCount > 0 ? `<span style="font-size:0.68rem; color:#64748b; font-family:var(--font-mono);">(${totalCount})</span>` : ''}
          ${isCurrentActiveBrain ? '<span style="font-size:0.62rem; color:#38bdf8; font-family:var(--font-mono); margin-left:2px; font-weight:700;">[ACTIVE]</span>' : ''}
        `;

        chip.addEventListener("click", () => {
          this.selectedProviderId = p.id;
          this.renderProvidersList(providers, activeProvId, currentModel);
        });

        this.providersSegmentedNav.appendChild(chip);
      });
    }

    // 2. Render Single Focused Workspace for the Selected Provider
    this.providersList.innerHTML = "";
    const p = providers.find((x) => x.id === this.selectedProviderId) || providers[0];
    if (!p) return;

    const isCurrentActive = (p.id === activeProvId);
    const card = document.createElement("div");
    card.className = `provider-card ${isCurrentActive ? "active-card" : ""}`;

    const totalCount = p.total_models_count || p.models?.length || 0;
    const freeCount = p.free_models_count || 0;

    const head = document.createElement("div");
    head.className = "provider-head";
    head.innerHTML = `
      <div style="display:flex; align-items:center; flex-wrap:wrap; gap:0.5rem;">
        <span class="provider-title">${p.name}</span>
        <span style="font-size:0.75rem; font-weight:500; color:${p.is_configured ? '#10b981' : '#f43f5e'};">
          ${p.is_configured ? '● Configured & Ready' : '○ Needs API Key'}
        </span>
        ${totalCount > 0 ? `<span class="model-count-badge">${totalCount} Models</span>` : ''}
        ${freeCount > 0 ? `<span class="free-badge">🎁 ${freeCount} Free</span>` : ''}
      </div>
      <div>
        ${isCurrentActive ? '<span class="free-badge" style="background:rgba(56,189,248,0.18); border-color:rgba(56,189,248,0.4); color:#38bdf8;">ACTIVE BRAIN</span>' : ''}
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
    allBtn.type = "button";
    allBtn.className = "model-filter-btn active";
    allBtn.textContent = `All (${totalCount})`;

    const freeBtn = document.createElement("button");
    freeBtn.type = "button";
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
    activateBtn.type = "button";
    activateBtn.className = `action-btn ${isCurrentActive ? "primary" : ""}`;
    activateBtn.textContent = isCurrentActive ? "Active Brain" : "Activate Selected Model";
    activateBtn.addEventListener("click", async () => {
      if (!select.value || select.value === "No models matching filter") return;
      activateBtn.textContent = "Activating...";
      await this.switchProvider(p.id, select.value);
    });

    const testBtn = document.createElement("button");
    testBtn.type = "button";
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
        <button class="action-btn" type="button" id="save-key-btn-${p.id}">Save Key & Discover Models</button>
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

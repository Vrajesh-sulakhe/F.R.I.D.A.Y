/**
 * FRIDAY 3D Galaxy Graph - Live Second Brain & macOS Application Visualizer
 * Dynamically queries real local files, folders, and applications on the user's Mac.
 */

class GalaxyGraph {
  constructor(canvasContainerId, onNodeSelect) {
    this.container = document.getElementById(canvasContainerId);
    this.onNodeSelect = onNodeSelect;
    this.nodes = [];
    this.edges = [];
    this.hubs = [];
    this.categories = {};

    this.selectedNode = null;
    this.hoveredNode = null;
    this.viewMode = "ring";
    this.repelForce = 1.0;
    this.linkLength = 1.0;

    this.catColors = {
      "Applications": 0x38bdf8,
      "Projects": 0x10b981,
      "Code": 0x60a5fa,
      "Documents": 0xf97316,
      "Presentations": 0xf43f5e,
      "Notes": 0xfacc15,
      "Data": 0xa855f7,
      "Config": 0x34d399,
      "Media": 0xec4899,
      "Utilities": 0xef4444,
      "Archives": 0x8b5cf6,
      "Downloads": 0xf97316,
      "Desktop": 0xec4899,
      "Brain": 0xa855f7,
      "Files": 0x94a3b8,
      "Folders": 0xeab308,
    };

    this.initScene();
    this.createTooltipElement();
    this.setupEvents();
    this.loadRealSystemGraph();
    this.animate();
  }

  initScene() {
    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.FogExp2(0x020408, 0.0006);

    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;

    this.camera = new THREE.PerspectiveCamera(55, width / height, 1, 3500);
    this.camera.position.set(0, 90, 560);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.container.appendChild(this.renderer.domElement);

    if (window.THREE && window.THREE.OrbitControls) {
      this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.05;
      this.controls.maxDistance = 1400;
      this.controls.minDistance = 50;
      this.controls.autoRotate = true;
      this.controls.autoRotateSpeed = 0.25;
    }

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.95);
    this.scene.add(ambientLight);

    const coreLight = new THREE.PointLight(0x38bdf8, 2.5, 1000);
    coreLight.position.set(0, 0, 0);
    this.scene.add(coreLight);

    this.createStarfield();

    this.raycaster = new THREE.Raycaster();
    this.mouse = new THREE.Vector2();

    this.nodeGroup = new THREE.Group();
    this.scene.add(this.nodeGroup);
  }

  createTooltipElement() {
    this.tooltip = document.createElement("div");
    this.tooltip.id = "graph-node-tooltip";
    this.tooltip.className = "graph-hud-tooltip";
    this.tooltip.style.display = "none";
    document.body.appendChild(this.tooltip);
  }

  createStarfield() {
    const starGeo = new THREE.BufferGeometry();
    const starCount = 1400;
    const starPos = new Float32Array(starCount * 3);

    for (let i = 0; i < starCount * 3; i += 3) {
      starPos[i] = (Math.random() - 0.5) * 2400;
      starPos[i + 1] = (Math.random() - 0.5) * 2400;
      starPos[i + 2] = (Math.random() - 0.5) * 2400;
    }

    starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
    const starMat = new THREE.PointsMaterial({
      color: 0x64748b,
      size: 1.5,
      transparent: true,
      opacity: 0.65,
    });
    this.scene.add(new THREE.Points(starGeo, starMat));
  }

  async loadRealSystemGraph() {
    try {
      const res = await fetch("/api/second_brain/graph");
      if (!res.ok) throw new Error("Failed to scan system");
      const data = await res.json();

      this.hubs = data.hubs || [];
      this.categories = data.categories || {};
      const realNodes = data.nodes || [];
      const deepEdges = data.edges || [];

      this.buildGalaxyFromRealData(this.hubs, realNodes, deepEdges);

      // Trigger UI callback to update Top Hubs & Filter cards
      if (window.friday) {
        window.friday.renderRealHubsList(this.hubs);
        window.friday.renderRealFilterList(this.categories);
      }
    } catch (e) {
      console.warn("Second brain scan failed:", e);
    }
  }

  buildGalaxyFromRealData(hubs, realNodes, deepEdges = []) {
    // Clear existing
    while (this.nodeGroup.children.length > 0) {
      this.nodeGroup.remove(this.nodeGroup.children[0]);
    }
    this.nodes = [];
    this.edges = [];

    const sphereGeo = new THREE.SphereGeometry(1, 16, 16);
    const hubMeshMap = {};
    const nodeMeshMap = {};

    // 1. Create Hub Meshes
    hubs.forEach((hub, hIdx) => {
      const color = hub.color || this.catColors[hub.category] || 0x38bdf8;
      const hubMat = new THREE.MeshBasicMaterial({ color: color });
      const hubMesh = new THREE.Mesh(sphereGeo, hubMat);

      hubMesh.scale.setScalar(8.0);
      hubMesh.position.set(hub.pos.x, hub.pos.y, hub.pos.z);
      hubMesh.userData = {
        id: hub.id || `hub_${hIdx}`,
        name: hub.name,
        type: "Hub",
        category: hub.category,
        count: hub.count,
        path: hub.path,
        summary: `Local hub scanning: ${hub.path}. Contains ${hub.count} indexed items on your Mac.`,
        isHub: true,
      };

      this.nodeGroup.add(hubMesh);
      this.nodes.push(hubMesh);
      hubMeshMap[hub.name] = hubMesh;
      hubMeshMap[hub.id] = hubMesh;

      // 3D Floating Sprite Label
      const sprite = this.createTextSprite(hub.name, color);
      sprite.position.set(hub.pos.x, hub.pos.y + 15, hub.pos.z);
      this.nodeGroup.add(sprite);

      // Orbital Halo Ring around major Hub
      const ringGeo = new THREE.RingGeometry(11, 12, 32);
      const ringMat = new THREE.MeshBasicMaterial({
        color: color,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.35,
      });
      const ringMesh = new THREE.Mesh(ringGeo, ringMat);
      ringMesh.position.set(hub.pos.x, hub.pos.y, hub.pos.z);
      ringMesh.rotation.x = Math.PI / 2;
      this.nodeGroup.add(ringMesh);
    });

    // 2. Connect Hubs into central galaxy backbone
    for (let i = 0; i < hubs.length - 1; i++) {
      if (this.nodes[i] && this.nodes[i + 1]) {
        this.edges.push({
          start: this.nodes[i],
          end: this.nodes[i + 1],
          color: 0x38bdf8,
        });
      }
    }

    // 3. Create Real Local Nodes around their respective Hubs
    realNodes.forEach((item, nIdx) => {
      const parentHub = hubMeshMap[item.hub] || hubMeshMap[item.hub_id] || this.nodes[0];
      if (!parentHub) return;

      const hubPos = parentHub.position;
      const radius = 30 + (Math.random() * 85);
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos((Math.random() * 2) - 1);

      const nodePos = new THREE.Vector3(
        hubPos.x + radius * Math.sin(phi) * Math.cos(theta),
        hubPos.y + radius * Math.sin(phi) * Math.sin(theta),
        hubPos.z + radius * Math.cos(phi)
      );

      const catColor = this.catColors[item.category] || 0x94a3b8;
      const nodeMat = new THREE.MeshBasicMaterial({
        color: catColor,
        transparent: true,
        opacity: 0.9,
      });

      const nodeMesh = new THREE.Mesh(sphereGeo, nodeMat);
      const nodeScale = item.is_app ? 4.5 : (item.is_dir ? 3.5 : 2.5);
      nodeMesh.scale.setScalar(nodeScale);
      nodeMesh.position.copy(nodePos);

      nodeMesh.userData = {
        id: item.id || `node_${nIdx}`,
        name: item.name,
        type: item.type,
        category: item.category,
        path: item.path,
        hub: item.hub,
        is_app: item.is_app,
        is_dir: item.is_dir,
        size_bytes: item.size_bytes,
        size_human: item.size_human,
        mtime: item.mtime,
        summary: item.summary,
        is_text_readable: item.is_text_readable,
        parent_project: item.parent_project,
        parent_node_id: item.parent_node_id,
        hubMesh: parentHub,
      };

      this.nodeGroup.add(nodeMesh);
      this.nodes.push(nodeMesh);
      nodeMeshMap[item.id] = nodeMesh;

      // Connect node to parent hub
      this.edges.push({
        start: parentHub,
        end: nodeMesh,
        color: catColor,
      });
    });

    // 4. Connect hierarchical sub-edges (e.g. project folder -> its files)
    deepEdges.forEach((e) => {
      const srcMesh = nodeMeshMap[e.source];
      const tgtMesh = nodeMeshMap[e.target];
      if (srcMesh && tgtMesh) {
        this.edges.push({
          start: srcMesh,
          end: tgtMesh,
          color: this.catColors[e.category] || 0x10b981,
        });
      }
    });

    // 5. Generate line geometry
    this.createEdgeLines();
  }

  createEdgeLines() {
    if (this.linesMesh) {
      this.scene.remove(this.linesMesh);
    }

    const positions = [];
    const colors = [];

    this.edges.forEach((edge) => {
      const p1 = edge.start.position;
      const p2 = edge.end.position;

      positions.push(p1.x, p1.y, p1.z);
      positions.push(p2.x, p2.y, p2.z);

      const c = new THREE.Color(edge.color || 0x1e3a8a);
      colors.push(c.r, c.g, c.b, c.r, c.g, c.b);
    });

    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    lineGeo.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));

    const lineMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.22,
      blending: THREE.AdditiveBlending,
    });

    this.linesMesh = new THREE.LineSegments(lineGeo, lineMat);
    this.scene.add(this.linesMesh);
  }

  createTextSprite(text, colorHex) {
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 64;
    const ctx = canvas.getContext("2d");

    ctx.fillStyle = "rgba(0,0,0,0)";
    ctx.fillRect(0, 0, 256, 64);

    ctx.font = "bold 20px 'Inter', sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";

    const c = new THREE.Color(colorHex);
    ctx.fillStyle = `rgb(${Math.floor(c.r * 255)}, ${Math.floor(c.g * 255)}, ${Math.floor(c.b * 255)})`;
    ctx.fillText(text, 128, 32);

    const texture = new THREE.CanvasTexture(canvas);
    const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true, opacity: 0.88 });
    const sprite = new THREE.Sprite(spriteMat);
    sprite.scale.set(38, 9.5, 1);
    return sprite;
  }

  setupEvents() {
    window.addEventListener("resize", () => this.onWindowResize());
    this.renderer.domElement.addEventListener("click", (e) => this.onCanvasClick(e));
    this.renderer.domElement.addEventListener("pointermove", (e) => this.onCanvasPointerMove(e));

    const repelSlider = document.getElementById("repel-slider");
    if (repelSlider) {
      repelSlider.addEventListener("input", (e) => {
        this.repelForce = parseFloat(e.target.value);
        this.updateGraphForces();
      });
    }

    const linkSlider = document.getElementById("link-slider");
    if (linkSlider) {
      linkSlider.addEventListener("input", (e) => {
        this.linkLength = parseFloat(e.target.value);
        this.updateGraphForces();
      });
    }

    document.querySelectorAll(".mode-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        document.querySelectorAll(".mode-pill").forEach(p => p.classList.remove("active"));
        pill.classList.add("active");
        this.setViewMode(pill.getAttribute("data-mode"));
      });
    });

    document.getElementById("fit-graph-btn")?.addEventListener("click", () => this.fitView());
    document.getElementById("reset-view-btn")?.addEventListener("click", () => this.fitView());
  }

  updateGraphForces() {
    this.nodes.forEach((node) => {
      if (!node.userData.isHub && node.userData.hubMesh) {
        const hubPos = node.userData.hubMesh.position;
        const dir = node.position.clone().sub(hubPos).normalize();
        const dist = 45 * this.linkLength + (Math.random() * 45 * this.repelForce);
        node.position.copy(hubPos.clone().add(dir.multiplyScalar(dist)));
      }
    });
    this.createEdgeLines();
  }

  setViewMode(mode) {
    this.viewMode = mode;
    if (mode === "ring") {
      this.camera.position.set(0, 90, 560);
    } else if (mode === "cube") {
      this.camera.position.set(400, 300, 400);
    } else if (mode === "face") {
      this.camera.position.set(0, 0, 360);
    }
    if (this.controls) this.controls.target.set(0, 0, 0);
  }

  fitView() {
    if (this.controls) {
      this.camera.position.set(0, 90, 560);
      this.controls.target.set(0, 0, 0);
      this.controls.update();
    }
  }

  focusHub(hubName) {
    const hubNode = this.nodes.find(n => n.userData.isHub && n.userData.name.toLowerCase() === hubName.toLowerCase());
    if (hubNode) {
      this.selectNode(hubNode);
      if (this.controls) {
        this.controls.target.copy(hubNode.position);
        this.camera.position.set(hubNode.position.x, hubNode.position.y + 50, hubNode.position.z + 200);
        this.controls.update();
      }
    }
  }

  onCanvasPointerMove(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.mouse, this.camera);
    const intersects = this.raycaster.intersectObjects(this.nodes);

    if (intersects.length > 0) {
      const top = intersects[0].object;
      this.hoveredNode = top;
      this.container.style.cursor = "pointer";

      // Show Tooltip
      if (this.tooltip) {
        const u = top.userData;
        const icon = u.is_app ? "💻" : (u.is_dir ? "📁" : "📄");
        this.tooltip.innerHTML = `
          <div class="tooltip-title">${icon} ${u.name}</div>
          <div class="tooltip-meta">${u.category} • ${u.size_human || u.type || ''}</div>
          <div class="tooltip-hub">${u.hub || 'Mac Local'}</div>
        `;
        this.tooltip.style.left = `${e.clientX + 14}px`;
        this.tooltip.style.top = `${e.clientY + 14}px`;
        this.tooltip.style.display = "block";
      }
    } else {
      this.hoveredNode = null;
      this.container.style.cursor = "default";
      if (this.tooltip) {
        this.tooltip.style.display = "none";
      }
    }
  }

  onCanvasClick(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.mouse, this.camera);
    const intersects = this.raycaster.intersectObjects(this.nodes);

    if (intersects.length > 0) {
      this.selectNode(intersects[0].object);
    }
  }

  selectNode(mesh) {
    this.selectedNode = mesh;

    this.nodes.forEach((n) => {
      if (n === mesh) {
        n.material.opacity = 1.0;
        n.scale.setScalar(n.userData.isHub ? 10.0 : 6.0);
      } else {
        n.material.opacity = 0.35;
        n.scale.setScalar(n.userData.isHub ? 7.5 : (n.userData.is_app ? 4.2 : (n.userData.is_dir ? 3.2 : 2.3)));
      }
    });

    if (this.onNodeSelect) {
      this.onNodeSelect(mesh.userData);
    }
  }

  highlightByQuery(query) {
    const q = query.toLowerCase().trim();
    if (!q) {
      this.nodes.forEach(n => {
        n.material.opacity = 0.9;
        n.scale.setScalar(n.userData.isHub ? 8.0 : (n.userData.is_app ? 4.5 : (n.userData.is_dir ? 3.5 : 2.5)));
      });
      return;
    }

    let matchCount = 0;
    this.nodes.forEach(n => {
      const nameMatch = n.userData.name.toLowerCase().includes(q);
      const typeMatch = (n.userData.type || "").toLowerCase().includes(q);
      const catMatch = (n.userData.category || "").toLowerCase().includes(q);
      const pathMatch = (n.userData.path || "").toLowerCase().includes(q);

      if (nameMatch || typeMatch || catMatch || pathMatch) {
        n.material.opacity = 1.0;
        n.scale.setScalar(n.userData.isHub ? 10.0 : 6.0);
        matchCount++;
      } else {
        n.material.opacity = 0.12;
        n.scale.setScalar(n.userData.isHub ? 5.0 : 1.8);
      }
    });

    return matchCount;
  }

  onWindowResize() {
    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  animate() {
    requestAnimationFrame(() => this.animate());
    if (this.controls) this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}

window.GalaxyGraph = GalaxyGraph;

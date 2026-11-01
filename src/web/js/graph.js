/**
 * FRIDAY 3D Galaxy Graph - Second Brain Three.js Visualization
 * Recreates the exact interactive 3D node galaxy from the Jarvis demo.
 */

class GalaxyGraph {
  constructor(canvasContainerId, onNodeSelect) {
    this.container = document.getElementById(canvasContainerId);
    this.onNodeSelect = onNodeSelect;
    this.nodes = [];
    this.edges = [];
    this.hubs = [
      { name: "Skill Suites", color: 0x38bdf8, count: 236, pos: new THREE.Vector3(0, 0, 0) },
      { name: "Local Businesses", color: 0xf59e0b, count: 123, pos: new THREE.Vector3(-180, 40, -60) },
      { name: "AI Workshop", color: 0xeab308, count: 82, pos: new THREE.Vector3(160, -30, 80) },
      { name: "Zubair OS", color: 0xa855f7, count: 51, pos: new THREE.Vector3(-120, -90, 100) },
      { name: "Claude Code", color: 0x60a5fa, count: 48, pos: new THREE.Vector3(140, 90, -100) },
      { name: "YouTube Channel", color: 0xef4444, count: 47, pos: new THREE.Vector3(-60, 140, 70) },
      { name: "SEO Suite", color: 0xc084fc, count: 38, pos: new THREE.Vector3(80, -120, -80) },
      { name: "Build and Sell series", color: 0x10b981, count: 37, pos: new THREE.Vector3(200, 20, 20) },
    ];

    this.categories = {
      "Router": { color: 0x10b981, count: 1 },
      "Wiki": { color: 0xeab308, count: 12 },
      "Concepts": { color: 0xf1f5f9, count: 24 },
      "Suites": { color: 0xa855f7, count: 13 },
      "Skills": { color: 0x38bdf8, count: 197 },
      "Tools": { color: 0xef4444, count: 19 },
      "Worlds": { color: 0xf97316, count: 15 },
      "Notes": { color: 0xfacc15, count: 68 },
      "Files": { color: 0x64748b, count: 195 },
    };

    this.selectedNode = null;
    this.viewMode = "ring"; // "ring", "cube", "face"
    this.repelForce = 1.0;
    this.linkLength = 1.0;

    this.initScene();
    this.generateGalaxyData();
    this.setupEvents();
    this.animate();
  }

  initScene() {
    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.FogExp2(0x04060a, 0.0008);

    const width = this.container.clientWidth || window.innerWidth;
    const height = this.container.clientHeight || window.innerHeight;

    this.camera = new THREE.PerspectiveCamera(55, width / height, 1, 3000);
    this.camera.position.set(0, 80, 520);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.container.appendChild(this.renderer.domElement);

    if (window.THREE && window.THREE.OrbitControls) {
      this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.05;
      this.controls.maxDistance = 1200;
      this.controls.minDistance = 60;
      this.controls.autoRotate = true;
      this.controls.autoRotateSpeed = 0.35;
    }

    // Ambient and point lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.85);
    this.scene.add(ambientLight);

    const coreLight = new THREE.PointLight(0x38bdf8, 2, 800);
    coreLight.position.set(0, 0, 0);
    this.scene.add(coreLight);

    // Starfield particles
    this.createStarfield();

    // Raycaster for click selection
    this.raycaster = new THREE.Raycaster();
    this.mouse = new THREE.Vector2();
  }

  createStarfield() {
    const starGeo = new THREE.BufferGeometry();
    const starCount = 1200;
    const starPos = new Float32Array(starCount * 3);

    for (let i = 0; i < starCount * 3; i += 3) {
      starPos[i] = (Math.random() - 0.5) * 2200;
      starPos[i + 1] = (Math.random() - 0.5) * 2200;
      starPos[i + 2] = (Math.random() - 0.5) * 2200;
    }

    starGeo.setAttribute("position", new THREE.BufferAttribute(starPos, 3));
    const starMat = new THREE.PointsMaterial({
      color: 0x64748b,
      size: 1.5,
      transparent: true,
      opacity: 0.6,
    });
    const starMesh = new THREE.Points(starGeo, starMat);
    this.scene.add(starMesh);
  }

  generateGalaxyData() {
    this.nodeGroup = new THREE.Group();
    this.scene.add(this.nodeGroup);

    const sphereGeo = new THREE.SphereGeometry(1, 12, 12);
    const catKeys = Object.keys(this.categories);

    // 1. Create central Hub Nodes
    this.hubs.forEach((hub, hIdx) => {
      const hubMat = new THREE.MeshBasicMaterial({
        color: hub.color,
        wireframe: false,
      });
      const hubMesh = new THREE.Mesh(sphereGeo, hubMat);
      hubMesh.scale.setScalar(6.5);
      hubMesh.position.copy(hub.pos);
      hubMesh.userData = {
        id: `hub_${hIdx}`,
        name: hub.name,
        type: "Hub",
        category: "Suites",
        count: hub.count,
        summary: `Central cluster coordinating ${hub.count} second brain concepts, notes, and local pipelines.`,
        isHub: true,
      };
      this.nodeGroup.add(hubMesh);
      this.nodes.push(hubMesh);

      // Hub 3D floating sprite label
      const labelSprite = this.createTextSprite(hub.name, hub.color);
      labelSprite.position.set(hub.pos.x, hub.pos.y + 12, hub.pos.z);
      this.nodeGroup.add(labelSprite);

      // 2. Spawn satellite nodes around each hub
      const satelliteCount = Math.min(Math.floor(hub.count / 3), 45);
      for (let s = 0; s < satelliteCount; s++) {
        const radius = 35 + Math.random() * 80;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos((Math.random() * 2) - 1);

        const nodePos = new THREE.Vector3(
          hub.pos.x + radius * Math.sin(phi) * Math.cos(theta),
          hub.pos.y + radius * Math.sin(phi) * Math.sin(theta),
          hub.pos.z + radius * Math.cos(phi)
        );

        const cat = catKeys[Math.floor(Math.random() * catKeys.length)];
        const catColor = this.categories[cat].color;

        const nodeMat = new THREE.MeshBasicMaterial({
          color: catColor,
          transparent: true,
          opacity: 0.9,
        });
        const nodeMesh = new THREE.Mesh(sphereGeo, nodeMat);
        const nodeSize = 2.2 + Math.random() * 2.2;
        nodeMesh.scale.setScalar(nodeSize);
        nodeMesh.position.copy(nodePos);

        const nodeId = `node_${hIdx}_${s}`;
        const nodeName = `${hub.name} / ${cat} #${s + 1}`;
        nodeMesh.userData = {
          id: nodeId,
          name: nodeName,
          type: cat,
          category: cat,
          hub: hub.name,
          summary: `Knowledge node in ${hub.name}. Indexed for fast retrieval and semantic traversal, sir.`,
          hubMesh: hubMesh,
        };

        this.nodeGroup.add(nodeMesh);
        this.nodes.push(nodeMesh);

        // Connect satellite to hub with line
        this.edges.push({
          start: hubMesh,
          end: nodeMesh,
          color: hub.color,
        });
      }
    });

    // 3. Connect related hubs to each other
    for (let i = 0; i < this.hubs.length - 1; i++) {
      this.edges.push({
        start: this.nodes[i],
        end: this.nodes[i + 1],
        color: 0x38bdf8,
      });
    }

    // 4. Build line geometry for edges
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
    const spriteMat = new THREE.SpriteMaterial({ map: texture, transparent: true, opacity: 0.85 });
    const sprite = new THREE.Sprite(spriteMat);
    sprite.scale.set(36, 9, 1);
    return sprite;
  }

  setupEvents() {
    window.addEventListener("resize", () => this.onWindowResize());

    this.renderer.domElement.addEventListener("click", (e) => this.onCanvasClick(e));

    // Force sliders
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

    // View mode selector pills
    document.querySelectorAll(".mode-pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        document.querySelectorAll(".mode-pill").forEach(p => p.classList.remove("active"));
        pill.classList.add("active");
        this.setViewMode(pill.getAttribute("data-mode"));
      });
    });

    // Fit button
    const fitBtn = document.getElementById("fit-graph-btn");
    if (fitBtn) {
      fitBtn.addEventListener("click", () => this.fitView());
    }
  }

  updateGraphForces() {
    this.nodes.forEach((node) => {
      if (!node.userData.isHub && node.userData.hubMesh) {
        const hubPos = node.userData.hubMesh.position;
        const dir = node.position.clone().sub(hubPos).normalize();
        const dist = 50 * this.linkLength + (Math.random() * 40 * this.repelForce);
        node.position.copy(hubPos.clone().add(dir.multiplyScalar(dist)));
      }
    });
    this.createEdgeLines();
  }

  setViewMode(mode) {
    this.viewMode = mode;
    if (mode === "ring") {
      this.camera.position.set(0, 80, 520);
    } else if (mode === "cube") {
      this.camera.position.set(380, 280, 380);
    } else if (mode === "face") {
      this.camera.position.set(0, 0, 340);
    }
    if (this.controls) this.controls.target.set(0, 0, 0);
  }

  fitView() {
    if (this.controls) {
      this.camera.position.set(0, 80, 520);
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
        this.camera.position.set(hubNode.position.x, hubNode.position.y + 40, hubNode.position.z + 180);
        this.controls.update();
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
      const clickedMesh = intersects[0].object;
      this.selectNode(clickedMesh);
    }
  }

  selectNode(mesh) {
    this.selectedNode = mesh;

    // Highlight clicked node and dim others
    this.nodes.forEach((n) => {
      if (n === mesh) {
        n.material.opacity = 1.0;
        n.scale.setScalar(n.userData.isHub ? 8.5 : 4.5);
      } else {
        n.material.opacity = 0.35;
        n.scale.setScalar(n.userData.isHub ? 6.5 : 2.5);
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
        n.scale.setScalar(n.userData.isHub ? 6.5 : 2.5);
      });
      return;
    }

    let matchCount = 0;
    this.nodes.forEach(n => {
      const match = n.userData.name.toLowerCase().includes(q) || n.userData.type.toLowerCase().includes(q);
      if (match) {
        n.material.opacity = 1.0;
        n.scale.setScalar(n.userData.isHub ? 9.0 : 5.0);
        matchCount++;
      } else {
        n.material.opacity = 0.15;
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

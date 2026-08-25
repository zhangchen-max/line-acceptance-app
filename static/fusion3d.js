import * as THREE from "/static/vendor/three.module.min.js";
import { OrbitControls } from "/static/vendor/OrbitControls.js";

const CLASS_COLORS = {
  ground: 0x668c7e,
  foundation: 0x9aaabd,
  tower: 0x63c7ff,
  conductor: 0x8de3cf,
  crossing: 0xc19b6b,
  vegetation: 0x55b77d,
  unknown: 0x91a2b1,
};

const LEVEL_COLORS = {
  严重: 0xff6674,
  关注: 0xf4b84a,
  一般: 0x45d483,
  正常: 0x45d483,
};

class Fusion3DController {
  constructor(container) {
    this.container = container;
    this.data = null;
    this.layers = {};
    this.objects = new Map();
    this.selectables = [];
    this.selected = null;
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.ready = false;
    this.defaultView = null;
    this._init();
  }

  _init() {
    try {
      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      this.renderer.setClearColor(0x07111f, 1);
      this.renderer.outputColorSpace = THREE.SRGBColorSpace;
      this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
      this.renderer.toneMappingExposure = 1.2;
      this.renderer.shadowMap.enabled = true;
      this.renderer.shadowMap.type = THREE.PCFShadowMap;
      this.container.replaceChildren(this.renderer.domElement);
      this.scene = new THREE.Scene();
      this.scene.background = new THREE.Color(0x07111f);
      this.scene.fog = new THREE.FogExp2(0x07111f, 0.00045);
      this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 5000);
      this.controls = new OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.08;
      this.controls.screenSpacePanning = true;
      this.controls.minDistance = 8;
      this.controls.maxDistance = 1800;
      this.root = new THREE.Group();
      this.scene.add(this.root);
      this._addLights();
      this.renderer.domElement.addEventListener("pointerdown", event => this._pick(event));
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(this.container);
      this.ready = true;
      this._animate();
    } catch (error) {
      this._fallback(error);
    }
  }

  _addLights() {
    this.scene.add(new THREE.HemisphereLight(0xb8d8ef, 0x182231, 1.7));
    const key = new THREE.DirectionalLight(0xffffff, 2.1);
    key.position.set(-80, 140, 90);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0x6ebde7, 0.8);
    fill.position.set(120, 50, -100);
    this.scene.add(fill);
  }

  _fallback(error) {
    this.ready = false;
    const fallback = document.getElementById("webgl-fallback");
    if (fallback) fallback.hidden = false;
    console.warn("Fusion 3D unavailable", error);
  }

  setData(data, layers = {}) {
    this.layers = layers;
    if (!this.ready || !data) return;
    if (this.data === data) {
      this.setLayers(layers);
      return;
    }
    this.data = data;
    this._clearRoot();
    this._addGrid(data.scene3d?.bounds || [0, 0, 0, 100, 50, 50]);
    this._addTerrain(data.scene3d?.terrain || [], data.scene3d?.bounds || []);
    this._addPointcloud(data.scene3d?.pointcloud || {});
    this._addComponents(data.scene3d?.components || []);
    this._addConductors(data.scene3d?.conductors || []);
    this._addMarkers(data.profile?.dimensions || [], "check");
    this._addMarkers(data.scene3d?.markers || [], "issue");
    this._addImages(data.layers?.images || []);
    this._frameBounds(data.scene3d?.bounds || [0, 0, 0, 100, 50, 50]);
    this.setLayers(layers);
  }

  _clearRoot() {
    this.selected = null;
    this.objects.clear();
    this.selectables = [];
    while (this.root.children.length) {
      const child = this.root.children.pop();
      child.traverse(object => {
        object.geometry?.dispose?.();
        if (Array.isArray(object.material)) object.material.forEach(material => material.dispose?.());
        else object.material?.dispose?.();
      });
    }
  }

  _addGrid(bounds) {
    const [minX, minY, minZ, maxX, maxY] = bounds;
    const spanX = Math.max(maxX - minX, 20);
    const spanY = Math.max(maxY - minY, 20);
    const size = Math.max(spanX, spanY) * 1.15;
    const divisions = Math.max(10, Math.min(50, Math.round(size / 10)));
    const grid = new THREE.GridHelper(size, divisions, 0x2e6685, 0x17354a);
    grid.position.set((minX + maxX) / 2, minZ - 0.08, -(minY + maxY) / 2);
    grid.material.transparent = true;
    grid.material.opacity = 0.46;
    grid.userData.layer = "grid";
    this.root.add(grid);

    const axes = new THREE.AxesHelper(Math.min(size * 0.12, 35));
    axes.position.set(minX, minZ, -minY);
    axes.userData.layer = "grid";
    this.root.add(axes);
  }

  _addTerrain(terrain, bounds) {
    if (terrain.length < 2 || bounds.length < 6) return;
    const halfWidth = Math.max((bounds[4] - bounds[1]) * 0.55, 18);
    const positions = [];
    const indices = [];
    terrain.forEach((point, index) => {
      positions.push(point.x, point.z - 0.15, halfWidth, point.x, point.z - 0.15, -halfWidth);
      if (index < terrain.length - 1) {
        const offset = index * 2;
        indices.push(offset, offset + 2, offset + 1, offset + 2, offset + 3, offset + 1);
      }
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({ color: 0x294b44, roughness: 0.96, metalness: 0.02, side: THREE.DoubleSide, transparent: true, opacity: 0.84 });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.receiveShadow = true;
    mesh.userData.layer = "objects";
    this.root.add(mesh);
  }

  _addPointcloud(pointcloud) {
    const positions = pointcloud.positions || [];
    const classes = pointcloud.classes || [];
    if (!positions.length) return;
    const vertices = new Float32Array(positions.length * 3);
    const colors = new Float32Array(positions.length * 3);
    positions.forEach((point, index) => {
      vertices[index * 3] = point[0];
      vertices[index * 3 + 1] = point[2];
      vertices[index * 3 + 2] = -point[1];
      const color = new THREE.Color(CLASS_COLORS[classes[index]] || CLASS_COLORS.unknown);
      colors[index * 3] = color.r;
      colors[index * 3 + 1] = color.g;
      colors[index * 3 + 2] = color.b;
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(vertices, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geometry.computeBoundingSphere();
    const material = new THREE.PointsMaterial({ size: 2.7, sizeAttenuation: false, vertexColors: true, transparent: true, opacity: 0.96 });
    const points = new THREE.Points(geometry, material);
    points.userData.layer = "pointcloud";
    this.root.add(points);
  }

  _addComponents(components) {
    components.forEach(component => {
      let object;
      if (component.type.includes("杆塔") || component.type.includes("支撑端")) object = this._tower(component);
      else if (component.type.includes("基础")) object = this._boxComponent(component, 0x8ea1b2, 0.58);
      else if (component.type.includes("交跨")) object = this._boxComponent(component, 0xb58b5c, 0.58);
      else if (component.type.includes("通道")) object = this._vegetation(component);
      else if (!component.type.includes("导线")) object = this._boxComponent(component, 0x638ba4, 0.4);
      if (!object) return;
      object.userData.layer = component.type.includes("交跨") || component.type.includes("通道") ? "objects" : "model";
      this._register(object, component.id);
      this.root.add(object);
    });
  }

  _tower(component) {
    const group = new THREE.Group();
    const [x, y, baseZ] = component.position;
    const height = Math.max(Number(component.height || 25), 8);
    const material = new THREE.MeshStandardMaterial({
      color: component.inferred ? 0x8295a5 : 0x6ec8ef,
      metalness: 0.68,
      roughness: 0.4,
      transparent: Boolean(component.inferred),
      opacity: component.inferred ? 0.58 : 1,
    });
    const base = Math.max(Math.min(height * 0.18, 7), 3.4);
    const top = Math.max(base * 0.22, 0.8);
    const legs = [
      [x - base / 2, baseZ, -y - base / 2, x - top / 2, baseZ + height, -y - top / 2],
      [x + base / 2, baseZ, -y - base / 2, x + top / 2, baseZ + height, -y - top / 2],
      [x - base / 2, baseZ, -y + base / 2, x - top / 2, baseZ + height, -y + top / 2],
      [x + base / 2, baseZ, -y + base / 2, x + top / 2, baseZ + height, -y + top / 2],
    ];
    legs.forEach(values => group.add(beam(values.slice(0, 3), values.slice(3), Math.max(height * 0.012, 0.11), material)));
    const levels = 6;
    for (let index = 0; index <= levels; index += 1) {
      const t = index / levels;
      const levelY = baseZ + height * t;
      const half = base / 2 + (top - base) / 2 * t;
      group.add(beam([x - half, levelY, -y - half], [x + half, levelY, -y - half], 0.085, material));
      group.add(beam([x - half, levelY, -y + half], [x + half, levelY, -y + half], 0.085, material));
      if (index < levels) {
        const nextT = (index + 1) / levels;
        const nextY = baseZ + height * nextT;
        const nextHalf = base / 2 + (top - base) / 2 * nextT;
        group.add(beam([x - half, levelY, -y - half], [x + nextHalf, nextY, -y - nextHalf], 0.065, material));
        group.add(beam([x + half, levelY, -y + half], [x - nextHalf, nextY, -y + nextHalf], 0.065, material));
      }
    }
    [height * 0.72, height * 0.86, height * 0.97].forEach((offset, index) => {
      const arm = base * (index === 1 ? 1.05 : 0.84);
      group.add(beam([x, baseZ + offset, -y - arm], [x, baseZ + offset, -y + arm], 0.13, material));
    });
    group.userData.center = new THREE.Vector3(x, baseZ + height * 0.5, -y);
    return group;
  }

  _boxComponent(component, color, opacity) {
    const bbox = component.bbox3d;
    const size = [Math.max(bbox[3] - bbox[0], 1), Math.max(bbox[5] - bbox[2], 0.6), Math.max(bbox[4] - bbox[1], 1)];
    const geometry = new THREE.BoxGeometry(...size);
    const material = new THREE.MeshStandardMaterial({ color, transparent: true, opacity, roughness: 0.78, metalness: 0.08 });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set((bbox[0] + bbox[3]) / 2, (bbox[2] + bbox[5]) / 2, -(bbox[1] + bbox[4]) / 2);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  }

  _vegetation(component) {
    const group = new THREE.Group();
    const bbox = component.bbox3d;
    const width = Math.max(bbox[3] - bbox[0], 6);
    const depth = Math.max(bbox[4] - bbox[1], 6);
    const baseZ = component.position[2];
    const material = new THREE.MeshStandardMaterial({ color: 0x4d9d69, roughness: 0.9, transparent: true, opacity: 0.74 });
    const count = Math.max(3, Math.min(12, Math.round(width / 5)));
    for (let index = 0; index < count; index += 1) {
      const px = bbox[0] + width * ((index + 0.5) / count);
      const pz = -bbox[1] - depth * (((index * 7) % count + 0.5) / count);
      const height = 5 + (index % 4) * 1.4;
      const crown = new THREE.Mesh(new THREE.ConeGeometry(2.1, height, 7), material);
      crown.position.set(px, baseZ + height / 2, pz);
      group.add(crown);
    }
    return group;
  }

  _addConductors(conductors) {
    conductors.forEach(conductor => conductor.curves.forEach(curve => {
      const points = curve.points.map(point => new THREE.Vector3(point[0], point[2], -point[1]));
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      const material = new THREE.LineDashedMaterial({ color: 0x63c7ff, dashSize: 4, gapSize: 2, transparent: true, opacity: 0.92 });
      const line = new THREE.Line(geometry, material);
      line.computeLineDistances();
      line.userData.layer = "model";
      this._register(line, conductor.id);
      this.root.add(line);
    }));
  }

  _addMarkers(items, kind) {
    items.forEach(item => {
      const location = [item.x, item.y || 0, item.z || 0];
      if (!location.every(value => Number.isFinite(Number(value)))) return;
      const color = LEVEL_COLORS[item.level] || 0x45d483;
      const group = new THREE.Group();
      const core = new THREE.Mesh(
        new THREE.SphereGeometry(kind === "issue" ? 1.3 : 0.95, 18, 12),
        new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.65, roughness: 0.38 }),
      );
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(kind === "issue" ? 2.2 : 1.65, 0.12, 8, 28),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.78 }),
      );
      ring.rotation.x = Math.PI / 2;
      group.add(core, ring);
      group.position.set(location[0], location[2], -location[1]);
      group.userData.layer = "issues";
      this._register(group, item.id);
      this.root.add(group);
    });
  }

  _addImages(images) {
    images.forEach(image => {
      if (![image.x, image.y, image.z].every(value => Number.isFinite(Number(value)))) return;
      const group = new THREE.Group();
      const body = new THREE.Mesh(new THREE.BoxGeometry(2.2, 1.5, 0.8), new THREE.MeshStandardMaterial({ color: 0xa990df, emissive: 0x4f3d78, emissiveIntensity: 0.45 }));
      const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 0.8, 16), body.material);
      lens.rotation.z = Math.PI / 2;
      lens.position.x = 1.4;
      group.add(body, lens);
      group.position.set(image.x, image.z, -image.y);
      group.userData.layer = "images";
      this._register(group, image.id);
      this.root.add(group);
    });
  }

  _register(object, id) {
    object.userData.selectionId = id;
    object.traverse(child => { child.userData.selectionId = id; });
    this.objects.set(id, object);
    this.selectables.push(object);
  }

  setLayers(layers = {}) {
    this.layers = layers;
    if (!this.ready) return;
    this.root.traverse(object => {
      const layer = object.userData.layer;
      if (layer && Object.prototype.hasOwnProperty.call(layers, layer)) object.visible = layers[layer] !== false;
    });
  }

  select(id, focus = false) {
    if (!this.ready) return;
    if (this.selected) this._highlight(this.selected, false);
    this.selected = this.objects.get(id) || null;
    if (!this.selected) return;
    this._highlight(this.selected, true);
    if (focus) this._focusObject(this.selected);
  }

  _highlight(object, active) {
    object.scale.setScalar(active ? 1.08 : 1);
    object.traverse(child => {
      const materials = Array.isArray(child.material) ? child.material : child.material ? [child.material] : [];
      materials.forEach(material => {
        if (!("emissiveIntensity" in material)) return;
        if (material.userData.baseEmissiveIntensity === undefined) material.userData.baseEmissiveIntensity = material.emissiveIntensity || 0;
        material.emissiveIntensity = active ? Math.max(material.userData.baseEmissiveIntensity, 0.9) : material.userData.baseEmissiveIntensity;
      });
    });
  }

  _pick(event) {
    if (!this.ready || !this.selectables.length) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.selectables, true);
    const id = hits.map(hit => hit.object.userData.selectionId).find(Boolean);
    if (id) window.selectFusionItem?.(id, true);
  }

  _focusObject(object) {
    const box = new THREE.Box3().setFromObject(object);
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const distance = Math.max(size.length() * 2.2, 68);
    const direction = new THREE.Vector3(1, 0.65, 1).normalize();
    this.camera.position.copy(center).add(direction.multiplyScalar(distance));
    this.controls.target.copy(center);
    this.controls.update();
  }

  _frameBounds(bounds) {
    const [minX, minY, minZ, maxX, maxY, maxZ] = bounds;
    const center = new THREE.Vector3((minX + maxX) / 2, (minZ + maxZ) / 2, -(minY + maxY) / 2);
    const span = Math.max(maxX - minX, maxY - minY, (maxZ - minZ) * 3, 30);
    this.defaultView = {
      target: center.clone(),
      position: center.clone().add(new THREE.Vector3(span * 0.12, span * 0.32, span * 1.25)),
      span,
    };
    this.setView("reset");
  }

  setView(view) {
    if (!this.ready || !this.defaultView) return;
    const { target, position, span } = this.defaultView;
    this.controls.target.copy(target);
    if (view === "top") this.camera.position.set(target.x, target.y + span * 1.15, target.z + 0.01);
    else if (view === "side") this.camera.position.set(target.x, target.y + span * 0.18, target.z + span * 0.88);
    else this.camera.position.copy(position);
    this.camera.near = Math.max(span / 1000, 0.1);
    this.camera.far = Math.max(span * 12, 2000);
    this.camera.updateProjectionMatrix();
    this.controls.update();
  }

  resize() {
    if (!this.ready) return;
    const rect = this.container.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this.renderer.setSize(rect.width, rect.height, false);
    this.camera.aspect = rect.width / rect.height;
    this.camera.updateProjectionMatrix();
  }

  _animate() {
    if (!this.ready) return;
    requestAnimationFrame(() => this._animate());
    if (!this.container.offsetParent) return;
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}

function beam(start, end, radius, material) {
  const from = new THREE.Vector3(...start);
  const to = new THREE.Vector3(...end);
  const direction = to.clone().sub(from);
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, direction.length(), 6), material);
  mesh.position.copy(from).add(to).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.clone().normalize());
  mesh.castShadow = true;
  return mesh;
}

const container = document.getElementById("fusion-three-container");
if (container) {
  window.LineFusion3D = new Fusion3DController(container);
  window.dispatchEvent(new CustomEvent("fusion3dready"));
}

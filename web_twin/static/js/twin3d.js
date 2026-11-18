/**
 * 3D Digital Twin Scene — Smart Waste Sorting Conveyor
 * Uses global THREE object from CDN (r128). No ES module imports.
 */

(function () {
  'use strict';

  const container = document.getElementById('three-container');

  // ===== 1. Scene =====
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1a2e);
  scene.fog = new THREE.Fog(0x1a1a2e, 15, 30);

  // ===== 2. Camera =====
  const initWidth = Math.max(container.clientWidth, 1);
  const initHeight = Math.max(container.clientHeight, 1);
  const camera = new THREE.PerspectiveCamera(
    60,
    initWidth / initHeight,
    0.1,
    100
  );
  camera.position.set(8, 6, 8);
  camera.lookAt(0, 0, 0);

  // ===== 3. Renderer =====
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(initWidth, initHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.shadowMap.enabled = true;
  container.appendChild(renderer.domElement);

  // ===== 4. Controls =====
  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.minDistance = 3;
  controls.maxDistance = 20;

  // ===== 5. Lighting =====
  const ambientLight = new THREE.AmbientLight(0x404040, 0.6);
  scene.add(ambientLight);

  const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
  dirLight.position.set(5, 10, 5);
  dirLight.castShadow = true;
  scene.add(dirLight);

  const pointLight = new THREE.PointLight(0x00ff88, 0.3);
  pointLight.position.set(0, 3, 0);
  scene.add(pointLight);

  // ===== 6. Ground =====
  const groundGeo = new THREE.PlaneGeometry(20, 20);
  const groundMat = new THREE.MeshStandardMaterial({ color: 0x222222 });
  const ground = new THREE.Mesh(groundGeo, groundMat);
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.01;
  ground.receiveShadow = true;
  scene.add(ground);

  // ===== 7. Conveyor Belt =====
  const beltGeo = new THREE.BoxGeometry(10, 0.3, 1.2);
  const beltMat = new THREE.MeshStandardMaterial({ color: 0x333333 });
  const conveyorBelt = new THREE.Mesh(beltGeo, beltMat);
  conveyorBelt.position.set(0, 0.5, 0);
  conveyorBelt.castShadow = true;
  conveyorBelt.receiveShadow = true;
  scene.add(conveyorBelt);

  // Belt surface lines (animated stripes)
  const stripeMat = new THREE.MeshStandardMaterial({ color: 0x555555 });
  const stripes = [];
  for (let i = 0; i < 10; i++) {
    const stripeGeo = new THREE.BoxGeometry(0.05, 0.01, 1.2);
    const stripe = new THREE.Mesh(stripeGeo, stripeMat);
    stripe.position.set(-4.5 + i * 1.0, 0.66, 0);
    scene.add(stripe);
    stripes.push(stripe);
  }

  // ===== 8. Conveyor Legs (4 legs) =====
  const legGeo = new THREE.CylinderGeometry(0.05, 0.05, 0.5, 8);
  const legMat = new THREE.MeshStandardMaterial({ color: 0x111111 });
  const legPositions = [
    [-4.5, 0.25, 0.5],
    [-4.5, 0.25, -0.5],
    [4.5, 0.25, 0.5],
    [4.5, 0.25, -0.5]
  ];
  legPositions.forEach(function (pos) {
    const leg = new THREE.Mesh(legGeo, legMat);
    leg.position.set(pos[0], pos[1], pos[2]);
    scene.add(leg);
  });

  // ===== 9. Bins =====
  const BIN_COLORS = {
    cardboard: 0x8B4513,
    glass:     0x00ff88,
    metal:     0xcccccc,
    paper:     0xffff00,
    plastic:   0x0088ff,
    trash:     0xff4444
  };

  // 3 bins on each side of the conveyor
  const BIN_POSITIONS = {
    cardboard: { x: -3, z: -1.5 },
    glass:     { x: -1, z: -1.5 },
    metal:     { x:  1, z: -1.5 },
    paper:     { x:  3, z:  1.5 },
    plastic:   { x:  1, z:  1.5 },
    trash:     { x: -1, z:  1.5 }
  };

  const bins = {};

  /**
   * Create a text sprite label using CanvasTexture.
   */
  function makeTextSprite(text, color) {
    var canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 64;
    var ctx = canvas.getContext('2d');
    ctx.fillStyle = 'rgba(0,0,0,0)';
    ctx.fillRect(0, 0, 256, 64);
    ctx.font = 'Bold 28px Segoe UI';
    ctx.textAlign = 'center';
    ctx.fillStyle = color || '#ffffff';
    ctx.fillText(text, 128, 42);

    var tex = new THREE.CanvasTexture(canvas);
    var spriteMat = new THREE.SpriteMaterial({ map: tex, transparent: true });
    var sprite = new THREE.Sprite(spriteMat);
    sprite.scale.set(1.2, 0.3, 1);
    return sprite;
  }

  Object.keys(BIN_POSITIONS).forEach(function (name) {
    var pos = BIN_POSITIONS[name];
    var hexColor = BIN_COLORS[name];

    // Bin container (semi-transparent box)
    var binGeo = new THREE.BoxGeometry(0.8, 0.8, 0.8);
    var binMat = new THREE.MeshStandardMaterial({
      color: hexColor,
      transparent: true,
      opacity: 0.35,
      side: THREE.DoubleSide
    });
    var binMesh = new THREE.Mesh(binGeo, binMat);
    binMesh.position.set(pos.x, 0.4, pos.z);
    binMesh.castShadow = true;
    scene.add(binMesh);

    // Fill level indicator (opaque inner box, starts at scale.y = 0)
    var fillGeo = new THREE.BoxGeometry(0.7, 0.7, 0.7);
    var fillMat = new THREE.MeshStandardMaterial({
      color: hexColor,
      transparent: true,
      opacity: 0.75
    });
    var fillMesh = new THREE.Mesh(fillGeo, fillMat);
    fillMesh.scale.y = 0.001; // near zero initially
    fillMesh.position.set(pos.x, 0.05, pos.z);
    scene.add(fillMesh);

    // Text label above bin
    var colorStr = '#' + hexColor.toString(16).padStart(6, '0');
    var label = makeTextSprite(name.charAt(0).toUpperCase() + name.slice(1), colorStr);
    label.position.set(pos.x, 1.1, pos.z);
    scene.add(label);

    bins[name] = { mesh: binMesh, fillMesh: fillMesh, fill_level: 0 };
  });

  // ===== 10. Waste Object (Textured 3D Parcel + Floating Image Card) =====
  var textureLoader = new THREE.TextureLoader();
  var currentWasteTexture = null;
  var currentWasteColorHex = 0xffffff;

  var wasteObject = new THREE.Group();
  wasteObject.position.set(-4.5, 0.65, 0);
  wasteObject.visible = false;

  // Class-colored base tray sitting directly on the belt
  var trayGeo = new THREE.BoxGeometry(0.68, 0.08, 0.68);
  var trayMat = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    emissive: 0x222222,
    roughness: 0.4
  });
  var wasteTray = new THREE.Mesh(trayGeo, trayMat);
  wasteTray.position.y = 0.04;
  wasteTray.castShadow = true;
  wasteObject.add(wasteTray);

  // 3D cube carrying the real image texture (MeshBasicMaterial keeps photo bright)
  var wasteBoxGeo = new THREE.BoxGeometry(0.58, 0.58, 0.58);
  var wasteBoxMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
  var wasteBox = new THREE.Mesh(wasteBoxGeo, wasteBoxMat);
  wasteBox.position.y = 0.37;
  wasteBox.castShadow = true;
  wasteObject.add(wasteBox);

  // Floating camera-facing image sprite above the cube for clear viewing from any angle
  var wasteSpriteMat = new THREE.SpriteMaterial({
    color: 0xffffff,
    transparent: true,
    opacity: 0.95
  });
  var wasteSprite = new THREE.Sprite(wasteSpriteMat);
  wasteSprite.scale.set(0.85, 0.85, 1);
  wasteSprite.position.y = 1.15;
  wasteSprite.visible = false;
  wasteObject.add(wasteSprite);

  scene.add(wasteObject);

  // ===== 11. Gates / Diverters =====
  var gateGeo = new THREE.BoxGeometry(0.1, 0.4, 0.5);
  var gateMat = new THREE.MeshStandardMaterial({ color: 0xff8800 });
  var gates = {};

  Object.keys(BIN_POSITIONS).forEach(function (name) {
    var pos = BIN_POSITIONS[name];
    var gate = new THREE.Mesh(gateGeo, gateMat.clone());
    // Place gate on belt edge, on the side the bin sits
    var gz = pos.z > 0 ? 0.65 : -0.65;
    gate.position.set(pos.x, 0.85, gz);
    scene.add(gate);
    gates[name] = gate;
  });

  // ===== 12. Camera on Belt (detector) =====
  var camBodyGeo = new THREE.BoxGeometry(0.3, 0.2, 0.3);
  var camBodyMat = new THREE.MeshStandardMaterial({ color: 0x444444 });
  var camBody = new THREE.Mesh(camBodyGeo, camBodyMat);
  camBody.position.set(-3.5, 1.1, 0);
  scene.add(camBody);

  // Camera lens
  var lensGeo = new THREE.CylinderGeometry(0.06, 0.06, 0.15, 12);
  var lensMat = new THREE.MeshStandardMaterial({ color: 0x222222 });
  var lens = new THREE.Mesh(lensGeo, lensMat);
  lens.rotation.x = Math.PI / 2;
  lens.position.set(-3.5, 1.0, 0);
  scene.add(lens);

  // Camera mount post
  var postGeo = new THREE.CylinderGeometry(0.03, 0.03, 0.4, 8);
  var postMat = new THREE.MeshStandardMaterial({ color: 0x666666 });
  var post = new THREE.Mesh(postGeo, postMat);
  post.position.set(-3.5, 0.9, 0.5);
  scene.add(post);

  // ===== 13. Global API Functions =====

  window.updateWastePosition = function (x_normalized, z_offset, y_offset) {
    // x_normalized: 0 to 1 (start to end of belt -> -4.5 to +4.5)
    // Optional z_offset & y_offset allow diverting sideways and dropping into the target bin
    wasteObject.position.x = -4.5 + x_normalized * 9;
    wasteObject.position.z = typeof z_offset === 'number' ? z_offset : 0;
    wasteObject.position.y = 0.65 + (typeof y_offset === 'number' ? y_offset : 0);
    wasteObject.visible = true;
  };

  window.setWasteColor = function (className) {
    var colors = {
      cardboard: 0x8B4513,
      glass:     0x00ff88,
      metal:     0xcccccc,
      paper:     0xffff00,
      plastic:   0x0088ff,
      trash:     0xff4444
    };
    currentWasteColorHex = colors[className] || 0xffffff;
    trayMat.color.setHex(currentWasteColorHex);
    trayMat.emissive.setHex(currentWasteColorHex);
    trayMat.emissiveIntensity = 0.35;
    if (!wasteBoxMat.map) {
      wasteBoxMat.color.setHex(currentWasteColorHex);
    }
  };

  window.setWasteImage = function (imageUrl, onLoaded) {
    if (!imageUrl) {
      if (currentWasteTexture) {
        currentWasteTexture.dispose();
        currentWasteTexture = null;
      }
      wasteBoxMat.map = null;
      wasteBoxMat.color.setHex(currentWasteColorHex);
      wasteBoxMat.needsUpdate = true;
      wasteSpriteMat.map = null;
      wasteSpriteMat.needsUpdate = true;
      wasteSprite.visible = false;
      if (typeof onLoaded === 'function') onLoaded();
      return;
    }

    textureLoader.load(
      imageUrl,
      function (texture) {
        if (currentWasteTexture && currentWasteTexture !== texture) {
          currentWasteTexture.dispose();
        }
        // Crisp rendering for arbitrary (non-power-of-two) uploaded images
        texture.minFilter = THREE.LinearFilter;
        texture.magFilter = THREE.LinearFilter;
        texture.generateMipmaps = false;

        currentWasteTexture = texture;
        wasteBoxMat.map = texture;
        wasteBoxMat.color.setHex(0xffffff); // no tint so real photo colors stay accurate
        wasteBoxMat.needsUpdate = true;

        wasteSpriteMat.map = texture;
        wasteSpriteMat.needsUpdate = true;
        wasteSprite.visible = true;
        if (typeof onLoaded === 'function') onLoaded();
      },
      undefined,
      function () {
        // Fallback to solid class color if image fails to load
        wasteBoxMat.map = null;
        wasteBoxMat.color.setHex(currentWasteColorHex);
        wasteBoxMat.needsUpdate = true;
        wasteSprite.visible = false;
        if (typeof onLoaded === 'function') onLoaded();
      }
    );
  };

  window.updateBinFill = function (binName, fillPercent) {
    if (bins[binName]) {
      var pct = Math.max(0, Math.min(fillPercent, 100));
      var scaleY = pct / 100;
      bins[binName].fillMesh.scale.y = Math.max(scaleY, 0.001);
      bins[binName].fillMesh.position.y = 0.05 + scaleY * 0.35;
      bins[binName].fill_level = pct;
    }
  };

  const gateOrder = Object.keys(BIN_POSITIONS);

  window.animateGate = function (binNameOrIndex) {
    var key = typeof binNameOrIndex === 'number' ? gateOrder[binNameOrIndex] : binNameOrIndex;
    var gate = gates[key];
    if (!gate) return;
    if (gate.userData.closeTimer) {
      clearTimeout(gate.userData.closeTimer);
    }
    gate.rotation.z = Math.PI / 3; // open 60 degrees
    gate.userData.closeTimer = setTimeout(function () {
      gate.rotation.z = 0;
      gate.userData.closeTimer = null;
    }, 500);
  };

  window.hideWaste = function () {
    wasteObject.visible = false;
    wasteObject.position.set(-4.5, 0.65, 0);
  };

  // ===== 14. Animation Loop =====
  var beltOffset = 0;

  function animate() {
    requestAnimationFrame(animate);
    controls.update();

    // Animate belt stripes strictly within conveyor bounds [-5.0, +5.0]
    beltOffset += 0.015;
    for (var i = 0; i < stripes.length; i++) {
      stripes[i].position.x = -5.0 + ((i * 1.0 + beltOffset) % 10);
    }

    renderer.render(scene, camera);
  }
  animate();

  // ===== 15. Window Resize Handler =====
  window.addEventListener('resize', function () {
    var c = document.getElementById('three-container');
    if (!c) return;
    var w = Math.max(c.clientWidth, 1);
    var h = Math.max(c.clientHeight, 1);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  });

})();

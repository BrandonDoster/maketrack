import * as THREE from 'three';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

(function () {
  const el = document.getElementById('stl-viewer');
  if (!el) return;
  const url = el.dataset.stlUrl;
  if (!url) return;

  const isDark = document.documentElement.classList.contains('dark');
  const bg = isDark ? 0x020617 : 0xf1f5f9;

  let width = el.clientWidth;
  let height = el.clientHeight;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(bg);

  const camera = new THREE.PerspectiveCamera(45, width / height || 1, 0.1, 5000);
  camera.position.set(80, 80, 80);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(width, height);
  el.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 0.85);
  key.position.set(50, 100, 70);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.25);
  fill.position.set(-60, -20, -40);
  scene.add(fill);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  new STLLoader().load(
    url,
    (geometry) => {
      geometry.computeBoundingBox();
      const center = new THREE.Vector3();
      geometry.boundingBox.getCenter(center);
      geometry.translate(-center.x, -center.y, -center.z);

      const material = new THREE.MeshPhongMaterial({
        color: 0x10b981,
        specular: 0x222222,
        shininess: 35,
        flatShading: false,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.rotation.x = -Math.PI / 2; // STLs are typically Z-up
      scene.add(mesh);

      const size = new THREE.Vector3();
      geometry.boundingBox.getSize(size);
      const maxDim = Math.max(size.x, size.y, size.z) || 50;
      camera.position.set(maxDim * 1.5, maxDim * 1.2, maxDim * 1.5);
      controls.target.set(0, 0, 0);
      controls.update();
    },
    undefined,
    () => {
      el.innerHTML =
        '<div class="flex h-full w-full items-center justify-center text-sm text-rose-400">Failed to load STL.</div>';
    },
  );

  function tick() {
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  tick();

  const resize = () => {
    width = el.clientWidth;
    height = el.clientHeight;
    if (!width || !height) return;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  };
  window.addEventListener('resize', resize);
})();

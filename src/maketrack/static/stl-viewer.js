import * as THREE from 'three';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// Switchable STL preview. The viewer is built lazily on the first load() so a
// fresh page shows only the collection thumbnail; "Preview" buttons in the
// file list call MaketrackViewer.loadPath(<file_path>) to swap models.
(function () {
  const el = document.getElementById('stl-viewer');
  if (!el) return;

  let scene, camera, renderer, controls, mesh;
  let started = false;

  function init() {
    const placeholder = document.getElementById('preview-placeholder');
    if (placeholder) placeholder.classList.add('hidden');
    el.classList.remove('hidden');

    const isDark = document.documentElement.classList.contains('dark');
    scene = new THREE.Scene();
    scene.background = new THREE.Color(isDark ? 0x020617 : 0xf1f5f9);

    const width = el.clientWidth || 400;
    const height = el.clientHeight || 400;
    camera = new THREE.PerspectiveCamera(45, width / height || 1, 0.1, 5000);
    camera.position.set(80, 80, 80);

    renderer = new THREE.WebGLRenderer({ antialias: true });
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

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;

    const tick = () => {
      controls.update();
      renderer.render(scene, camera);
      requestAnimationFrame(tick);
    };
    tick();

    window.addEventListener('resize', () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });

    started = true;
  }

  function load(url) {
    if (!started) init();
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (w && h) {
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    if (mesh) {
      scene.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
      mesh = null;
    }
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
        mesh = new THREE.Mesh(geometry, material);
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
  }

  // Build the URL from a stored relative path, encoding each segment but
  // keeping the slashes (handles spaces/parens in filenames).
  function loadPath(path) {
    const url = '/model-media/' + path.split('/').map(encodeURIComponent).join('/');
    load(url);
  }

  window.MaketrackViewer = { load, loadPath };
})();

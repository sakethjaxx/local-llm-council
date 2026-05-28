// ── UNIFIED REUSABLE MODAL & GRAPH MODULE ──

let activeFocusTrap = null;
let previousActiveElement = null;

export function openModal(title, contentHtml, onOpenCallback = null) {
  const overlay = document.getElementById('commonModal');
  const titleEl = document.getElementById('commonModalTitle');
  const bodyEl = document.getElementById('commonModalBody');

  if (!overlay || !titleEl || !bodyEl) return;

  // Save previous focus
  previousActiveElement = document.activeElement;

  titleEl.textContent = title;
  bodyEl.innerHTML = contentHtml;
  overlay.style.display = 'flex';
  overlay.setAttribute('aria-hidden', 'false');

  // Trigger onOpen callback
  if (onOpenCallback) {
    onOpenCallback(bodyEl);
  }

  // Setup focus trap
  setupFocusTrap(overlay);

  // Focus the close button first
  const closeBtn = document.getElementById('modalCloseBtn');
  if (closeBtn) closeBtn.focus();
}

export function closeModal() {
  const overlay = document.getElementById('commonModal');
  if (!overlay) return;

  overlay.style.display = 'none';
  overlay.setAttribute('aria-hidden', 'true');

  // Remove focus trap listener
  if (activeFocusTrap) {
    document.removeEventListener('keydown', activeFocusTrap);
    activeFocusTrap = null;
  }

  // Restore previous focus
  if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
    previousActiveElement.focus();
  }
}

function setupFocusTrap(container) {
  const focusableSelectors = 'button, [href], input, select, textarea, [tabindex]:not([-1])';
  
  if (activeFocusTrap) {
    document.removeEventListener('keydown', activeFocusTrap);
  }

  activeFocusTrap = function (e) {
    if (e.key === 'Escape') {
      closeModal();
      return;
    }

    if (e.key !== 'Tab') return;

    const focusables = Array.from(container.querySelectorAll(focusableSelectors))
      .filter(el => !el.disabled && el.tabIndex !== -1 && el.offsetParent !== null);
      
    if (focusables.length === 0) {
      e.preventDefault();
      return;
    }

    const first = focusables[0];
    const last = focusables[focusables.length - 1];

    if (e.shiftKey) {
      if (document.activeElement === first) {
        last.focus();
        e.preventDefault();
      }
    } else {
      if (document.activeElement === last) {
        first.focus();
        e.preventDefault();
      }
    }
  };

  document.addEventListener('keydown', activeFocusTrap);
}

// ── LAZY LOADER FOR VIS-NETWORK ──

let visLoadedPromise = null;

export function ensureVisLoaded() {
  if (window.vis) return Promise.resolve(window.vis);
  if (visLoadedPromise) return visLoadedPromise;

  visLoadedPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://unpkg.com/vis-network/standalone/umd/vis-network.min.js';
    script.onload = () => {
      console.log('vis-network dynamically loaded successfully');
      resolve(window.vis);
    };
    script.onerror = (e) => {
      console.error('Failed to load vis-network script dynamically', e);
      visLoadedPromise = null;
      reject(new Error('Failed to load graph visualization dependency.'));
    };
    document.head.appendChild(script);
  });

  return visLoadedPromise;
}

// ── RENDER GRAPHS ──

export async function renderMemoryGraph(container) {
  try {
    container.innerHTML = '<div style="padding: 24px; color: var(--muted); font-family: monospace;">Loading Knowledge Graph data...</div>';
    
    const [vis, resp] = await Promise.all([
      ensureVisLoaded(),
      fetch('/council/memory').then(r => r.json())
    ]);

    container.innerHTML = '';
    const options = {
      nodes: {
        shape: 'dot', size: 16,
        font: { color: '#2f5d50', face: 'IBM Plex Sans', size: 12 },
        color: { background: '#dde7e1', border: '#2f5d50' },
        shadow: true
      },
      edges: {
        width: 1.5,
        color: { color: 'rgba(47, 93, 80, 0.3)', highlight: '#9c7a4d' },
        font: { color: '#58635d', face: 'IBM Plex Mono', size: 10, align: 'horizontal' },
        arrows: { to: { enabled: true, scaleFactor: 0.5 } },
        smooth: { type: 'continuous' }
      },
      physics: { barnesHut: { gravitationalConstant: -2000, centralGravity: 0.25 } }
    };
    
    new vis.Network(container, resp, options);
  } catch (e) {
    console.error(e);
    container.innerHTML = `<div style="padding: 24px; color: var(--danger); font-family: sans-serif;">Failed to load knowledge graph: ${e.message}</div>`;
  }
}

export async function renderCodeGraph(container) {
  try {
    container.innerHTML = '<div style="padding: 24px; color: var(--muted); font-family: monospace;">Loading Code Dependency Graph...</div>';
    
    const [vis, resp] = await Promise.all([
      ensureVisLoaded(),
      fetch('/project/code-graph').then(r => r.json())
    ]);

    container.innerHTML = '';
    const options = {
      nodes: {
        shape: 'dot',
        size: 14,
        font: { color: '#1f2823', face: 'IBM Plex Mono', size: 12 },
        color: { background: '#eef3f0', border: '#2f5d50' }
      },
      edges: {
        width: 1.5,
        color: { color: 'rgba(47, 93, 80, 0.35)', highlight: '#9c7a4d' },
        font: { color: '#6b756f', face: 'IBM Plex Mono', size: 10, align: 'horizontal' },
        arrows: { to: { enabled: true, scaleFactor: 0.45 } },
        smooth: { type: 'continuous' }
      },
      physics: { barnesHut: { gravitationalConstant: -2200, centralGravity: 0.28 } }
    };

    new vis.Network(container, { nodes: resp.nodes, edges: resp.edges }, options);
  } catch (e) {
    console.error(e);
    container.innerHTML = `<div style="padding: 24px; color: var(--danger); font-family: sans-serif;">Failed to load code graph: ${e.message}</div>`;
  }
}

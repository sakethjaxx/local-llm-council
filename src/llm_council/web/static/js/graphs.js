// Memory graph + code graph modals (vis-network).

import { showToast } from './utils.js';

export async function viewMemory() {
  const modal = document.getElementById('memoryModal');
  document.getElementById('modalTitle').textContent = 'Knowledge graph';
  modal.style.display = 'flex';

  try {
    const resp = await fetch('/council/memory');
    const data = await resp.json();

    const container = document.getElementById('memoryNetwork');
    const options = {
      nodes: {
        shape: 'dot',
        size: 16,
        font: { color: '#1f2823', face: 'IBM Plex Mono', size: 14 },
        color: { background: '#dbe5df', border: '#2f5d50' },
        shadow: true,
      },
      edges: {
        width: 2,
        color: { color: 'rgba(47, 93, 80, 0.4)', highlight: '#9c7a4d' },
        font: { color: '#6b756f', face: 'IBM Plex Mono', size: 11, align: 'horizontal' },
        arrows: { to: { enabled: true, scaleFactor: 0.5 } },
        smooth: { type: 'continuous' },
      },
      physics: { barnesHut: { gravitationalConstant: -3000, centralGravity: 0.3 } },
    };

    new vis.Network(container, data, options);
  } catch (e) {
    console.error(e);
    showToast('Failed to load memory graph.');
  }
}

export function closeMemory() {
  document.getElementById('memoryModal').style.display = 'none';
}

export async function viewCodeGraph() {
  const modal = document.getElementById('memoryModal');
  document.getElementById('modalTitle').textContent = 'Project code graph';
  modal.style.display = 'flex';

  try {
    const resp = await fetch('/project/code-graph');
    const data = await resp.json();

    const container = document.getElementById('memoryNetwork');
    const options = {
      nodes: {
        shape: 'dot',
        size: 14,
        font: { color: '#1f2823', face: 'IBM Plex Mono', size: 12 },
        color: { background: '#dbe5df', border: '#2f5d50' },
      },
      edges: {
        width: 1.5,
        color: { color: 'rgba(47, 93, 80, 0.35)', highlight: '#9c7a4d' },
        font: { color: '#6b756f', face: 'IBM Plex Mono', size: 10, align: 'horizontal' },
        arrows: { to: { enabled: true, scaleFactor: 0.45 } },
        smooth: { type: 'continuous' },
      },
      physics: { barnesHut: { gravitationalConstant: -2200, centralGravity: 0.28 } },
    };

    new vis.Network(container, { nodes: data.nodes, edges: data.edges }, options);
  } catch (e) {
    console.error(e);
    showToast('Failed to load code graph.');
  }
}

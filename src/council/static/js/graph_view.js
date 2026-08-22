async function viewMemory() {
  const modal = document.getElementById('memoryModal');
  const title = document.getElementById('modalTitle');
  if (title) title.textContent = 'Council Knowledge Graph';
  if (modal) modal.style.display = 'flex';
  
  try {
    const resp = await fetch('/council/memory');
    const data = await resp.json();

    const edgeColors = {
      supports: '#2f5d50',
      contradicts: '#9f3d32',
      decision_about: '#9c7a4d',
      depends_on: '#2b5876',
      causes: '#73552f'
    };

    const formattedEdges = (data.edges || []).map(edge => ({
      ...edge,
      color: { color: edgeColors[edge.label] || 'rgba(47, 93, 80, 0.4)', highlight: '#9c7a4d' }
    }));
    
    const container = document.getElementById('memoryNetwork');
    const options = {
      nodes: {
        shape: 'dot', size: 14,
        font: { color: cssVar('--text', '#1f2823'), face: 'SFMono-Regular', size: 12 },
        color: { background: cssVar('--accent-soft', '#dde7e1'), border: cssVar('--accent', '#2f5d50') }
      },
      edges: {
        width: 2,
        font: { color: cssVar('--muted', '#58635d'), face: 'SFMono-Regular', size: 10, align: 'horizontal' },
        arrows: { to: { enabled: true, scaleFactor: 0.5 } },
        smooth: { type: 'continuous' }
      },
      physics: { barnesHut: { gravitationalConstant: -2800, centralGravity: 0.3 } }
    };

    if (window.vis && window.vis.Network) {
      new vis.Network(container, { nodes: data.nodes, edges: formattedEdges }, options);
    }
  } catch (e) {
    alert("Failed to load memory graph.");
  }
}

function closeMemory() {
  const modal = document.getElementById('memoryModal');
  if (modal) modal.style.display = 'none';
}

async function viewCodeGraph() {
  const modal = document.getElementById('memoryModal');
  const pathInput = document.getElementById('projectPathInput')?.value.trim();
  const title = pathInput ? `Code Graph: ${pathInput.split('/').pop()}` : 'Project Code Graph';
  const modalTitle = document.getElementById('modalTitle');
  if (modalTitle) modalTitle.textContent = title;
  if (modal) modal.style.display = 'flex';

  try {
    const url = pathInput ? `/project/code-graph?path=${encodeURIComponent(pathInput)}` : '/project/code-graph';
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    const container = document.getElementById('memoryNetwork');
    const options = {
      nodes: {
        shape: 'dot', size: 14,
        font: { color: cssVar('--text', '#1f2823'), face: 'SFMono-Regular', size: 11 },
        color: { background: cssVar('--accent-soft', '#dde7e1'), border: cssVar('--accent', '#2f5d50') }
      },
      edges: {
        width: 1.5,
        color: { color: 'rgba(47, 93, 80, 0.35)', highlight: '#9c7a4d' },
        font: { color: cssVar('--muted', '#58635d'), face: 'SFMono-Regular', size: 10, align: 'horizontal' },
        arrows: { to: { enabled: true, scaleFactor: 0.45 } },
        smooth: { type: 'continuous' }
      },
      physics: { barnesHut: { gravitationalConstant: -2200, centralGravity: 0.28 } }
    };

    if (window.vis && window.vis.Network) {
      new vis.Network(container, { nodes: data.nodes, edges: data.edges }, options);
    }
  } catch (e) {
    alert("Failed to load project code graph.");
  }
}

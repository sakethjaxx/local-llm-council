function renderSeats() {
  const list = document.getElementById('seatList');
  if (!list) return;
  list.innerHTML = '';
  const installed = new Set(installedModelIds());
  for (const [id, seat] of Object.entries(councilConfig)) {
    const isChairman = id === 'chairman';
    const isLocal = seat.model.startsWith('ollama/');
    const ready = !isLocal || installed.has(seat.model) || !modelCatalog;
    const div = document.createElement('div');
    div.className = 'seat-item';
    div.innerHTML = `
      <div class="seat-header">
        <div class="seat-dot" style="background: ${seat.color}; color: ${seat.color}"></div>
        <div class="seat-title">${seat.icon} ${seat.label}</div>
        <div class="seat-model ${ready ? '' : 'seat-model-missing'}" title="${escapeHtml(seat.model)}${ready ? '' : ' — not installed'}">${escapeHtml(seat.model.split('/').pop())}${ready ? '' : ' ⚠'}</div>
        ${!isChairman ? `<div class="seat-remove" onclick="removeSeat('${id}')" title="Remove seat">✕</div>` : ''}
      </div>
      <div class="seat-edit-fields">
        <select class="seat-model-select" onchange="onSeatModelPicked('${id}', this)" aria-label="Model for ${escapeHtml(seat.label)}">
          ${buildModelOptions(seat.model)}
        </select>
        <input type="text" value="${escapeHtml(seat.persona)}" onchange="updateSeat('${id}', 'persona', this.value)" placeholder="System Persona Prompt">
      </div>
    `;
    list.appendChild(div);
  }
  updateRosterFitSummary();
}

function onSeatModelPicked(id, selectEl) {
  if (selectEl.value === '__custom__') {
    const current = councilConfig[id] ? councilConfig[id].model : '';
    const entered = prompt('Model id (LiteLLM format, e.g. ollama/qwen2.5:7b):', current);
    if (!entered) return renderSeats();
    return updateSeat(id, 'model', entered.trim());
  }
  updateSeat(id, 'model', selectEl.value);
}

function addSeat() {
  const id = 'seat_' + Math.floor(Math.random() * 1000);
  councilConfig[id] = {
    label: "New Expert",
    model: "ollama/qwen2.5:7b",
    color: "#" + Math.floor(Math.random()*16777215).toString(16),
    icon: "N",
    persona: "You are an expert."
  };
  renderSeats();
  refreshPreflight();
}

function removeSeat(id) {
  delete councilConfig[id];
  renderSeats();
  refreshPreflight();
}

function updateSeat(id, field, value) {
  if(councilConfig[id]) councilConfig[id][field] = value;
  if (field === 'model') {
    renderSeats();
    refreshPreflight();
  }
}

function pickInstalledModel(profile, fallback) {
  if (!modelCatalog) return fallback;
  const installed = modelCatalog.models
    .filter(m => m.installed)
    .sort((a, b) => a.size_gb - b.size_gb);
  if (!installed.length) return fallback;

  if (profile === 'turbo') return installed[0].model_id;
  if (profile === 'quality') return installed[installed.length - 1].model_id;
  return installed[Math.floor((installed.length - 1) / 2)].model_id;
}

function applyModelProfile(profile) {
  const profileConfig = MODEL_PROFILES[profile];
  if (!profileConfig) return;

  for (const [id, seat] of Object.entries(councilConfig)) {
    const fallback = profileConfig[id] || profileConfig.architect;
    seat.model = pickInstalledModel(profile, fallback);
  }

  renderSeats();
  refreshPreflight();
  showToast(`${profile[0].toUpperCase()}${profile.slice(1)} profile applied to all seats.`);
}

function removeFile(index) {
  selectedFiles.splice(index, 1);
  renderSelectedFiles();
  refreshPreflight();
}

const PROMPT_TEMPLATES = {
  security: "Conduct an OWASP Top 10 security audit. Focus on authentication/authorization gaps, injection vectors, unauthenticated endpoints, and secrets exposure risk.",
  perf: "Audit this codebase for runtime performance bottlenecks, memory pressure, unbounded loops, inefficient DB queries, and latency optimization opportunities.",
  refactor: "Analyze this code for SOLID principles, coupling, code duplication, maintainability risks, and propose the top 3 highest-value refactoring steps.",
  pr: "Review this pull request diff for correctness bugs, edge cases, breaking API changes, and code quality before merging.",
  incident: "Triage this incident / error log. Identify the root cause, cascading failure vectors, immediate mitigation steps, and long-term prevention mechanisms."
};

function insertPromptTemplate(type) {
  const textarea = document.getElementById('topicText');
  if (!textarea) return;
  const template = PROMPT_TEMPLATES[type] || '';
  textarea.value = template;
  textarea.focus();
  showToast(`Inserted ${type.toUpperCase()} review template.`);
}

function renderSelectedFiles() {
  const fileList = document.getElementById('fileList');
  if (!fileList) return;
  if (!selectedFiles.length) {
    fileList.innerHTML = '';
    return;
  }
  fileList.innerHTML = selectedFiles.map((file, i) => {
    const sizeKb = Math.max(1, Math.round(file.size / 1024));
    const estTokens = Math.max(1, Math.round(file.size / 4));
    return `<div class="file-row">
      <span>${escapeHtml(file.name)} <span class="file-size">(${sizeKb} KB)</span> <span class="file-token-chip">~${estTokens.toLocaleString()} tokens</span></span>
      <button class="remove-file-button" onclick="removeFile(${i})" title="Remove">X</button>
    </div>`;
  }).join('');
}

function initResizer() {
  const resizer = document.getElementById('dragResizer');
  if (!resizer) return;

  let activePointerId = null;

  const setSidebarWidth = (clientX) => {
    const windowWidth = window.innerWidth;
    const maxSidebar = Math.min(500, Math.floor(windowWidth * 0.46));
    const newWidth = Math.min(Math.max(clientX, 300), maxSidebar);
    document.documentElement.style.setProperty('--sidebar-width', `${newWidth}px`);
  };

  const finishDrag = () => {
    activePointerId = null;
    resizer.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  };

  resizer.addEventListener('pointerdown', (event) => {
    activePointerId = event.pointerId;
    resizer.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    try { resizer.setPointerCapture(event.pointerId); } catch {}
    setSidebarWidth(event.clientX);
    event.preventDefault();
  });

  resizer.addEventListener('pointermove', (event) => {
    if (activePointerId !== event.pointerId) return;
    setSidebarWidth(event.clientX);
  });

  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((type) => {
    resizer.addEventListener(type, finishDrag);
  });
}

function initPressFeedback() {
  document.addEventListener('pointerdown', (event) => {
    if (event.target.closest('input, textarea, select')) return;
    const target = event.target.closest('.btn, .replay-run-item');
    if (!target || target.disabled) return;

    target.classList.add('is-pressed');
    const release = () => target.classList.remove('is-pressed');
    target.addEventListener('pointerup', release, { once: true });
    target.addEventListener('pointercancel', release, { once: true });
    target.addEventListener('lostpointercapture', release, { once: true });
    try { target.setPointerCapture(event.pointerId); } catch {}
  });
}

async function extractDroppedFiles(dataTransfer) {
  const files = [];
  const items = dataTransfer?.items;
  if (items && items.length > 0 && items[0].webkitGetAsEntry) {
    const queue = [];
    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry();
      if (entry) queue.push(entry);
    }
    
    async function readEntry(entry, currentPath = '') {
      if (entry.isFile) {
        return new Promise((resolve) => {
          entry.file((file) => {
            const relPath = currentPath ? `${currentPath}/${file.name}` : file.name;
            const renamed = new File([file], relPath, { type: file.type || 'text/plain' });
            files.push(renamed);
            resolve();
          }, () => resolve());
        });
      } else if (entry.isDirectory) {
        const dirName = entry.name;
        if (['.git', 'node_modules', '__pycache__', 'venv', '.venv', 'dist', 'build', '.next', '.nuxt'].includes(dirName)) {
          return;
        }
        const dirReader = entry.createReader();
        return new Promise((resolve) => {
          dirReader.readEntries(async (entries) => {
            for (const subEntry of entries) {
              await readEntry(subEntry, currentPath ? `${currentPath}/${dirName}` : dirName);
            }
            resolve();
          }, () => resolve());
        });
      }
    }
    
    for (const entry of queue) {
      await readEntry(entry);
    }
  } else {
    for (const file of Array.from(dataTransfer?.files || [])) {
      files.push(file);
    }
  }
  return files;
}

function initDragAndDrop() {
  const topicInput = document.getElementById('topicText');
  const fileList = document.getElementById('fileList');
  const dropTargets = [topicInput, fileList].filter(Boolean);

  ['dragenter', 'dragover'].forEach(eventName => {
    document.body.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
    }, false);
  });

  dropTargets.forEach(target => {
    target.addEventListener('dragover', (e) => {
      e.preventDefault();
      target.classList.add('drag-active');
    });
    target.addEventListener('dragleave', () => {
      target.classList.remove('drag-active');
    });
    target.addEventListener('drop', async (e) => {
      e.preventDefault();
      target.classList.remove('drag-active');
      const files = await extractDroppedFiles(e.dataTransfer);
      if (!files.length) return;
      const existingNames = new Set(selectedFiles.map(f => f.name));
      let added = 0;
      for (const f of files) {
        if (!existingNames.has(f.name)) {
          selectedFiles.push(f);
          existingNames.add(f.name);
          added++;
        }
      }
      renderSelectedFiles();
      refreshPreflight();
      showToast(`Added ${added} attachment(s) via drag-and-drop.`);
    });
  });
}

function initKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const modals = ['memoryModal', 'modelLibraryModal', 'replayModal'];
      for (const modalId of modals) {
        const modal = document.getElementById(modalId);
        if (modal && modal.style.display !== 'none' && modal.style.display !== '') {
          modal.style.display = 'none';
        }
      }
    }

    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      if (document.activeElement === document.getElementById('topicText')) {
        e.preventDefault();
        launchCouncil();
      } else if (document.activeElement === document.getElementById('projectPathInput')) {
        e.preventDefault();
        launchProjectReview();
      }
    }
  });
}

/* Fleet Dashboard — Tab navigation, API calls, auto-refresh */

// ── State ───────────────────────────────────────────────────────────────────

let currentTab = 'overview';
let knowledgeFilter = 'all';
let expandedReview = new Set();

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initKnowledgeFilters();
  updateClock();
  setInterval(updateClock, 1000);
  loadAll();
  setInterval(loadAll, 15000); // Auto-refresh every 15s
});

// ── Tab Navigation ──────────────────────────────────────────────────────────

function initTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.tab;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('tab-' + target).classList.add('active');
      currentTab = target;
    });
  });
}

function initKnowledgeFilters() {
  document.getElementById('knowledge-filters').addEventListener('click', e => {
    if (e.target.classList.contains('filter-btn')) {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      knowledgeFilter = e.target.dataset.filter;
      loadKnowledge();
    }
  });
}

function updateClock() {
  const now = new Date();
  document.getElementById('header-time').textContent =
    now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

// ── Load All Data ───────────────────────────────────────────────────────────

async function loadAll() {
  // Always load overview metrics
  loadSystem();
  loadServices();
  loadRoles();
  loadTasks();
  // Load tab-specific data
  loadProjects();
  loadReview();
  loadDebug();
  loadKnowledge();
  loadLogs();
}

// ── API Helpers ─────────────────────────────────────────────────────────────

async function api(path) {
  try {
    const r = await fetch(path);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

// ── System Metrics ──────────────────────────────────────────────────────────

async function loadSystem() {
  const d = await api('/api/system');
  if (!d) return;

  document.getElementById('cpu-value').textContent = d.cpu_percent.toFixed(0) + '%';
  document.getElementById('cpu-cores').textContent = d.cpu_cores + ' cores';
  document.getElementById('cpu-bar').style.width = Math.min(d.cpu_percent, 100) + '%';
  setCpuBarColor(d.cpu_percent);

  document.getElementById('ram-value').textContent = d.ram_used_gb.toFixed(1) + ' GB';
  document.getElementById('ram-sub').textContent = d.ram_used_gb.toFixed(1) + ' / ' + d.ram_total_gb + ' GB';
  document.getElementById('ram-bar').style.width = d.ram_percent + '%';
  setRamBarColor(d.ram_percent);

  document.getElementById('uptime-value').textContent = d.uptime;
  document.getElementById('header-uptime').textContent = 'up ' + d.uptime;
}

function setCpuBarColor(pct) {
  const bar = document.getElementById('cpu-bar');
  if (pct > 80) bar.style.background = 'var(--red)';
  else if (pct > 50) bar.style.background = 'var(--amber)';
  else bar.style.background = 'var(--blue)';
}

function setRamBarColor(pct) {
  const bar = document.getElementById('ram-bar');
  if (pct > 80) bar.style.background = 'var(--red)';
  else if (pct > 60) bar.style.background = 'var(--amber)';
  else bar.style.background = 'var(--purple)';
}

// ── Services ────────────────────────────────────────────────────────────────

async function loadServices() {
  const d = await api('/api/services');
  if (!d) return;
  const el = document.getElementById('services-list');
  el.innerHTML = d.map(s => {
    const isDaemon = s.name === 'Daemon';
    const dot = s.healthy ? 'up' : 'down';
    const statusText = isDaemon
      ? (s.healthy ? `${s.running} running, ${s.queued} queued` : 'stopped')
      : (s.status === 200 ? '200 OK' : (s.status ? s.status : 'down'));
    const link = s.url && !isDaemon
      ? `<a href="${s.url}" target="_blank" class="service-link">Open</a>`
      : '';
    return `<div class="service-row">
      <span class="status-dot ${dot}"></span>
      <span class="service-name">${esc(s.name)}</span>
      <span class="service-port">${s.port ? ':' + s.port : ''}</span>
      <span class="service-status">${statusText}</span>
      ${link}
    </div>`;
  }).join('');
}

// ── Roles ───────────────────────────────────────────────────────────────────

async function loadRoles() {
  const d = await api('/api/roles');
  if (!d) return;
  const icons = { hammer: '\u{1F528}', heart: '\u{2764}\u{FE0F}', chart: '\u{1F4CA}' };
  document.getElementById('roles-grid').innerHTML = d.map(r => `
    <div class="role-chip">
      <span class="role-status ${r.status}"></span>
      <span>${esc(r.name)}</span>
      ${r.detail ? `<span class="role-detail">${esc(r.detail)}</span>` : ''}
    </div>
  `).join('');
}

// ── Tasks ───────────────────────────────────────────────────────────────────

async function loadTasks() {
  const d = await api('/api/tasks');
  if (!d) return;
  const el = document.getElementById('tasks-list');
  if (!d.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📋</div>No tasks</div>';
    return;
  }

  // Sort: running first, then queued, then by date desc
  const order = { running: 0, queued: 1, completed: 2, failed: 3, blocked: 4 };
  d.sort((a, b) => (order[a.status] ?? 5) - (order[b.status] ?? 5));

  el.innerHTML = d.map(t => {
    const icon = { running: '🔄', queued: '📋', completed: '✅', failed: '❌', blocked: '🔴' }[t.status] || '⏳';
    const dur = t.duration_min != null ? t.duration_min + 'm' : '';
    return `<div class="task-row">
      <span class="task-icon">${icon}</span>
      <span class="task-name">${esc(t.slug || t.id)}</span>
      <span class="task-project">${esc(t.project_name || '')}</span>
      <span class="task-status ${t.status}">${t.status}</span>
      <span class="task-duration">${dur}</span>
    </div>`;
  }).join('');
}

// ── Projects ────────────────────────────────────────────────────────────────

async function loadProjects() {
  const d = await api('/api/projects');
  if (!d) return;
  const el = document.getElementById('projects-grid');

  el.innerHTML = d.map(p => {
    const langs = p.languages || {};
    const total = p.lines || 0;
    const langBar = Object.entries(langs).map(([lang, count]) => {
      const pct = total ? (count / total * 100) : 0;
      const color = langColor(lang);
      return `<div class="lang-segment" style="width:${pct}%;background:${color}" title="${lang}: ${count.toLocaleString()} lines"></div>`;
    }).join('');

    const langSummary = Object.entries(langs)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([l, c]) => `${l} ${(c/1000).toFixed(1)}k`)
      .join(' · ');

    const ghLink = p.repo
      ? `<a href="${p.repo.replace('git@github.com:', 'https://github.com/').replace('.git', '')}" target="_blank">GitHub</a>`
      : '';

    return `<div class="project-card">
      <div class="project-header">
        <span class="project-name">${esc(p.name)}</span>
        ${p.primary ? '<span class="project-primary">Primary</span>' : ''}
      </div>
      <div class="lang-bar">${langBar}</div>
      <div class="project-stats">
        <span class="project-stat">${total.toLocaleString()} lines</span>
        <span class="project-stat">${p.commits_week || 0} commits/wk</span>
        ${p.branch ? `<span class="project-stat">${esc(p.branch)}</span>` : ''}
      </div>
      <div class="project-stats" style="margin-top:-4px">
        <span class="project-stat" style="color:var(--text-tertiary)">${langSummary}</span>
      </div>
      <div class="project-links">${ghLink}</div>
    </div>`;
  }).join('');
}

function langColor(lang) {
  const colors = {
    'Python': '#3572A5', 'TypeScript': '#3178C6', 'JavaScript': '#F7DF1E',
    'C++': '#F34B7D', 'C': '#555555', 'CSS': '#563D7C',
    'HTML': '#E34C26', 'Shell': '#89E051', 'Rust': '#DEA584',
    'Go': '#00ADD8', 'Markdown': '#083FA1', 'C/C++ Header': '#F34B7D',
  };
  return colors[lang] || '#888';
}

// ── Review Queue ────────────────────────────────────────────────────────────

async function loadReview() {
  const d = await api('/api/review');
  if (!d) return;
  const el = document.getElementById('review-list');

  // Update badge
  const active = d.filter(r => !r.archived);
  const badge = document.getElementById('review-badge');
  if (active.length > 0) {
    badge.style.display = '';
    badge.textContent = active.length;
  } else {
    badge.style.display = 'none';
  }

  if (!d.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">✅</div>Queue is clear</div>';
    return;
  }

  el.innerHTML = d.map(r => {
    const expanded = expandedReview.has(r.filename);
    const isArchived = r.archived;
    return `<div class="review-item ${isArchived ? 'review-archived' : ''}">
      <div class="review-header" onclick="toggleReview('${esc(r.filename)}')" style="cursor:pointer">
        <span class="review-type ${r.type}">${esc(r.type.replace('_', ' '))}</span>
        <span class="review-task-id">${esc(r.task_id)}</span>
        <span class="review-project">${esc(r.project)}</span>
      </div>
      <div class="review-body ${expanded ? '' : 'collapsed'}">${esc(r.body)}</div>
      ${!isArchived ? `<div class="review-actions">
        ${r.type === 'completed' ? `<button class="btn btn-merge" onclick="action('merge','${esc(r.task_id)}')">✓ Merge</button>` : ''}
        <button class="btn btn-skip" onclick="action('skip','${esc(r.task_id)}')">✗ Skip</button>
        <button class="btn btn-fix" onclick="promptFix('${esc(r.task_id)}')">🔧 Fix</button>
        <button class="btn btn-copy" onclick="copyReview(this, ${JSON.stringify(JSON.stringify(r))})" title="Copy">📋</button>
      </div>` : '<div style="font-size:11px;color:var(--text-tertiary);margin-top:6px">Archived</div>'}
    </div>`;
  }).join('');
}

function toggleReview(filename) {
  if (expandedReview.has(filename)) expandedReview.delete(filename);
  else expandedReview.add(filename);
  loadReview();
}

// ── Debug ───────────────────────────────────────────────────────────────────

async function loadDebug() {
  const d = await api('/api/debug');
  if (!d) return;
  const el = document.getElementById('debug-list');
  if (!d.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🐛</div>No bugs detected</div>';
    return;
  }
  el.innerHTML = d.map(b => `
    <div class="bug-card">
      <div class="bug-header">
        <span class="bug-status ${b.status}">${b.status}</span>
        <span class="bug-title">${esc(b.title)}</span>
        <span class="bug-project">${esc(b.project)}</span>
      </div>
      <div class="bug-body">${esc(b.body)}</div>
      <div class="bug-meta">
        <span>Occurrences: ${b.occurrences}</span>
      </div>
      <div class="review-actions" style="margin-top:8px">
        <button class="btn btn-dispatch" onclick="dispatchBug(${JSON.stringify(JSON.stringify(b))})">Auto-fix</button>
        <button class="btn btn-copy" onclick="copyBug(this, ${JSON.stringify(JSON.stringify(b))})" title="Copy">📋</button>
      </div>
    </div>
  `).join('');
}

// ── Knowledge ───────────────────────────────────────────────────────────────

async function loadKnowledge() {
  const params = knowledgeFilter !== 'all' ? `?tag=${knowledgeFilter}` : '';
  const d = await api('/api/knowledge' + params);
  if (!d) return;
  const el = document.getElementById('knowledge-list');
  if (!d.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📚</div>No knowledge items found</div>';
    return;
  }
  el.innerHTML = d.map(k => `
    <div class="knowledge-card">
      <div class="knowledge-header">
        <span class="knowledge-tag ${k.tag}">${k.tag}</span>
        <span class="knowledge-project">${esc(k.project)}</span>
        <span class="knowledge-source">${esc(k.source)}</span>
      </div>
      <div class="knowledge-text">${esc(k.text)}</div>
    </div>
  `).join('');
}

// ── Logs ────────────────────────────────────────────────────────────────────

async function loadLogs() {
  const d = await api('/api/logs');
  if (!d) return;
  const el = document.getElementById('logs-list');
  if (!d.length) {
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">📄</div>No logs yet</div>';
    return;
  }
  el.innerHTML = d.map(l => `
    <div class="log-entry">
      <div class="log-header">
        <span class="log-task-id">${esc(l.task_id)}</span>
        <span class="log-time">${formatDate(l.modified)}</span>
      </div>
      <div class="log-content">${esc(l.content)}</div>
    </div>
  `).join('');
}

// ── Actions ─────────────────────────────────────────────────────────────────

async function action(type, taskSlug) {
  const r = await fetch('/api/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type, task_slug: taskSlug }),
  });
  if (r.ok) {
    showToast(`${type} → ${taskSlug}`);
    loadReview();
  } else {
    showToast('Action failed');
  }
}

function promptFix(taskSlug) {
  const desc = prompt('Describe the fix:');
  if (desc) {
    action('fix', taskSlug, desc);
  }
}

async function dispatchBug(bugJson) {
  const bug = JSON.parse(bugJson);
  const desc = `Fix bug: ${bug.title} in ${bug.project}`;
  await fetch('/api/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type: 'dispatch', task_slug: bug.project, description: desc }),
  });
  showToast('Bug dispatched for auto-fix');
}

// ── Copy ────────────────────────────────────────────────────────────────────

function copyReview(btn, dataJson) {
  const r = JSON.parse(dataJson);
  const text = `[Context: ${r.project} / ${r.type}]\n${r.body}\nTask: ${r.task_id}\n\nWhat should I do about this?`;
  navigator.clipboard.writeText(text);
  showToast('Copied');
}

function copyBug(btn, dataJson) {
  const b = JSON.parse(dataJson);
  const text = `[Bug: ${b.project}] ${b.title}\n${b.body}\nStatus: ${b.status}, Occurrences: ${b.occurrences}\n\nWhat should I do about this?`;
  navigator.clipboard.writeText(text);
  showToast('Copied');
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function esc(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2000);
}

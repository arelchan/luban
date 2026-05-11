"""Single-file HTML template for the tracing dashboard."""

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Luban Tracing Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
:root {
  --bg: #1a1b26;
  --bg-surface: #24283b;
  --bg-card: #2f3347;
  --bg-hover: #363b54;
  --text: #c0caf5;
  --text-dim: #565f89;
  --text-bright: #ffffff;
  --accent-blue: #7aa2f7;
  --accent-purple: #bb9af7;
  --accent-green: #9ece6a;
  --accent-orange: #e0af68;
  --accent-red: #f7768e;
  --accent-cyan: #7dcfff;
  --border: #3b4261;
  --radius: 6px;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Header */
header {
  padding: 12px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-surface);
  flex-shrink: 0;
}
header h1 { font-size: 16px; color: var(--accent-blue); font-weight: 600; }
header .meta { font-size: 12px; color: var(--text-dim); margin-left: 12px; }
.toolbar {
  display: flex; gap: 8px; align-items: center;
}
.toolbar button {
  background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text); padding: 5px 10px; border-radius: var(--radius);
  cursor: pointer; font-size: 12px;
}
.toolbar button:hover { border-color: var(--accent-blue); }
.toolbar .auto-refresh { font-size: 11px; color: var(--text-dim); }

/* Three-panel layout */
.container {
  display: flex; flex: 1; overflow: hidden;
}
.panel {
  overflow-y: auto; border-right: 1px solid var(--border);
}
.panel:last-child { border-right: none; }
.panel-traces { width: 240px; min-width: 200px; background: var(--bg-surface); }
.panel-spans { width: 320px; min-width: 260px; background: var(--bg); }
.panel-detail { flex: 1; background: var(--bg); display: flex; flex-direction: column; }

/* Panel headers */
.panel-header {
  padding: 10px 14px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-dim);
  border-bottom: 1px solid var(--border);
  background: rgba(0,0,0,0.15);
  position: sticky; top: 0; z-index: 1;
}

/* Trace list (left) */
.trace-item {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.12s;
}
.trace-item:hover { background: var(--bg-hover); }
.trace-item.active { background: var(--bg-card); border-left: 3px solid var(--accent-blue); padding-left: 11px; }
.trace-item .trace-idx {
  background: var(--accent-blue); color: var(--bg);
  font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 3px;
}
.trace-item .trace-time { font-size: 10px; color: var(--text-dim); float: right; }
.trace-item .trace-input {
  font-size: 12px; margin-top: 4px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: var(--text);
}
.trace-item .trace-meta {
  font-size: 10px; color: var(--text-dim); margin-top: 3px;
  display: flex; gap: 8px;
}

/* Span list (middle) */
.span-item {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.12s;
}
.span-item:hover { background: var(--bg-hover); }
.span-item.active { background: var(--bg-card); border-left: 3px solid var(--accent-purple); padding-left: 11px; }
.span-item-header {
  display: flex; align-items: center; gap: 6px;
}
.span-item .span-duration { font-size: 10px; color: var(--text-dim); margin-left: auto; }
.span-item .span-summary {
  font-size: 12px; color: var(--text-dim); margin-top: 3px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

/* Badges */
.badge {
  display: inline-block; font-size: 10px; font-weight: 600;
  padding: 1px 6px; border-radius: 3px; text-transform: uppercase;
}
.badge-turn { background: var(--accent-blue); color: var(--bg); }
.badge-llm { background: var(--accent-purple); color: var(--bg); }
.badge-tool { background: var(--accent-green); color: var(--bg); }
.badge-compression { background: var(--accent-orange); color: var(--bg); }
.badge-subagent { background: var(--accent-cyan); color: var(--bg); }
.badge-error { background: var(--accent-red); color: var(--bg); }

/* Search bar */
.search-bar {
  position: sticky; top: 0; z-index: 2;
  padding: 8px 16px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  display: none;
}
.search-bar.visible { display: flex; align-items: center; gap: 8px; }
.search-bar input {
  flex: 1; background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text); padding: 5px 10px; border-radius: var(--radius);
  font-size: 12px; outline: none;
}
.search-bar input:focus { border-color: var(--accent-blue); }
.search-bar .search-info { font-size: 11px; color: var(--text-dim); white-space: nowrap; }
.search-bar button {
  background: var(--bg-card); border: 1px solid var(--border);
  color: var(--text); padding: 4px 8px; border-radius: var(--radius);
  cursor: pointer; font-size: 12px;
}
.search-bar button:hover { border-color: var(--accent-blue); }
mark.search-highlight {
  background: var(--accent-orange); color: var(--bg); border-radius: 2px;
  padding: 0 1px;
}
mark.search-highlight.current {
  background: var(--accent-red); color: var(--text-bright);
}

/* Detail panel (right) */
.detail-empty {
  display: flex; align-items: center; justify-content: center;
  height: 100%; color: var(--text-dim); font-size: 13px;
}
.detail-header {
  margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border);
}
.detail-header h2 {
  font-size: 14px; font-weight: 600; color: var(--text-bright);
  display: flex; align-items: center; gap: 8px;
}
.detail-header .detail-meta {
  font-size: 11px; color: var(--text-dim); margin-top: 4px;
  font-family: monospace;
}
.detail-section {
  margin-bottom: 12px;
}
.detail-section-title {
  font-size: 11px; font-weight: 600; color: var(--text-dim);
  text-transform: uppercase; letter-spacing: 0.3px;
  margin-bottom: 6px; padding: 6px 0;
  cursor: pointer; user-select: none;
  display: flex; align-items: center; gap: 6px;
}
.detail-section-title::before {
  content: '\\25BC'; font-size: 9px; transition: transform 0.2s;
}
.detail-section.collapsed .detail-section-title::before {
  transform: rotate(-90deg);
}
.detail-section.collapsed .detail-section-body { display: none; }
pre.json-view {
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 10px;
  font-size: 11px; font-family: 'SF Mono', Monaco, 'Fira Code', monospace;
  overflow-x: auto; white-space: pre-wrap; word-break: break-all;
  max-height: 360px; overflow-y: auto; color: var(--text); line-height: 1.5;
}
.json-key { color: var(--accent-blue); }
.json-string { color: var(--accent-green); }
.json-number { color: var(--accent-orange); }
.json-bool { color: var(--accent-purple); }
.json-null { color: var(--text-dim); }

/* Attributes table */
.attr-table { width: 100%; font-size: 12px; border-collapse: collapse; }
.attr-table td {
  padding: 4px 8px; border-bottom: 1px solid var(--border);
}
.attr-table td:first-child {
  color: var(--accent-cyan); font-family: monospace; white-space: nowrap; width: 120px;
}

/* Status */
.status-ok { color: var(--accent-green); }
.status-error { color: var(--accent-red); }

/* Empty states */
.empty-state {
  text-align: center; padding: 40px 16px; color: var(--text-dim);
}
.empty-state p { font-size: 12px; margin-top: 4px; }
</style>
</head>
<body>
<header>
  <div style="display:flex;align-items:center">
    <h1>Luban Tracing</h1>
    <span class="meta" id="session-meta"></span>
  </div>
  <div class="toolbar">
    <label class="auto-refresh">
      <input type="checkbox" id="auto-refresh-toggle" checked> Auto (3s)
    </label>
    <button onclick="fetchData()">Refresh</button>
  </div>
</header>
<div class="container">
  <div class="panel panel-traces">
    <div class="panel-header">Traces</div>
    <div id="trace-list"></div>
  </div>
  <div class="panel panel-spans">
    <div class="panel-header">Spans</div>
    <div id="span-list"></div>
  </div>
  <div class="panel panel-detail">
    <div class="search-bar" id="search-bar">
      <input type="text" id="search-input" placeholder="Search content... (Ctrl+F)" />
      <span class="search-info" id="search-info"></span>
      <button onclick="searchNav(-1)">&#9650;</button>
      <button onclick="searchNav(1)">&#9660;</button>
      <button onclick="closeSearch()">&#10005;</button>
    </div>
    <div id="detail-panel" style="overflow-y:auto;flex:1;padding:16px;">
      <div class="detail-empty">Select a span to view details</div>
    </div>
  </div>
</div>

<script>
let turnsData = [];
let selectedTraceIdx = null;
let selectedSpanId = null;
let autoRefreshTimer = null;
let lastDataHash = '';

function formatTime(ts) {
  if (!ts) return '--';
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false });
}
function formatDuration(ms) {
  if (ms === null || ms === undefined) return '...';
  if (ms < 1000) return Math.round(ms) + 'ms';
  return (ms / 1000).toFixed(2) + 's';
}
function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
function syntaxHighlight(obj) {
  const json = JSON.stringify(obj, null, 2);
  if (!json) return '';
  return json.replace(/("(\\\\u[a-zA-Z0-9]{4}|\\\\[^u]|[^\\\\"])*"(\\s*:)?|\\b(true|false|null)\\b|-?\\d+(?:\\.\\d*)?(?:[eE][+\\-]?\\d+)?)/g,
    function(match) {
      let cls = 'json-number';
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? 'json-key' : 'json-string';
        if (cls === 'json-key') match = match.slice(0,-1) + ':';
      } else if (/true|false/.test(match)) cls = 'json-bool';
      else if (/null/.test(match)) cls = 'json-null';
      return '<span class="'+cls+'">'+match+'</span>';
    });
}

function formatTokens(n) {
  if (!n) return '0';
  if (n >= 1000) return (n/1000).toFixed(1) + 'k';
  return String(n);
}
// Recursively collect LLM usage from a node tree
function collectTokens(node, acc) {
  const span = node.span;
  if (span.span_type === 'llm' && span.output && span.output.usage) {
    const u = span.output.usage;
    acc.inp += u.prompt_tokens || 0;
    acc.out += u.completion_tokens || 0;
    acc.cacheRead += u.cache_read_tokens || 0;
    acc.cacheCreation += u.cache_creation_tokens || 0;
  }
  for (const child of (node.children || [])) collectTokens(child, acc);
}
function getTraceTokens(t) {
  const acc = {inp:0, out:0, cacheRead:0, cacheCreation:0};
  collectTokens(t, acc);
  return acc;
}
function getSessionTokens() {
  const acc = {inp:0, out:0, cacheRead:0, cacheCreation:0};
  for (const t of turnsData) collectTokens(t, acc);
  return acc;
}

function getSpanSummary(span) {
  if (span.span_type === 'llm') {
    const out = span.output || {};
    if (out.tool_calls && out.tool_calls.length) return 'tool_calls: ' + out.tool_calls.map(tc=>tc.name).join(', ');
    const c = out.content || '';
    return c.slice(0, 60) || '(empty)';
  }
  if (span.span_type === 'tool') {
    const inp = span.input || {};
    return inp.name || '?';
  }
  if (span.span_type === 'turn') {
    return typeof span.input === 'string' ? span.input.slice(0,50) : '';
  }
  if (span.span_type === 'subagent') {
    const inp = span.input || {};
    return (inp.task || '').slice(0, 60);
  }
  return '';
}

function countSpanTypes(node, counts) {
  counts[node.span.span_type] = (counts[node.span.span_type] || 0) + 1;
  for (const c of (node.children || [])) countSpanTypes(c, counts);
}
function renderTraceList() {
  const el = document.getElementById('trace-list');
  if (!turnsData.length) {
    el.innerHTML = '<div class="empty-state"><p>No traces yet</p></div>';
    return;
  }
  el.innerHTML = turnsData.map((t, i) => {
    const span = t.span;
    const active = selectedTraceIdx === i ? ' active' : '';
    const input = typeof span.input === 'string' ? span.input : JSON.stringify(span.input);
    const counts = {};
    countSpanTypes(t, counts);
    const llmCount = (counts['llm'] || 0);
    const toolCount = (counts['tool'] || 0);
    const subCount = (counts['subagent'] || 0);
    const tok = getTraceTokens(t);
    const tokStr = tok.inp || tok.out ? `${formatTokens(tok.inp)}/${formatTokens(tok.out)}` : '';
    const subBadge = subCount ? `<span style="color:var(--accent-cyan)">${subCount}SA</span>` : '';
    return `<div class="trace-item${active}" onclick="selectTrace(${i})">
      <span class="trace-idx">#${span.attributes.turn_index||i+1}</span>
      <span class="trace-time">${formatTime(span.start_time)}</span>
      <div class="trace-input">${escapeHtml(input.slice(0,50))}</div>
      <div class="trace-meta">
        <span>${formatDuration(span.duration_ms)}</span>
        <span>${llmCount}L ${toolCount}T ${subBadge}</span>
        ${tokStr ? `<span>${tokStr}</span>` : ''}
        <span class="${span.status==='error'?'status-error':'status-ok'}">${span.status}</span>
      </div>
    </div>`;
  }).join('');
}

// Track collapsed subagent nodes
const collapsedSubagents = new Set();

function renderSpanNode(node, depth) {
  const span = node.span;
  const active = selectedSpanId === span.span_id ? ' active' : '';
  const badgeCls = span.status === 'error' ? 'badge-error' : `badge-${span.span_type}`;
  const summary = getSpanSummary(span);
  const indent = depth * 14;
  const hasChildren = node.children && node.children.length > 0;
  const isSubagent = span.span_type === 'subagent';
  const isCollapsed = collapsedSubagents.has(span.span_id);

  let toggleHtml = '';
  if (hasChildren) {
    const icon = isCollapsed ? '▶' : '▼';
    toggleHtml = `<span class="span-toggle" onclick="toggleSubagent(event,'${span.span_id}')" style="cursor:pointer;margin-right:4px;font-size:9px;color:var(--text-dim)">${icon}</span>`;
  }

  let html = `<div class="span-item${active}" onclick="selectSpan('${span.span_id}')" style="padding-left:${14 + indent}px">
    <div class="span-item-header">
      ${toggleHtml}<span class="badge ${badgeCls}">${span.span_type}</span>
      <span class="span-duration">${formatDuration(span.duration_ms)}</span>
    </div>
    <div class="span-summary" style="padding-left:${hasChildren ? 14 : 0}px">${escapeHtml(summary)}</div>
  </div>`;

  if (hasChildren && !isCollapsed) {
    for (const child of node.children) {
      html += renderSpanNode(child, depth + 1);
    }
  }
  return html;
}

function toggleSubagent(e, spanId) {
  e.stopPropagation();
  if (collapsedSubagents.has(spanId)) collapsedSubagents.delete(spanId);
  else collapsedSubagents.add(spanId);
  renderSpanList();
}

function renderSpanList() {
  const el = document.getElementById('span-list');
  if (selectedTraceIdx === null) {
    el.innerHTML = '<div class="empty-state"><p>Select a trace</p></div>';
    return;
  }
  const t = turnsData[selectedTraceIdx];
  el.innerHTML = renderSpanNode(t, 0);
}

function findSpanInNode(node, spanId) {
  if (node.span.span_id === spanId) return node.span;
  for (const child of (node.children || [])) {
    const found = findSpanInNode(child, spanId);
    if (found) return found;
  }
  return null;
}
function findSpan(spanId) {
  for (const t of turnsData) {
    const found = findSpanInNode(t, spanId);
    if (found) return found;
  }
  return null;
}

function renderDetail() {
  const el = document.getElementById('detail-panel');
  if (!selectedSpanId) {
    el.innerHTML = '<div class="detail-empty">Select a span to view details</div>';
    return;
  }
  const span = findSpan(selectedSpanId);
  if (!span) { el.innerHTML = '<div class="detail-empty">Span not found</div>'; return; }

  const badgeCls = span.status === 'error' ? 'badge-error' : `badge-${span.span_type}`;
  const attrs = span.attributes || {};

  let html = `<div class="detail-header">
    <h2><span class="badge ${badgeCls}">${span.span_type.toUpperCase()}</span> ${formatDuration(span.duration_ms)}</h2>
    <div class="detail-meta">
      span_id: ${span.span_id} &nbsp;|&nbsp; trace_id: ${span.trace_id}<br>
      session_id: ${span.session_id}${span.parent_span_id ? ' &nbsp;|&nbsp; parent: '+span.parent_span_id : ''}
    </div>
  </div>`;

  // Token Usage (for LLM spans)
  if (span.span_type === 'llm' && span.output && span.output.usage) {
    const u = span.output.usage;
    const uncached = (u.prompt_tokens||0) - (u.cache_read_tokens||0);
    html += `<div class="detail-section">
      <div class="detail-section-title" onclick="this.parentElement.classList.toggle('collapsed')">Token Usage</div>
      <div class="detail-section-body"><table class="attr-table">
        <tr><td>Input</td><td>${(u.prompt_tokens||0).toLocaleString()}</td></tr>
        <tr><td>├ Cache hit</td><td>${(u.cache_read_tokens||0).toLocaleString()}</td></tr>
        <tr><td>├ Cache write</td><td>${(u.cache_creation_tokens||0).toLocaleString()}</td></tr>
        <tr><td>└ Uncached</td><td>${uncached.toLocaleString()}</td></tr>
        <tr><td>Output</td><td>${(u.completion_tokens||0).toLocaleString()}</td></tr>
        <tr><td>Total</td><td>${(u.total_tokens||0).toLocaleString()}</td></tr>
      </table></div>
    </div>`;
  }

  // Attributes
  if (Object.keys(attrs).length) {
    html += `<div class="detail-section">
      <div class="detail-section-title" onclick="this.parentElement.classList.toggle('collapsed')">Attributes</div>
      <div class="detail-section-body"><table class="attr-table">
        ${Object.entries(attrs).map(([k,v])=>`<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(JSON.stringify(v))}</td></tr>`).join('')}
      </table></div>
    </div>`;
  }

  // Input
  if (span.input !== null && span.input !== undefined) {
    html += `<div class="detail-section">
      <div class="detail-section-title" onclick="this.parentElement.classList.toggle('collapsed')">Input</div>
      <div class="detail-section-body"><pre class="json-view">${syntaxHighlight(span.input)}</pre></div>
    </div>`;
  }

  // Output
  if (span.output !== null && span.output !== undefined) {
    html += `<div class="detail-section">
      <div class="detail-section-title" onclick="this.parentElement.classList.toggle('collapsed')">Output</div>
      <div class="detail-section-body"><pre class="json-view">${syntaxHighlight(span.output)}</pre></div>
    </div>`;
  }

  el.innerHTML = html;
}

function selectTrace(idx) {
  selectedTraceIdx = idx;
  selectedSpanId = null;
  renderTraceList();
  renderSpanList();
  renderDetail();
}
function selectSpan(spanId) {
  selectedSpanId = spanId;
  renderSpanList();
  renderDetail();
}

async function fetchData() {
  try {
    const resp = await fetch('/api/spans');
    const raw = await resp.text();

    // Skip re-render if data unchanged
    if (raw === lastDataHash) return;
    lastDataHash = raw;

    const data = JSON.parse(raw);
    turnsData = data.turns || [];
    const st = getSessionTokens();
    const cacheRate = st.inp > 0 ? Math.round(st.cacheRead / st.inp * 100) : 0;
    // Count only root-level turns (span_type=turn, not subagent/compression)
    const turnCount = turnsData.filter(t => t.span && t.span.span_type === 'turn').length;
    let metaText = 'Session: ' + (data.session_id||'?') + ' | Turns: ' + turnCount;
    if (st.inp || st.out) metaText += ` | ${formatTokens(st.inp)} in / ${formatTokens(st.out)} out (cache hit: ${cacheRate}%)`;
    document.getElementById('session-meta').textContent = metaText;
    renderTraceList();
    if (selectedTraceIdx !== null) { renderSpanList(); }
    // Don't re-render detail on data refresh — only on explicit span selection
  } catch(e) { console.error('Fetch error:', e); }
}

function setupAutoRefresh() {
  const toggle = document.getElementById('auto-refresh-toggle');
  toggle.addEventListener('change', () => {
    if (toggle.checked) { autoRefreshTimer = setInterval(fetchData, 3000); }
    else { clearInterval(autoRefreshTimer); autoRefreshTimer = null; }
  });
  autoRefreshTimer = setInterval(fetchData, 3000);
}

// ─── Search functionality ─────────────────────────
let searchMatches = [];
let searchCurrentIdx = -1;

function openSearch() {
  const bar = document.getElementById('search-bar');
  bar.classList.add('visible');
  const input = document.getElementById('search-input');
  input.focus();
  input.select();
}

function closeSearch() {
  const bar = document.getElementById('search-bar');
  bar.classList.remove('visible');
  document.getElementById('search-input').value = '';
  document.getElementById('search-info').textContent = '';
  clearHighlights();
  searchMatches = [];
  searchCurrentIdx = -1;
}

function clearHighlights() {
  const panel = document.getElementById('detail-panel');
  const marks = panel.querySelectorAll('mark.search-highlight');
  marks.forEach(m => {
    const parent = m.parentNode;
    parent.replaceChild(document.createTextNode(m.textContent), m);
    parent.normalize();
  });
}

function performSearch(query) {
  clearHighlights();
  searchMatches = [];
  searchCurrentIdx = -1;
  const info = document.getElementById('search-info');

  if (!query || query.length < 1) {
    info.textContent = '';
    return;
  }

  const panel = document.getElementById('detail-panel');
  // Walk all text nodes inside pre.json-view and other content
  const walker = document.createTreeWalker(panel, NodeFilter.SHOW_TEXT, null);
  const textNodes = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode);

  const lowerQuery = query.toLowerCase();

  textNodes.forEach(node => {
    const text = node.textContent;
    const lowerText = text.toLowerCase();
    let idx = lowerText.indexOf(lowerQuery);
    if (idx === -1) return;

    // Split text node and wrap matches
    const frag = document.createDocumentFragment();
    let lastIdx = 0;
    while (idx !== -1) {
      // Text before match
      if (idx > lastIdx) frag.appendChild(document.createTextNode(text.slice(lastIdx, idx)));
      // The match
      const mark = document.createElement('mark');
      mark.className = 'search-highlight';
      mark.textContent = text.slice(idx, idx + query.length);
      frag.appendChild(mark);
      searchMatches.push(mark);
      lastIdx = idx + query.length;
      idx = lowerText.indexOf(lowerQuery, lastIdx);
    }
    // Remaining text
    if (lastIdx < text.length) frag.appendChild(document.createTextNode(text.slice(lastIdx)));
    node.parentNode.replaceChild(frag, node);
  });

  if (searchMatches.length > 0) {
    searchCurrentIdx = 0;
    highlightCurrent();
    info.textContent = `1/${searchMatches.length}`;
  } else {
    info.textContent = '0 results';
  }
}

function highlightCurrent() {
  searchMatches.forEach((m, i) => {
    m.classList.toggle('current', i === searchCurrentIdx);
  });
  if (searchMatches[searchCurrentIdx]) {
    searchMatches[searchCurrentIdx].scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

function searchNav(dir) {
  if (!searchMatches.length) return;
  searchCurrentIdx = (searchCurrentIdx + dir + searchMatches.length) % searchMatches.length;
  highlightCurrent();
  document.getElementById('search-info').textContent =
    `${searchCurrentIdx + 1}/${searchMatches.length}`;
}

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    e.preventDefault();
    openSearch();
  }
  if (e.key === 'Escape') {
    closeSearch();
  }
  if (e.key === 'Enter' && document.activeElement === document.getElementById('search-input')) {
    e.preventDefault();
    if (e.shiftKey) searchNav(-1);
    else searchNav(1);
  }
});

// Search on input
document.getElementById('search-input').addEventListener('input', (e) => {
  performSearch(e.target.value);
});

fetchData();
setupAutoRefresh();
</script>
</body>
</html>
"""

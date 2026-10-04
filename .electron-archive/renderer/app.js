const state = {
  boot: null,
  activeCommandFilter: 'all',
  activeCommand: null,
  selectedProvider: '',
  selectedModel: '',
  selectedSessionId: '',
  activeAgent: '',
  modelCatalog: {},
  modelErrors: {},
  files: [],
  sessions: [],
  agents: [],
  themes: [
    { name: 'Royal Gold', tier: 'free', accent: '#e3a72d', text: '#f5d999', muted: '#b08a45', bgA: '#050403', bgB: '#160b04', panelA: 'rgba(18, 14, 8, 0.96)', panelB: 'rgba(7, 7, 6, 0.96)', green: '#8ed35f', red: '#ef6b5a', logoOpacity: '0.20', logoFilter: 'saturate(0.85) contrast(1.08)' },
    { name: 'Emerald Gate', tier: 'free', accent: '#74d66f', text: '#d8ffd0', muted: '#7eb875', bgA: '#020704', bgB: '#07190d', panelA: 'rgba(6, 22, 12, 0.96)', panelB: 'rgba(2, 8, 5, 0.96)', green: '#a8ff7a', red: '#ff6f6f', logoOpacity: '0.16', logoFilter: 'hue-rotate(60deg) saturate(0.9) contrast(1.1)' },
    { name: 'Arc Blue', tier: 'free', accent: '#7ab7ff', text: '#dcecff', muted: '#8aa9c8', bgA: '#03060b', bgB: '#071526', panelA: 'rgba(7, 18, 31, 0.96)', panelB: 'rgba(3, 7, 12, 0.96)', green: '#8af0d2', red: '#ff7488', logoOpacity: '0.16', logoFilter: 'hue-rotate(185deg) saturate(0.72) contrast(1.12)' },
    { name: 'Regal Violet', tier: 'free', accent: '#c7a0ff', text: '#efe2ff', muted: '#a991c8', bgA: '#07040d', bgB: '#160927', panelA: 'rgba(20, 11, 32, 0.96)', panelB: 'rgba(6, 4, 10, 0.96)', green: '#9df2b0', red: '#ff7b9c', logoOpacity: '0.17', logoFilter: 'hue-rotate(245deg) saturate(0.78) contrast(1.08)' },
    { name: 'Signal Red', tier: 'free', accent: '#ff756a', text: '#ffe1dc', muted: '#c18882', bgA: '#090302', bgB: '#260806', panelA: 'rgba(32, 9, 7, 0.96)', panelB: 'rgba(8, 3, 2, 0.96)', green: '#9ee879', red: '#ff756a', logoOpacity: '0.15', logoFilter: 'hue-rotate(320deg) saturate(0.9) contrast(1.12)' },
    { name: 'Copper Line', tier: 'free', accent: '#c97d33', text: '#ffdcb8', muted: '#ae7d56', bgA: '#060403', bgB: '#1b0d05', panelA: 'rgba(24, 14, 8, 0.96)', panelB: 'rgba(7, 5, 4, 0.96)', green: '#a4d66f', red: '#f0775f', logoOpacity: '0.18', logoFilter: 'sepia(0.35) saturate(0.9) contrast(1.08)' },
    { name: 'Ice Terminal', tier: 'free', accent: '#9ee7ff', text: '#e8fbff', muted: '#92b8c2', bgA: '#020607', bgB: '#082026', panelA: 'rgba(7, 25, 29, 0.96)', panelB: 'rgba(2, 7, 8, 0.96)', green: '#b8ffdc', red: '#ff8090', logoOpacity: '0.14', logoFilter: 'hue-rotate(165deg) saturate(0.55) brightness(1.08)' },
    { name: 'Solar Ink', tier: 'free', accent: '#f5c94c', text: '#fff0bd', muted: '#baa25d', bgA: '#050503', bgB: '#201805', panelA: 'rgba(27, 21, 8, 0.96)', panelB: 'rgba(7, 7, 4, 0.96)', green: '#b5e86c', red: '#ff846b', logoOpacity: '0.19', logoFilter: 'saturate(0.72) brightness(1.05)' },
    { name: 'Green Screen', tier: 'free', accent: '#5ee787', text: '#dcffe5', muted: '#80b88f', bgA: '#010604', bgB: '#08180d', panelA: 'rgba(4, 19, 10, 0.96)', panelB: 'rgba(1, 7, 4, 0.96)', green: '#5ee787', red: '#ff6b78', logoOpacity: '0.13', logoFilter: 'hue-rotate(75deg) saturate(0.68)' },
    { name: 'Magenta Trace', tier: 'free', accent: '#ff85c2', text: '#ffe5f3', muted: '#c28aa9', bgA: '#08030a', bgB: '#22091a', panelA: 'rgba(30, 10, 24, 0.96)', panelB: 'rgba(7, 3, 8, 0.96)', green: '#94f7b4', red: '#ff85c2', logoOpacity: '0.15', logoFilter: 'hue-rotate(285deg) saturate(0.82)' },
    { name: 'Amber Wire', tier: 'free', accent: '#ffb547', text: '#ffe8bd', muted: '#bd9153', bgA: '#060503', bgB: '#211305', panelA: 'rgba(29, 17, 7, 0.96)', panelB: 'rgba(7, 5, 3, 0.96)', green: '#b9df6a', red: '#ff795e', logoOpacity: '0.19', logoFilter: 'sepia(0.25) saturate(0.84)' },
    { name: 'Cyan Relay', tier: 'free', accent: '#55d6ff', text: '#e1f8ff', muted: '#75aabb', bgA: '#020608', bgB: '#061724', panelA: 'rgba(5, 21, 31, 0.96)', panelB: 'rgba(2, 7, 9, 0.96)', green: '#89efba', red: '#ff7186', logoOpacity: '0.14', logoFilter: 'hue-rotate(175deg) saturate(0.68)' },
    { name: 'White Gold', tier: 'free', accent: '#fff0b8', text: '#fff7dd', muted: '#bfb38d', bgA: '#060504', bgB: '#17130b', panelA: 'rgba(20, 18, 12, 0.96)', panelB: 'rgba(7, 6, 5, 0.96)', green: '#b4e788', red: '#ff8b78', logoOpacity: '0.17', logoFilter: 'saturate(0.45) brightness(1.14)' },
    { name: 'Blue Steel', tier: 'free', accent: '#86a8ff', text: '#e4eaff', muted: '#8f9bc0', bgA: '#03050a', bgB: '#0b1024', panelA: 'rgba(10, 15, 30, 0.96)', panelB: 'rgba(3, 5, 10, 0.96)', green: '#93e7c4', red: '#ff7f92', logoOpacity: '0.15', logoFilter: 'hue-rotate(210deg) saturate(0.62)' },
    { name: 'Ruby Kernel', tier: 'free', accent: '#ff6f91', text: '#ffe1e8', muted: '#c28695', bgA: '#080305', bgB: '#230712', panelA: 'rgba(31, 8, 17, 0.96)', panelB: 'rgba(8, 3, 5, 0.96)', green: '#a7ef82', red: '#ff6f91', logoOpacity: '0.15', logoFilter: 'hue-rotate(305deg) saturate(0.8)' },
    { name: 'Lime Crown', tier: 'free', accent: '#c5f96b', text: '#f0ffd1', muted: '#a6c47b', bgA: '#050704', bgB: '#131e07', panelA: 'rgba(17, 26, 9, 0.96)', panelB: 'rgba(5, 7, 4, 0.96)', green: '#c5f96b', red: '#ff7d72', logoOpacity: '0.15', logoFilter: 'hue-rotate(50deg) saturate(0.7)' },
    { name: 'Graphite Gold', tier: 'free', accent: '#d6aa52', text: '#ead7ad', muted: '#a19172', bgA: '#040404', bgB: '#14120e', panelA: 'rgba(18, 17, 14, 0.96)', panelB: 'rgba(5, 5, 5, 0.96)', green: '#9ed385', red: '#e87d66', logoOpacity: '0.18', logoFilter: 'grayscale(0.32) sepia(0.18)' },
    { name: 'Aurora CLI', tier: 'free', accent: '#98ffcf', text: '#e4fff4', muted: '#8ebaa9', bgA: '#020705', bgB: '#071b18', panelA: 'rgba(6, 23, 20, 0.96)', panelB: 'rgba(2, 8, 6, 0.96)', green: '#98ffcf', red: '#ff7897', logoOpacity: '0.14', logoFilter: 'hue-rotate(120deg) saturate(0.72)' },
    { name: 'Deep Crown', tier: 'free', accent: '#b48cff', text: '#eadfff', muted: '#9d8abf', bgA: '#06040c', bgB: '#130822', panelA: 'rgba(18, 10, 30, 0.96)', panelB: 'rgba(6, 4, 11, 0.96)', green: '#9ef0b3', red: '#ff7b9e', logoOpacity: '0.16', logoFilter: 'hue-rotate(250deg) saturate(0.7)' },
    { name: 'Classic Terminal', tier: 'free', accent: '#f0b232', text: '#f6d590', muted: '#a98038', bgA: '#040403', bgB: '#120b03', panelA: 'rgba(16, 11, 5, 0.96)', panelB: 'rgba(5, 5, 4, 0.96)', green: '#8ed35f', red: '#ef6b5a', logoOpacity: '0.2', logoFilter: 'saturate(0.75)' },
    { name: 'Premium Obsidian', tier: 'premium', accent: '#ffd166', text: '#fff2ce', muted: '#bca66d', bgA: '#020202', bgB: '#15100a', panelA: 'rgba(17, 16, 14, 0.98)', panelB: 'rgba(2, 2, 2, 0.98)', green: '#9dffac', red: '#ff6e6e', logoOpacity: '0.24', logoFilter: 'contrast(1.18) saturate(0.58)' },
    { name: 'Premium Alchemy', tier: 'premium', accent: '#b7ff6a', text: '#efffd3', muted: '#a3bd75', bgA: '#030604', bgB: '#1a2006', panelA: 'rgba(22, 27, 8, 0.98)', panelB: 'rgba(3, 6, 4, 0.98)', green: '#b7ff6a', red: '#ff7979', logoOpacity: '0.2', logoFilter: 'hue-rotate(48deg) saturate(0.88) contrast(1.12)' },
    { name: 'Premium Sapphire', tier: 'premium', accent: '#73c2ff', text: '#e2f2ff', muted: '#82a9c7', bgA: '#01040a', bgB: '#071735', panelA: 'rgba(6, 19, 40, 0.98)', panelB: 'rgba(1, 4, 10, 0.98)', green: '#91f1c8', red: '#ff748f', logoOpacity: '0.19', logoFilter: 'hue-rotate(190deg) saturate(0.82) contrast(1.14)' },
    { name: 'Premium Plasma', tier: 'premium', accent: '#ff73d2', text: '#ffe3f7', muted: '#c184ae', bgA: '#07020a', bgB: '#250627', panelA: 'rgba(33, 7, 34, 0.98)', panelB: 'rgba(7, 2, 10, 0.98)', green: '#91f6b5', red: '#ff73d2', logoOpacity: '0.19', logoFilter: 'hue-rotate(285deg) saturate(1) contrast(1.1)' },
    { name: 'Premium Crownfire', tier: 'premium', accent: '#ff9f40', text: '#ffe0bf', muted: '#bd8654', bgA: '#070302', bgB: '#271006', panelA: 'rgba(35, 14, 6, 0.98)', panelB: 'rgba(7, 3, 2, 0.98)', green: '#b4ed76', red: '#ff6f55', logoOpacity: '0.22', logoFilter: 'sepia(0.3) saturate(1.05) contrast(1.12)' },
    { name: 'Premium Hypergreen', tier: 'premium', accent: '#78ff9d', text: '#ddffe6', muted: '#84bd91', bgA: '#010604', bgB: '#06240d', panelA: 'rgba(5, 31, 12, 0.98)', panelB: 'rgba(1, 6, 4, 0.98)', green: '#78ff9d', red: '#ff7180', logoOpacity: '0.18', logoFilter: 'hue-rotate(78deg) saturate(0.92) contrast(1.1)' },
    { name: 'Premium Moonlit', tier: 'premium', accent: '#d8c9ff', text: '#f2eeff', muted: '#aaa0c2', bgA: '#04050b', bgB: '#111324', panelA: 'rgba(16, 18, 31, 0.98)', panelB: 'rgba(4, 5, 11, 0.98)', green: '#a0efc8', red: '#ff859c', logoOpacity: '0.2', logoFilter: 'hue-rotate(220deg) saturate(0.48) brightness(1.12)' },
    { name: 'Premium Signal', tier: 'premium', accent: '#ff7676', text: '#ffe3e3', muted: '#c58a8a', bgA: '#080303', bgB: '#240909', panelA: 'rgba(33, 10, 10, 0.98)', panelB: 'rgba(8, 3, 3, 0.98)', green: '#a7ee83', red: '#ff7676', logoOpacity: '0.18', logoFilter: 'hue-rotate(325deg) saturate(0.92) contrast(1.12)' },
    { name: 'Premium Deepwave', tier: 'premium', accent: '#65f4ff', text: '#ddfdff', muted: '#80bdc2', bgA: '#010607', bgB: '#06252a', panelA: 'rgba(5, 32, 36, 0.98)', panelB: 'rgba(1, 6, 7, 0.98)', green: '#91efb9', red: '#ff758d', logoOpacity: '0.18', logoFilter: 'hue-rotate(168deg) saturate(0.9) contrast(1.1)' },
    { name: 'Premium Monarch', tier: 'premium', accent: '#f7c948', text: '#fff1b6', muted: '#bda24d', bgA: '#050403', bgB: '#211804', panelA: 'rgba(29, 21, 6, 0.98)', panelB: 'rgba(5, 4, 3, 0.98)', green: '#aee676', red: '#ff7b61', logoOpacity: '0.24', logoFilter: 'saturate(0.95) contrast(1.18)' }
  ]
};

const COMMAND_OPTION_SCHEMAS = {
  '/audio': ['audioProvider', 'file'],
  '/music': ['audioProvider', 'file'],
  '/master': ['audioProvider', 'file'],
  '/mix': ['audioProvider', 'file'],
  '/beat': ['audioProvider'],
  '/beat enhancer': ['audioProvider', 'file'],
  '/model': ['provider', 'model'],
  '/provider': ['provider'],
  '/sessions': ['session'],
  '/new': [],
  '/create agent': ['model'],
  '/agent': ['agent'],
  '/edit agent': ['agent'],
  '/brainstorm': ['brainstormMode', 'agent'],
  '/beehive': ['agentGroup'],
  '/theme': ['theme'],
  '/mcp': ['mcp'],
  '/browser': ['searchProvider'],
  '/code': ['runtime', 'file'],
  '/analyze': ['file'],
  '/diagram': ['diagramType'],
  '/write': ['writingType'],
  '/summarize': ['summaryLength', 'file'],
  '/translate': ['language', 'file'],
  '/search': ['searchProvider'],
  '/humanize': ['tone'],
  '/10x': ['expansionMode'],
  '/memory': ['memoryScope'],
  '/schedule': ['scheduleCadence'],
  '/task': ['taskPriority'],
  '/voice': ['audioProvider'],
  '/image': ['provider', 'model', 'file'],
  '/upload': ['file'],
  '/video': ['provider', 'model', 'file'],
  '/settings': ['settingsSection'],
  '/help': []
};

const STATIC_OPTIONS = {
  brainstormMode: ['Product ideas', 'Architecture', 'Naming', 'Debugging', 'Launch plan'],
  diagramType: ['Flowchart', 'Architecture', 'Sequence', 'State machine', 'Mind map'],
  writingType: ['Email', 'Document', 'Prompt', 'Script', 'Release notes'],
  summaryLength: ['Short', 'Medium', 'Detailed'],
  language: ['Spanish', 'French', 'German', 'Japanese', 'Chinese', 'Korean'],
  tone: ['Natural', 'Friendly', 'Direct', 'Formal', 'Punchy'],
  expansionMode: ['More detail', 'More examples', 'More polish', 'More options'],
  memoryScope: ['Session', 'Agent', 'Project', 'Long-term'],
  scheduleCadence: ['One time', 'Daily', 'Weekly', 'Monthly'],
  taskPriority: ['Low', 'Normal', 'High', 'Urgent'],
  runtime: ['Node.js', 'Python', 'PowerShell', 'Browser'],
  settingsSection: ['Account', 'Providers', 'Audio', 'Search', 'MCPs', 'Storage']
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function option(value, label, selected = false) {
  return `<option value="${escapeHtml(value)}" ${selected ? 'selected' : ''}>${escapeHtml(label)}</option>`;
}

function loadState() {
  state.sessions = [];
  state.agents = [];
  state.files = [];
  state.selectedProvider = '';
  state.selectedModel = '';
  state.selectedSessionId = '';
  state.activeAgent = '';
}

function saveState() {
  // Transient UI state intentionally stays in memory so setup/provider changes are never stale after reload.
}

function appendMessage(author, text, type = 'assistant') {
  const article = document.createElement('article');
  article.className = `message ${type}`;
  article.innerHTML = `<strong>${escapeHtml(author)}</strong><p>${escapeHtml(text)}</p>`;
  $('#chatLog').append(article);
  $('#chatLog').scrollTop = $('#chatLog').scrollHeight;
}

function flashElement(element) {
  if (!element) return;
  element.classList.remove('attention');
  void element.offsetWidth;
  element.classList.add('attention');
  element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function formatUptime(startedAt) {
  const total = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function configuredProviders() {
  const settings = state.boot.settings || {};
  const providers = settings.providers || [];
  const custom = (settings.customProviders || []).map((provider) => provider.name).filter(Boolean);
  return [...providers, ...custom];
}

function modelOptions() {
  if (!state.selectedProvider) return [];
  return state.modelCatalog[state.selectedProvider] || [];
}

function audioProviders() {
  return state.boot.settings?.audioProviders || [];
}

function commandName(raw) {
  const text = raw.trim().toLowerCase();
  if (text.startsWith('/beat enhancer')) return '/beat enhancer';
  if (text.startsWith('/create agent')) return '/create agent';
  if (text.startsWith('/edit agent')) return '/edit agent';
  return text.split(/\s+/)[0] || '';
}

function renderCommands() {
  const commands = state.boot.commands.filter(([, , category]) => {
    return state.activeCommandFilter === 'all' || category === state.activeCommandFilter;
  });
  const allOptions = state.boot.commands.map(([command, description, category]) => option(command, `${command} - ${description} (${category})`)).join('');

  $('#commandList').innerHTML = commands.map(([command, description, category]) => `
    <div class="command-row" data-command="${escapeHtml(command)}">
      <strong>${escapeHtml(command)}</strong>
      <span>${escapeHtml(description)} - ${escapeHtml(category)}</span>
    </div>
  `).join('');
  $('#commandSelect').innerHTML = allOptions;
  $('#sideCommandSelect').innerHTML = allOptions;
  $('#commandCount').textContent = state.boot.commands.length;
}

function renderDropdowns() {
  const providers = configuredProviders();
  const models = modelOptions();
  const sessions = state.sessions;
  const agents = state.agents;

  $('#providerSelect').innerHTML = option('', 'No provider selected', !state.selectedProvider) + providers.map((provider) => option(provider, provider, provider === state.selectedProvider)).join('');
  $('#modelSelect').innerHTML = option('', 'No model selected', !state.selectedModel) + models.map((model) => option(model, model, model === state.selectedModel)).join('');
  $('#modelSelect').disabled = !state.selectedProvider;
  if (state.selectedProvider && !models.length) {
    const reason = state.modelErrors[state.selectedProvider] || 'Select provider to load models.';
    $('#modelSelect').innerHTML = option('', reason, true);
  }
  $('#sessionSelect').innerHTML = option('', 'No active session', !state.selectedSessionId) + sessions.map((session) => option(session.id, `${session.name} / ${session.id}`, session.id === state.selectedSessionId)).join('');
  $('#agentSelect').innerHTML = option('', 'No active agent', !state.activeAgent) + agents.map((agent) => option(agent.id, `${agent.name} - ${agent.model || 'No model'}`, agent.id === state.activeAgent)).join('');
  $('#themeSelect').innerHTML = option('', 'Theme picker') + state.themes.map((theme) => option(theme.name, `${theme.name} (${theme.tier})`)).join('');

  $('#providerName').textContent = state.selectedProvider || 'No provider selected';
  $('#modelVendor').textContent = state.selectedProvider ? `by ${state.selectedProvider}` : 'No provider selected';
  $('#currentModel').textContent = state.selectedModel || 'No model selected';
  $('#modelName').textContent = state.selectedModel || 'No model selected';
  $('#modelMeter').style.width = state.selectedModel ? '100%' : '0%';
  $('#sessionName').textContent = state.selectedSessionId ? `Session / ${state.selectedSessionId}` : 'No active session';
}

function renderIntegrations() {
  $('#integrationGrid').innerHTML = state.boot.integrations.map(([name, status]) => `
    <div class="mcp-card ${escapeHtml(status)}">
      <i></i>
      <strong>${escapeHtml(name)}</strong>
      <span>${escapeHtml(status)}</span>
    </div>
  `).join('');
}

function renderAgents() {
  if (!state.agents.length) {
    $('#agentList').innerHTML = '<div class="agent-card idle"><i></i><div><strong>No agents</strong><span>Create one after selecting a model.</span></div></div>';
    renderDropdowns();
    return;
  }

  $('#agentList').innerHTML = state.agents.map((agent) => `
    <div class="agent-card ${agent.id === state.activeAgent ? 'active' : 'idle'}">
      <i></i>
      <div>
        <strong>${escapeHtml(agent.name)}</strong>
        <span>${escapeHtml(agent.model || 'No model')}</span>
      </div>
      <button data-agent-switch="${escapeHtml(agent.id)}">${agent.id === state.activeAgent ? 'Active' : 'Use'}</button>
    </div>
  `).join('');
  renderDropdowns();
}

function renderFiles() {
  if (!state.files.length) {
    $('#fileQueue').innerHTML = '<span>No files queued</span>';
    return;
  }
  $('#fileQueue').innerHTML = state.files.map((file) => `
    <div class="file-row">
      <strong>${escapeHtml(file.name)}</strong>
      <span>${escapeHtml(file.kind)}</span>
    </div>
  `).join('');
}

function optionsFor(kind) {
  if (kind === 'provider') return configuredProviders();
  if (kind === 'model') return modelOptions();
  if (kind === 'session') return state.sessions.map((session) => `${session.name} / ${session.id}`);
  if (kind === 'agent') return state.agents.map((agent) => `${agent.name} / ${agent.id}`);
  if (kind === 'agentGroup') return state.agents.map((agent) => `${agent.name} / ${agent.id}`);
  if (kind === 'audioProvider') return audioProviders();
  if (kind === 'mcp') return state.boot.integrations.map(([name, status]) => `${name} / ${status}`);
  if (kind === 'theme') return state.themes.map((theme) => `${theme.name} / ${theme.tier}`);
  if (kind === 'file') return state.files.map((file) => `${file.name} / ${file.kind}`);
  if (kind === 'searchProvider') return state.boot.searchProviders || [state.boot.settings?.searchProvider || 'DuckDuckGo'].filter(Boolean);
  return STATIC_OPTIONS[kind] || [];
}

function labelFor(kind) {
  return kind.replace(/([A-Z])/g, ' $1').toLowerCase();
}

function selectedValueForKind(kind) {
  if (kind === 'provider') return state.selectedProvider;
  if (kind === 'model') return state.selectedModel;
  if (kind === 'searchProvider') return state.boot.settings?.searchProvider || '';
  return '';
}

function commandControlMarkup(kind) {
  const opts = optionsFor(kind);
  const selectedValue = selectedValueForKind(kind);
  const disabled = opts.length ? '' : 'disabled';
  const empty = opts.length ? option('', `Choose ${labelFor(kind)}`, !selectedValue) : option('', `No ${labelFor(kind)} available`, true);
  return `
    <label>
      <span>${escapeHtml(labelFor(kind))}</span>
      <select data-option-kind="${escapeHtml(kind)}" ${disabled}>
        ${empty}
        ${opts.map((item) => option(item, item, item === selectedValue)).join('')}
      </select>
    </label>
  `;
}

function showCommandOptions(command) {
  const base = commandName(command);
  const schema = COMMAND_OPTION_SCHEMAS[base] || [];
  state.activeCommand = base;
  $('#commandOptionsTitle').textContent = schema.length ? `${base} needs ${schema.map(labelFor).join(', ')}.` : `${base || 'Command'} has no dropdown options.`;
  $('#applyCommandOptions').disabled = !base;
  $('#commandOptions').innerHTML = schema.map(commandControlMarkup).join('');
  renderTypedCommandDropdown(base, schema);
}

function refreshVisibleCommandOptions() {
  if (state.activeCommand) {
    showCommandOptions(state.activeCommand);
  }
}

function renderTypedCommandDropdown(base, schema) {
  const dropdown = $('#typedCommandDropdown');
  if (!base || !base.startsWith('/')) {
    dropdown.hidden = true;
    $('#typedCommandControls').innerHTML = '';
    return;
  }

  dropdown.hidden = false;
  $('#typedCommandTitle').textContent = `${base} options`;
  $('#typedCommandHelp').textContent = schema.length
    ? `Choose ${schema.map(labelFor).join(', ')} for ${base}.`
    : `${base} has no extra dropdown options.`;
  $('#typedCommandControls').innerHTML = schema.map(commandControlMarkup).join('');
}

function syncTypedCommandDropdown(inputValue) {
  const value = inputValue.trim();
  if (!value.startsWith('/')) {
    $('#typedCommandDropdown').hidden = true;
    return;
  }

  const base = commandName(value);
  if (!COMMAND_OPTION_SCHEMAS[base]) {
    $('#typedCommandDropdown').hidden = true;
    return;
  }

  showCommandOptions(base);
}

function setPermission(text, onApprove) {
  state.pendingPermission = onApprove;
  $('#permissionText').textContent = text;
  $('#approveButton').disabled = false;
  $('#denyButton').disabled = false;
}

function clearPermission(text = 'No pending approvals.') {
  state.pendingPermission = null;
  $('#permissionText').textContent = text;
  $('#approveButton').disabled = true;
  $('#denyButton').disabled = true;
}

function classifyFile(file) {
  if (file.type.startsWith('image/')) return 'image';
  if (file.type.startsWith('audio/')) return 'audio';
  if (file.type.startsWith('video/')) return 'video';
  return 'document';
}

function createSession() {
  const id = Math.random().toString(16).slice(2, 10);
  const session = { id, name: `Session ${state.sessions.length + 1}`, createdAt: new Date().toISOString() };
  state.sessions.unshift(session);
  state.selectedSessionId = id;
  saveState();
  renderDropdowns();
  appendMessage('Valeroy', `Created local session ${id}.`);
}

function createAgent() {
  if (!state.selectedModel) {
    appendMessage('Valeroy', 'Select a provider and model before creating an agent.');
    showCommandOptions('/create agent');
    return;
  }
  const id = Math.random().toString(16).slice(2, 10);
  const agent = { id, name: `Agent ${state.agents.length + 1}`, model: state.selectedModel, createdAt: new Date().toISOString() };
  state.agents.push(agent);
  state.activeAgent = id;
  saveState();
  renderAgents();
  appendMessage('Valeroy', `Created ${agent.name} with ${state.selectedModel}.`);
}

function applyCommandOptions() {
  const command = state.activeCommand;
  if (!command) return;

  if (command === '/new') {
    createSession();
    return;
  }
  if (command === '/help') {
    appendMessage('Valeroy', 'Choose or type a slash command. If the command needs choices, its dropdowns appear above the chatbox and in Command Options.');
    return;
  }
  if (command === '/clear') {
    $('#chatLog').innerHTML = '';
    appendMessage('Valeroy', 'Conversation cleared.');
    syncTypedCommandDropdown('');
    return;
  }
  if (command === '/create agent') {
    createAgent();
    return;
  }

  const optionRoot = $('#typedCommandDropdown').hidden ? $('#commandOptions') : $('#typedCommandControls');
  const selected = [...optionRoot.querySelectorAll('[data-option-kind]')].map((select) => ({
    kind: select.dataset.optionKind,
    value: select.value
  })).filter((item) => item.value);

  if (command === '/provider') {
    const provider = selected.find((item) => item.kind === 'provider')?.value;
    if (provider) setProvider(provider);
  }
  if (command === '/model') {
    const provider = selected.find((item) => item.kind === 'provider')?.value;
    const model = selected.find((item) => item.kind === 'model')?.value;
    if (provider) setProvider(provider);
    if (model) setModel(model);
  }
  if (command === '/sessions') {
    const session = selected.find((item) => item.kind === 'session')?.value;
    const id = session?.split('/').pop()?.trim();
    if (id) state.selectedSessionId = id;
  }
  if (command === '/agent' || command === '/edit agent') {
    const agent = selected.find((item) => item.kind === 'agent')?.value;
    const id = agent?.split('/').pop()?.trim();
    if (id) state.activeAgent = id;
  }
  if (command === '/theme') {
    const theme = selected.find((item) => item.kind === 'theme')?.value;
    const themeName = theme?.split('/')[0]?.trim();
    if (themeName) applyTheme(themeName);
  }
  if (command === '/mcp') {
    const mcp = selected.find((item) => item.kind === 'mcp')?.value;
    appendMessage('Valeroy', mcp ? `Selected MCP: ${mcp}. Connection flow is ready for provider-specific wiring.` : 'Choose an MCP first.');
  }
  if (command === '/settings') {
    const section = selected.find((item) => item.kind === 'settingsSection')?.value;
    appendMessage('Valeroy', section ? `Settings section selected: ${section}.` : `Settings file: ${state.boot.storage.settingsPath}`);
  }

  saveState();
  renderAgents();
  renderDropdowns();
  if (!['/mcp', '/settings'].includes(command)) {
    appendMessage('Valeroy', selected.length ? `${command} options applied.` : `${command} has no selected options to apply.`);
  }
}

function setProvider(provider) {
  state.selectedProvider = provider;
  state.selectedModel = '';
  saveState();
  renderDropdowns();
  loadModelsForProvider(provider);
}

function setModel(model) {
  state.selectedModel = model;
  saveState();
  renderDropdowns();
}

function hexToRgba(hex, alpha) {
  const clean = hex.replace('#', '');
  const value = parseInt(clean, 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function applyTheme(themeName) {
  const theme = state.themes.find((item) => item.name === themeName);
  if (!theme) return;
  const root = document.documentElement;
  root.style.setProperty('--gold', theme.accent);
  root.style.setProperty('--text', theme.text);
  root.style.setProperty('--muted', theme.muted);
  root.style.setProperty('--green', theme.green);
  root.style.setProperty('--red', theme.red);
  root.style.setProperty('--bg-a', theme.bgA);
  root.style.setProperty('--bg-b', theme.bgB);
  root.style.setProperty('--panel-a', theme.panelA);
  root.style.setProperty('--panel-b', theme.panelB);
  root.style.setProperty('--panel-border', theme.accent);
  root.style.setProperty('--grid-color', hexToRgba(theme.accent, 0.09));
  root.style.setProperty('--grid-color-2', hexToRgba(theme.accent, 0.07));
  root.style.setProperty('--logo-opacity', theme.logoOpacity);
  root.style.setProperty('--logo-filter', theme.logoFilter);
  root.style.setProperty('--glow', hexToRgba(theme.accent, 0.16));
  appendMessage('Valeroy', `Theme applied: ${theme.name} (${theme.tier}).`);
}

async function loadModelsForProvider(provider) {
  if (!provider) return;
  state.modelErrors[provider] = 'Loading models...';
  renderDropdowns();
  const result = await window.valeroy.listProviderModels(provider);
  state.modelCatalog[provider] = result.models || [];
  state.modelErrors[provider] = result.error || (result.models?.length ? '' : 'No models returned by provider.');
  if (!state.modelCatalog[provider].includes(state.selectedModel)) {
    state.selectedModel = '';
  }
  saveState();
  renderDropdowns();
  refreshVisibleCommandOptions();
}

function runCommand(raw) {
  const command = raw.trim();
  if (!command) return;
  appendMessage('You', command, 'user');

  if (!command.startsWith('/')) {
    appendMessage('Valeroy', 'No model is running. Select a provider and model before sending free-form prompts.');
    return;
  }

  const base = commandName(command);
  showCommandOptions(base);

  if (base === '/help') {
    appendMessage('Valeroy', 'Choose a command from the dropdown or type one. Commands that need choices will show dropdowns in Command Options.');
    return;
  }

  if (base === '/clear') {
    $('#chatLog').innerHTML = '';
    appendMessage('Valeroy', 'Conversation cleared.');
    syncTypedCommandDropdown('');
    return;
  }

  if (base === '/new') {
    createSession();
    return;
  }

  if (base === '/beehive') {
    setPermission('Activate every local agent for this project?', () => {
      appendMessage('Valeroy', state.agents.length ? `${state.agents.length} agent(s) activated for collaboration.` : 'No agents exist yet. Create agents before using /beehive.');
    });
    return;
  }

  appendMessage('Valeroy', `${base} selected. Use the Command Options dropdowns, then Apply.`);
}

function handleRailTab(tab) {
  $$('[data-tab]').forEach((button) => button.classList.toggle('active', button.dataset.tab === tab));
  const targets = {
    chat: '#chatTab',
    agents: '#agentsPanel',
    mcps: '#mcpsPanel',
    files: '#filesPanel',
    settings: '#commandOptionsPanel'
  };
  const target = $(targets[tab]);
  flashElement(target);

  if (tab === 'settings') {
    runCommand('/settings');
  } else if (tab === 'mcps') {
    showCommandOptions('/mcp');
    appendMessage('Valeroy', 'MCP panel focused.');
  } else if (tab === 'agents') {
    showCommandOptions('/agent');
    appendMessage('Valeroy', 'Agent panel focused.');
  } else if (tab === 'files') {
    showCommandOptions('/upload');
    appendMessage('Valeroy', 'File queue focused. Drop files anywhere in the app.');
  } else {
    appendMessage('Valeroy', 'Chat panel focused.');
  }
}

function setupInteractions() {
  $('#composer').addEventListener('submit', (event) => {
    event.preventDefault();
    const input = $('#messageInput');
    runCommand(input.value);
    input.value = '';
    syncTypedCommandDropdown('');
  });

  $('#messageInput').addEventListener('input', (event) => {
    syncTypedCommandDropdown(event.target.value);
  });

  $('#commandPalette').addEventListener('submit', (event) => {
    event.preventDefault();
    runCommand($('#commandSelect').value);
  });

  $('#sideCommandSelect').addEventListener('change', (event) => {
    $('#messageInput').value = event.target.value;
    showCommandOptions(event.target.value);
    $('#messageInput').focus();
  });

  $('#applyCommandOptions').addEventListener('click', applyCommandOptions);
  $('#typedApplyCommandOptions').addEventListener('click', applyCommandOptions);
  $('#storageButton').addEventListener('click', () => window.valeroy.revealStorage());
  $('#manageMcps').addEventListener('click', () => runCommand('/mcp'));
  $('#modelButton').addEventListener('click', () => runCommand('/model'));

  $('#providerSelect').addEventListener('change', (event) => setProvider(event.target.value));
  $('#modelSelect').addEventListener('change', (event) => setModel(event.target.value));
  $('#sessionSelect').addEventListener('change', (event) => {
    state.selectedSessionId = event.target.value;
    saveState();
    renderDropdowns();
  });
  $('#agentSelect').addEventListener('change', (event) => {
    state.activeAgent = event.target.value;
    saveState();
    renderAgents();
  });
  $('#themeSelect').addEventListener('change', (event) => {
    if (event.target.value) applyTheme(event.target.value);
  });

  document.addEventListener('change', (event) => {
    const optionSelect = event.target.closest('[data-option-kind]');
    if (!optionSelect) return;
    if (optionSelect.dataset.optionKind === 'provider' && optionSelect.value) {
      state.selectedProvider = optionSelect.value;
      state.selectedModel = '';
      saveState();
      renderDropdowns();
      loadModelsForProvider(optionSelect.value);
    }
  });

  document.addEventListener('click', (event) => {
    const tabButton = event.target.closest('[data-tab]');
    if (tabButton) {
      handleRailTab(tabButton.dataset.tab);
      return;
    }

    const commandButton = event.target.closest('[data-command]');
    if (commandButton) {
      runCommand(commandButton.dataset.command);
      return;
    }
    const commandRow = event.target.closest('.command-row');
    if (commandRow) {
      $('#messageInput').value = commandRow.dataset.command;
      showCommandOptions(commandRow.dataset.command);
      return;
    }
    const filterButton = event.target.closest('[data-command-filter]');
    if (filterButton) {
      state.activeCommandFilter = filterButton.dataset.commandFilter;
      $$('[data-command-filter]').forEach((button) => button.classList.toggle('active', button === filterButton));
      renderCommands();
      return;
    }
    const agentButton = event.target.closest('[data-agent-switch]');
    if (agentButton) {
      state.activeAgent = agentButton.dataset.agentSwitch;
      saveState();
      renderAgents();
    }
  });

  $('#approveButton').addEventListener('click', () => {
    const action = state.pendingPermission;
    clearPermission('Approved.');
    if (action) action();
  });
  $('#denyButton').addEventListener('click', () => clearPermission('Denied.'));

  window.addEventListener('dragover', (event) => {
    event.preventDefault();
    document.body.classList.add('dragging');
  });
  window.addEventListener('dragleave', () => document.body.classList.remove('dragging'));
  window.addEventListener('drop', (event) => {
    event.preventDefault();
    document.body.classList.remove('dragging');
    const files = [...event.dataTransfer.files].map((file) => ({ name: file.name, kind: classifyFile(file) }));
    state.files.push(...files);
    saveState();
    renderFiles();
    appendMessage('Valeroy', `Queued ${files.length} file(s).`);
  });
}

function startAnimation() {
  const bars = $('#bars');
  const columns = 20;
  const rows = 11;
  for (let y = 0; y < rows; y += 1) {
    for (let x = 0; x < columns; x += 1) {
      const bar = document.createElement('span');
      bar.className = 'bar';
      bar.style.left = `${(x / columns) * 100}%`;
      bar.style.top = `${(y / rows) * 100}%`;
      bar.style.width = `${100 / columns}%`;
      bar.style.height = `${100 / rows}%`;
      bar.style.transformOrigin = Math.random() > 0.5 ? 'top' : 'bottom';
      bar.style.animationDelay = `${Math.random() * 900}ms`;
      bars.append(bar);
    }
  }
  setTimeout(() => $('#startup').classList.add('done'), 2200);
}

function startClock() {
  const tick = () => {
    const now = new Date();
    $('#clock').textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    $('#uptime').textContent = formatUptime(state.boot.gatewayStartedAt);
  };
  tick();
  setInterval(tick, 1000);
}

async function init() {
  state.boot = await window.valeroy.getBootstrap();
  loadState();
  const settings = state.boot.settings || {};
  const gatewayUrl = `127.0.0.1:${state.boot.gatewayPort}`;

  if (!configuredProviders().includes(state.selectedProvider)) {
    state.selectedProvider = '';
    state.selectedModel = '';
  }

  $('#gatewayUrl').textContent = gatewayUrl;
  $('#gatewayPill').textContent = `Gateway online at ${gatewayUrl}`;
  $('#profileUser').textContent = `${settings.username || 'you'}@valeroy.ai`;
  $('#searchProvider').textContent = settings.searchProvider || 'DuckDuckGo';
  $('#readinessText').textContent = settings.setupComplete
    ? 'Setup complete. No model is running until the user selects one.'
    : 'Run "valeroy setup" in the terminal to connect providers.';

  $('#tokenCount').textContent = '0';
  renderCommands();
  renderDropdowns();
  if (state.selectedProvider) {
    loadModelsForProvider(state.selectedProvider);
  }
  renderIntegrations();
  renderAgents();
  renderFiles();
  showCommandOptions('');
  setupInteractions();
  startClock();
  startAnimation();
}

init();

const { app, BrowserWindow, ipcMain, shell } = require('electron');
const http = require('http');
const path = require('path');
const fs = require('fs');
const os = require('os');

const GATEWAY_PORT = Number(process.env.VALEROY_GATEWAY_PORT || 17637);

let mainWindow;
let gatewayServer;
const gatewayStartedAt = Date.now();

function ensureValeroyStorage() {
  const baseDir = path.join(app.getPath('userData'), 'valeroy-data');
  const dirs = {
    baseDir,
    agentsDir: path.join(baseDir, 'agents'),
    filesDir: path.join(baseDir, 'files'),
    sessionsDir: path.join(baseDir, 'sessions'),
    settingsDir: path.join(baseDir, 'settings')
  };

  for (const dir of Object.values(dirs)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  const settingsPath = path.join(dirs.settingsDir, 'settings.json');
  if (!fs.existsSync(settingsPath)) {
    fs.writeFileSync(settingsPath, JSON.stringify({
      version: '1.0.0',
      createdAt: new Date().toISOString(),
      username: null,
      account: null,
      providers: [],
      customProviders: [],
      audioProviders: [],
      searchProvider: null,
      searchProviderKey: '',
      appModificationEnabled: false
    }, null, 2));
  }

  return { ...dirs, settingsPath };
}

function readSettings(storage) {
  try {
    return JSON.parse(fs.readFileSync(storage.settingsPath, 'utf8'));
  } catch {
    return {};
  }
}

function startGateway(storage) {
  return new Promise((resolve) => {
    gatewayServer = http.createServer((req, res) => {
      res.setHeader('Access-Control-Allow-Origin', 'app://valeroy');
      res.setHeader('Content-Type', 'application/json; charset=utf-8');

      if (req.url === '/health') {
        res.end(JSON.stringify({
          status: 'online',
          version: app.getVersion(),
          uptimeSeconds: Math.round((Date.now() - gatewayStartedAt) / 1000),
          storage: storage.baseDir
        }));
        return;
      }

      if (req.url === '/commands') {
        res.end(JSON.stringify({ commands: VALEROY_COMMANDS }));
        return;
      }

      if (req.url === '/settings') {
        res.end(JSON.stringify(readSettings(storage)));
        return;
      }

      if (req.url === '/integrations') {
        res.end(JSON.stringify({ integrations: getIntegrations(readSettings(storage)) }));
        return;
      }

      res.statusCode = 404;
      res.end(JSON.stringify({ error: 'Not found' }));
    });

    gatewayServer.on('error', () => resolve(false));
    gatewayServer.listen(GATEWAY_PORT, '127.0.0.1', () => resolve(true));
  });
}

function createWindow(storage, gatewayOnline) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1040,
    minHeight: 720,
    title: 'Valeroy AI',
    backgroundColor: '#060605',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'), {
    query: {
      gateway: gatewayOnline ? 'online' : 'offline'
    }
  });
}

ipcMain.handle('valeroy:get-bootstrap', () => {
  const storage = ensureValeroyStorage();
  const settings = readSettings(storage);
  return {
    appVersion: app.getVersion(),
    gatewayPort: GATEWAY_PORT,
    gatewayStartedAt,
    storage,
    settings,
    commands: VALEROY_COMMANDS,
    providers: PROVIDERS,
    audioProviders: AUDIO_PROVIDERS,
    searchProviders: SEARCH_PROVIDERS,
    integrations: getIntegrations(settings),
    platform: process.platform,
    hostname: os.hostname()
  };
});

ipcMain.handle('valeroy:save-settings', (_, payload) => {
  const storage = ensureValeroyStorage();
  const settings = {
    ...readSettings(storage),
    ...payload,
    configuredAt: new Date().toISOString()
  };
  fs.writeFileSync(storage.settingsPath, JSON.stringify(settings, null, 2));
  return { ok: true, settingsPath: storage.settingsPath };
});

ipcMain.handle('valeroy:list-provider-models', async (_, providerName) => {
  const storage = ensureValeroyStorage();
  const settings = readSettings(storage);
  return listProviderModels(settings, providerName);
});

ipcMain.handle('valeroy:reveal-storage', () => {
  const storage = ensureValeroyStorage();
  shell.openPath(storage.baseDir);
  return storage.baseDir;
});

app.whenReady().then(async () => {
  const storage = ensureValeroyStorage();
  const gatewayOnline = await startGateway(storage);
  createWindow(storage, gatewayOnline);
});

app.on('window-all-closed', () => {
  if (gatewayServer) {
    gatewayServer.close();
  }
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    const storage = ensureValeroyStorage();
    createWindow(storage, true);
  }
});

const PROVIDERS = [
  'OpenRouter', 'OpenCode', 'Kilo', 'Novita', 'CostRouter', 'NagaAI', 'ModelsLab',
  'Anthropic', 'OpenAI', 'Grok', 'DeepSeek', 'Kimi', 'NVIDIA', 'Runway', 'Seedance',
  'Minimax', 'Google Gemini', 'Venice AI', 'Higgsfield', 'Perplexity'
];

const SEARCH_PROVIDERS = [
  'Perplexity', 'Google Gemini Search', 'Parallel', 'Parallel Free', 'Firecrawl',
  'DuckDuckGo', 'Brave'
];

const AUDIO_PROVIDERS = ['ElevenLabs', 'Deepgram', 'Suno'];

function getIntegrations(settings = {}) {
  const enabledAudio = new Set(settings.audioProviders || []);
  return BASE_INTEGRATIONS.map(([name, status]) => {
    if (AUDIO_PROVIDERS.includes(name) && enabledAudio.has(name)) {
      return [name, 'connected'];
    }
    return [name, status];
  });
}

async function listProviderModels(settings, providerName) {
  const providerKey = settings.providerKeys?.[providerName] || '';
  const customProvider = (settings.customProviders || []).find((provider) => provider.name === providerName);
  const apiKey = providerKey || customProvider?.apiKey || '';

  if (!apiKey) {
    return { providerName, models: [], error: 'No API key saved for this provider.' };
  }

  const adapter = MODEL_ADAPTERS[providerName];
  if (!adapter) {
    return { providerName, models: [], error: 'No model-list API adapter is available for this provider yet.' };
  }

  try {
    const models = await adapter(apiKey);
    return { providerName, models: [...new Set(models)].sort((a, b) => a.localeCompare(b)) };
  } catch (error) {
    return { providerName, models: [], error: error.message || String(error) };
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`Model request failed with HTTP ${response.status}`);
  }
  return response.json();
}

function parseOpenAiModels(payload) {
  return (payload.data || []).map((model) => model.id || model.name).filter(Boolean);
}

function openAiCompatibleModels(url, headerName = 'Authorization') {
  return async (apiKey) => {
    const headers = headerName === 'Authorization'
      ? { Authorization: `Bearer ${apiKey}` }
      : { [headerName]: apiKey };
    return parseOpenAiModels(await fetchJson(url, { headers }));
  };
}

const MODEL_ADAPTERS = {
  OpenAI: openAiCompatibleModels('https://api.openai.com/v1/models'),
  OpenRouter: openAiCompatibleModels('https://openrouter.ai/api/v1/models'),
  Anthropic: async (apiKey) => {
    const payload = await fetchJson('https://api.anthropic.com/v1/models', {
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01'
      }
    });
    return parseOpenAiModels(payload);
  },
  'Google Gemini': async (apiKey) => {
    const payload = await fetchJson(`https://generativelanguage.googleapis.com/v1beta/models?key=${encodeURIComponent(apiKey)}`);
    return (payload.models || []).map((model) => model.name?.replace(/^models\//, '')).filter(Boolean);
  },
  DeepSeek: openAiCompatibleModels('https://api.deepseek.com/models'),
  Grok: openAiCompatibleModels('https://api.x.ai/v1/models'),
  Kimi: openAiCompatibleModels('https://api.moonshot.ai/v1/models'),
  NVIDIA: openAiCompatibleModels('https://integrate.api.nvidia.com/v1/models'),
  Novita: openAiCompatibleModels('https://api.novita.ai/v3/openai/models'),
  Minimax: openAiCompatibleModels('https://api.minimax.chat/v1/models'),
  Perplexity: openAiCompatibleModels('https://api.perplexity.ai/models'),
  'Venice AI': openAiCompatibleModels('https://api.venice.ai/api/v1/models')
};

const BASE_INTEGRATIONS = [
  ['Figma', 'connected'], ['Canva', 'available'], ['Trello', 'available'],
  ['Google Workspace', 'connected'], ['Higgsfield', 'available'], ['Blender', 'available'],
  ['NotebookLM', 'available'], ['Google Antigravity', 'available'], ['Notion', 'connected'],
  ['Slack', 'available'], ['Discord', 'available'], ['GitHub', 'connected'],
  ['Linear', 'available'], ['Jira', 'available'], ['Asana', 'available'], ['Airtable', 'available'],
  ['Obsidian', 'available'], ['Dropbox', 'available'], ['OneDrive', 'connected'],
  ['ElevenLabs', 'locked'], ['Deepgram', 'locked'], ['Suno', 'locked'], ['Runway', 'available'],
  ['Perplexity', 'connected']
];

const VALEROY_COMMANDS = [
  ['/audio', 'Voice and audio workspace', 'audio'],
  ['/music', 'Generate, arrange, and revise music', 'audio'],
  ['/master', 'Master an audio track', 'audio'],
  ['/mix', 'Mix stems or full songs', 'audio'],
  ['/beat', 'Create a new beat', 'audio'],
  ['/beat enhancer', 'Enhance an existing beat', 'audio'],
  ['/model', 'Choose a model from enabled providers', 'core'],
  ['/provider', 'Choose an enabled API provider', 'core'],
  ['/sessions', 'Switch between existing sessions', 'core'],
  ['/new', 'Create a new agent session', 'core'],
  ['/create agent', 'Create an agent with the selected model', 'core'],
  ['/agent', 'Switch active agent', 'core'],
  ['/edit agent', 'Edit agent instructions and behavior', 'core'],
  ['/brainstorm', 'Ask the model to brainstorm', 'core'],
  ['/beehive', 'Run all agents on one project', 'core'],
  ['/theme', 'Open the theme picker', 'core'],
  ['/mcp', 'Manage connected app MCPs', 'core'],
  ['/browser', 'Browse the web', 'tools'],
  ['/code', 'Write and execute code', 'tools'],
  ['/analyze', 'Analyze data or files', 'tools'],
  ['/diagram', 'Generate diagrams', 'tools'],
  ['/write', 'Draft or revise writing', 'tools'],
  ['/summarize', 'Summarize content', 'tools'],
  ['/translate', 'Translate languages', 'tools'],
  ['/search', 'Search with the configured provider', 'tools'],
  ['/humanize', 'Rewrite AI text naturally', 'tools'],
  ['/10x', 'Expand or intensify output', 'tools'],
  ['/memory', 'Manage long-term memory', 'tools'],
  ['/schedule', 'Schedule tasks', 'tools'],
  ['/task', 'Create and track tasks', 'tools'],
  ['/voice', 'Voice input and output', 'tools'],
  ['/image', 'Generate or edit images', 'tools'],
  ['/upload', 'Upload and analyze files', 'tools'],
  ['/video', 'Generate or inspect video', 'tools'],
  ['/settings', 'Open settings', 'system'],
  ['/help', 'Show all commands', 'system']
];

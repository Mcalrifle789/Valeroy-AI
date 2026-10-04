#!/usr/bin/env node
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const readline = require('readline');

const PROVIDERS = [
  'OpenRouter', 'OpenCode', 'Kilo', 'Novita', 'CostRouter', 'NagaAI', 'ModelsLab',
  'Anthropic', 'OpenAI', 'Grok', 'DeepSeek', 'Kimi', 'NVIDIA', 'Runway', 'Seedance',
  'Minimax', 'Google Gemini', 'Venice AI', 'Higgsfield', 'Perplexity'
];

const AUDIO_PROVIDERS = ['ElevenLabs', 'Deepgram', 'Suno'];

const SEARCH_PROVIDERS = [
  'Perplexity', 'Google Gemini Search', 'Parallel', 'Parallel Free', 'Firecrawl',
  'DuckDuckGo', 'Brave'
];

const colors = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  gold: '\x1b[38;5;220m',
  brightYellow: '\x1b[38;5;226m',
  green: '\x1b[38;5;114m',
  cyan: '\x1b[38;5;81m',
  blue: '\x1b[38;5;75m',
  violet: '\x1b[38;5;141m',
  pink: '\x1b[38;5;213m',
  orange: '\x1b[38;5;208m',
  red: '\x1b[38;5;203m',
  gray: '\x1b[38;5;244m',
  clear: '\x1b[2J\x1b[H',
  hideCursor: '\x1b[?25l',
  showCursor: '\x1b[?25h'
};

const itemColors = [colors.gold, colors.green, colors.cyan, colors.violet, colors.orange, colors.blue, colors.pink];
const pipedAnswers = process.stdin.isTTY ? null : fs.readFileSync(0, 'utf8').split(/\r?\n/);

function color(text, value) {
  return `${value}${text}${colors.reset}`;
}

function getStorage() {
  const appData = process.env.APPDATA || path.join(os.homedir(), '.config');
  const baseDir = path.join(appData, 'valeroy-ai', 'valeroy-data');
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

  return {
    ...dirs,
    settingsPath: path.join(dirs.settingsDir, 'settings.json')
  };
}

function readSettings(storage) {
  if (!fs.existsSync(storage.settingsPath)) {
    return {};
  }

  try {
    return JSON.parse(fs.readFileSync(storage.settingsPath, 'utf8'));
  } catch {
    return {};
  }
}

function writeSettings(storage, settings) {
  fs.writeFileSync(storage.settingsPath, JSON.stringify(settings, null, 2));
}

function hashPassword(password, existingAccount = {}) {
  if (!password && existingAccount.passwordHash && existingAccount.passwordSalt) {
    return existingAccount;
  }

  if (!password) {
    return {
      passwordHash: null,
      passwordSalt: null
    };
  }

  const passwordSalt = crypto.randomBytes(16).toString('hex');
  const passwordHash = crypto.pbkdf2Sync(password, passwordSalt, 120000, 32, 'sha256').toString('hex');
  return { passwordHash, passwordSalt };
}

function banner(title, subtitle) {
  console.log(color('\nValeroy AI setup', colors.gold + colors.bold));
  console.log(color('Agentic royalty / local-first configuration', colors.gray));
  if (title) {
    console.log(color(`\n${title}`, colors.cyan + colors.bold));
  }
  if (subtitle) {
    console.log(color(subtitle, colors.gray));
  }
}

function ask(question) {
  if (pipedAnswers) {
    process.stdout.write(question);
    return Promise.resolve((pipedAnswers.shift() || '').trim());
  }

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
  });

  return new Promise((resolve) => {
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

function parseSelection(input, items, fallback = []) {
  if (!input) return fallback;
  return input
    .split(',')
    .map((part) => Number(part.trim()) - 1)
    .filter((index) => Number.isInteger(index) && index >= 0 && index < items.length)
    .map((index) => items[index]);
}

async function chooseMany(title, items, selectedItems = [], options = {}) {
  if (!process.stdin.isTTY) {
    console.log(`\n${title}`);
    items.forEach((item, index) => console.log(`${String(index + 1).padStart(2, ' ')}. ${item}`));
    const fallback = selectedItems.length ? selectedItems : (options.defaultItems || []);
    return parseSelection(await ask('\nSelect by number, comma-separated: '), items, fallback);
  }

  return runMenu({ title, items, selectedItems, multi: true, required: Boolean(options.required) });
}

async function chooseOne(title, items, selectedItem) {
  if (!process.stdin.isTTY) {
    console.log(`\n${title}`);
    items.forEach((item, index) => console.log(`${String(index + 1).padStart(2, ' ')}. ${item}`));
    const answer = Number(await ask('\nChoose one by number: ')) - 1;
    return Number.isInteger(answer) && answer >= 0 && answer < items.length
      ? items[answer]
      : selectedItem || items[0];
  }

  const result = await runMenu({ title, items, selectedItems: selectedItem ? [selectedItem] : [items[0]], multi: false, required: true });
  return result[0];
}

function runMenu({ title, items, selectedItems, multi, required }) {
  const selected = new Set(selectedItems || []);
  let cursor = Math.max(0, items.findIndex((item) => selected.has(item)));
  if (cursor < 0) cursor = 0;
  let offset = 0;
  const pageSize = Math.min(9, items.length);

  readline.emitKeypressEvents(process.stdin);
  if (process.stdin.isTTY) process.stdin.setRawMode(true);
  process.stdin.resume();
  process.stdout.write(colors.hideCursor);

  return new Promise((resolve) => {
    const render = () => {
      if (cursor < offset) offset = cursor;
      if (cursor >= offset + pageSize) offset = cursor - pageSize + 1;

      process.stdout.write(colors.clear);
      banner(title, multi ? 'Use Up/Down to scroll, Space to toggle, Enter to continue.' : 'Use Up/Down to scroll, Enter to choose.');

      const visible = items.slice(offset, offset + pageSize);
      visible.forEach((item, index) => {
        const actual = offset + index;
        const isHighlighted = actual === cursor;
        const pointer = isHighlighted ? color('>', colors.brightYellow + colors.bold) : ' ';
        const mark = multi ? (selected.has(item) ? color('[x]', colors.green) : color('[ ]', colors.gray)) : (actual === cursor ? color('[>]', colors.green) : color('[ ]', colors.gray));
        const itemColor = isHighlighted ? colors.brightYellow + colors.bold : itemColors[actual % itemColors.length];
        process.stdout.write(`${pointer} ${mark} ${color(item, itemColor)}\n`);
      });

      if (items.length > pageSize) {
        const page = `${offset + 1}-${Math.min(offset + pageSize, items.length)} of ${items.length}`;
        process.stdout.write(color(`\nShowing ${page}`, colors.gray) + '\n');
      }

      if (required && multi && selected.size === 0) {
        process.stdout.write(color('\nPick at least one option.', colors.red) + '\n');
      }

      process.stdout.write(color('\nEsc: cancel  Ctrl+C: quit', colors.gray));
    };

    const done = (value) => {
      process.stdin.off('keypress', onKeypress);
      if (process.stdin.isTTY) process.stdin.setRawMode(false);
      process.stdin.pause();
      process.stdout.write(colors.showCursor + colors.clear);
      resolve(value);
    };

    const onKeypress = (input, key = {}) => {
      let keyName = key.name;
      if (!keyName && input === '\x1b[A') keyName = 'up';
      if (!keyName && input === '\x1b[B') keyName = 'down';
      if (!keyName && input === '\r') keyName = 'return';
      if (!keyName && input === ' ') keyName = 'space';

      if (key.ctrl && key.name === 'c') {
        process.stdout.write(colors.showCursor + colors.reset + '\n');
        process.exit(130);
      }

      if (keyName === 'escape') {
        done(selectedItems || []);
        return;
      }

      if (keyName === 'up') {
        cursor = (cursor - 1 + items.length) % items.length;
        render();
        return;
      }

      if (keyName === 'down') {
        cursor = (cursor + 1) % items.length;
        render();
        return;
      }

      if (keyName === 'space' && multi) {
        const item = items[cursor];
        if (selected.has(item)) selected.delete(item);
        else selected.add(item);
        render();
        return;
      }

      if (keyName === 'return') {
        if (!multi) {
          done([items[cursor]]);
          return;
        }

        if (required && selected.size === 0) {
          render();
          return;
        }

        done([...selected]);
      }
    };

    process.stdin.on('keypress', onKeypress);
    render();
  });
}

async function collectKeys(label, selectedItems, existingKeys = {}, options = {}) {
  const keys = {};
  for (const item of selectedItems) {
    while (true) {
      const saved = existingKeys[item] ? ' [saved]' : '';
      const key = await ask(color(`${item} ${label} API key${saved}: `, colors.gold));
      const finalKey = key || existingKeys[item] || '';
      if (!options.required || finalKey) {
        keys[item] = finalKey;
        break;
      }

      const message = `${item} requires an API key because it was selected.`;
      if (pipedAnswers) {
        throw new Error(message);
      }

      console.log(color(message, colors.red));
    }
  }
  return keys;
}

async function collectCustomProviders(existing = []) {
  const customProviders = [...existing];
  const addCustom = await chooseOne('Custom AI Provider', ['Skip custom provider', 'Add custom provider'], customProviders.length ? 'Add custom provider' : 'Skip custom provider');
  if (addCustom === 'Skip custom provider') {
    return customProviders;
  }

  while (true) {
    const name = await ask(color('Custom provider name: ', colors.gold));
    if (!name) break;
    const homepageUrl = await ask(color('Homepage URL: ', colors.gold));
    const apiKey = await ask(color('API key: ', colors.gold));
    customProviders.push({
      name,
      homepageUrl,
      apiKey
    });

    const another = await chooseOne('Add Another Custom Provider', ['No, continue setup', 'Yes, add another'], 'No, continue setup');
    if (!another.startsWith('Yes')) break;
  }

  return customProviders;
}

function printStatus() {
  const storage = getStorage();
  const settings = readSettings(storage);
  banner('Setup status', `Settings file: ${storage.settingsPath}`);
  console.log(`${color('Complete:', colors.gold)} ${Boolean(settings.setupComplete)}`);
  console.log(`${color('User:', colors.gold)} ${settings.username || 'not set'}`);
  console.log(`${color('AI providers:', colors.gold)} ${(settings.providers || []).join(', ') || 'none'}`);
  console.log(`${color('Custom providers:', colors.gold)} ${(settings.customProviders || []).map((item) => item.name).join(', ') || 'none'}`);
  console.log(`${color('Audio providers:', colors.gold)} ${(settings.audioProviders || []).join(', ') || 'none'}`);
  console.log(`${color('Search provider:', colors.gold)} ${settings.searchProvider || 'not set'}`);
  console.log(`${color('App modification:', colors.gold)} ${Boolean(settings.appModificationEnabled)}`);
}

function resetSetup() {
  const storage = getStorage();
  if (!fs.existsSync(storage.settingsPath)) {
    banner('Reset setup', 'No settings file exists yet.');
    return;
  }

  const backupPath = `${storage.settingsPath}.${Date.now()}.bak`;
  fs.renameSync(storage.settingsPath, backupPath);
  banner('Reset setup', 'Settings were backed up and setup state was cleared.');
  console.log(`${color('Backup:', colors.gold)} ${backupPath}`);
  console.log(`${color('Next:', colors.gold)} valeroy setup`);
}

async function setup() {
  const storage = getStorage();
  const existing = readSettings(storage);

  console.log(colors.clear);
  banner('Step 1/5 - Account', `Settings file: ${storage.settingsPath}`);
  const username = await ask(color(`Username${existing.username ? ` [${existing.username}]` : ''}: `, colors.gold)) || existing.username || 'you';
  const password = await ask(color('Password: ', colors.gold));

  const selectedProviders = await chooseMany('Step 2/5 - AI API Providers', PROVIDERS, existing.providers || ['OpenAI'], {
    required: true,
    defaultItems: ['OpenAI']
  });
  const providerKeys = await collectKeys('provider', selectedProviders, existing.providerKeys || {});
  const customProviders = await collectCustomProviders(existing.customProviders || []);

  const selectedAudioProviders = await chooseMany('Step 3/5 - Audio Providers', AUDIO_PROVIDERS, existing.audioProviders || [], {
    required: false,
    defaultItems: []
  });
  const audioProviderKeys = await collectKeys('audio', selectedAudioProviders, existing.audioProviderKeys || {}, { required: true });

  const searchProvider = await chooseOne('Step 4/5 - Search Provider', SEARCH_PROVIDERS, existing.searchProvider || 'DuckDuckGo');
  const searchKey = searchProvider === 'DuckDuckGo'
    ? ''
    : await ask(color(`${searchProvider} API key${existing.searchKeySaved ? ' [saved]' : ''}: `, colors.gold));

  const modificationChoice = await chooseOne('Step 5/5 - App Modification', ['No, keep app locked down', 'Yes, unlock /theme and self-customization'], existing.appModificationEnabled ? 'Yes, unlock /theme and self-customization' : 'No, keep app locked down');

  const settings = {
    version: '1.0.0',
    createdAt: existing.createdAt || new Date().toISOString(),
    configuredAt: new Date().toISOString(),
    username,
    account: {
      username,
      ...hashPassword(password, existing.account || {})
    },
    passwordSaved: Boolean(password || existing.passwordSaved || existing.account?.passwordHash),
    providers: selectedProviders,
    providerKeys,
    customProviders,
    audioProviders: selectedAudioProviders,
    audioProviderKeys,
    searchProvider,
    searchProviderKey: searchKey || existing.searchProviderKey || '',
    searchKeySaved: Boolean(searchKey || existing.searchKeySaved),
    appModificationEnabled: modificationChoice.startsWith('Yes'),
    setupComplete: true
  };

  writeSettings(storage, settings);

  banner('Setup complete', 'Valeroy AI is ready to launch.');
  console.log(`${color('Storage:', colors.gold)} ${storage.baseDir}`);
  console.log(`${color('AI providers:', colors.gold)} ${selectedProviders.join(', ')}`);
  console.log(`${color('Custom providers:', colors.gold)} ${customProviders.map((item) => item.name).join(', ') || 'none'}`);
  console.log(`${color('Audio providers:', colors.gold)} ${selectedAudioProviders.length ? selectedAudioProviders.join(', ') : 'none'}`);
  console.log(`${color('Launch:', colors.gold)} valeroy\n`);
}

function launchApp() {
  const root = path.resolve(__dirname, '..');
  const electronBinary = require('electron');
  const child = spawn(electronBinary, [root], {
    stdio: 'inherit',
    windowsHide: false
  });

  child.on('exit', (code) => process.exit(code ?? 0));
}

if (process.argv[2] === 'setup' && process.argv[3] === 'status') {
  printStatus();
} else if (process.argv[2] === 'setup' && process.argv[3] === 'reset') {
  resetSetup();
} else if (process.argv[2] === 'setup') {
  setup().catch((error) => {
    process.stdout.write(colors.showCursor + colors.reset);
    console.error(color(`Setup failed: ${error.message || error}`, colors.red));
    process.exit(1);
  });
} else {
  launchApp();
}

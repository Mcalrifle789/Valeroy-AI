const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('valeroy', {
  getBootstrap: () => ipcRenderer.invoke('valeroy:get-bootstrap'),
  listProviderModels: (providerName) => ipcRenderer.invoke('valeroy:list-provider-models', providerName),
  saveSettings: (payload) => ipcRenderer.invoke('valeroy:save-settings', payload),
  revealStorage: () => ipcRenderer.invoke('valeroy:reveal-storage')
});

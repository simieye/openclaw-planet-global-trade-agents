const { contextBridge, ipcRenderer } = require('electron');

// 暴露安全的 API 给渲染进程
contextBridge.exposeInMainWorld('lobsterPlanet', {
  // 引擎控制
  getEngineStatus: () => ipcRenderer.invoke('get-engine-status'),
  startEngine: () => ipcRenderer.invoke('start-engine'),
  stopEngine: () => ipcRenderer.invoke('stop-engine'),
  runTest: () => ipcRenderer.invoke('run-test'),

  // 文件上传与批量导入
  openFileDialog: () => ipcRenderer.invoke('upload-file-dialog'),
  batchImportDialog: () => ipcRenderer.invoke('batch-import-dialog'),
  listUploadedFiles: () => ipcRenderer.invoke('list-uploaded-files'),

  // 平台信息
  platform: process.platform,
  isElectron: true,
});

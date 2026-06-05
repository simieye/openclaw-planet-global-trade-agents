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

  // 认证相关
  login: (email, password) => ipcRenderer.invoke('auth-login', email, password),
  register: (userData) => ipcRenderer.invoke('auth-register', userData),
  registerEnterprise: (enterpriseData) => ipcRenderer.invoke('auth-register-enterprise', enterpriseData),
  logout: () => ipcRenderer.invoke('auth-logout'),
  getAuthToken: () => ipcRenderer.invoke('auth-get-token'),
  refreshToken: (token) => ipcRenderer.invoke('auth-refresh-token', token),
  getUserInfo: () => ipcRenderer.invoke('auth-get-user'),
  getEnterpriseInfo: () => ipcRenderer.invoke('auth-get-enterprise'),

  // 平台信息
  platform: process.platform,
  isElectron: true,
});

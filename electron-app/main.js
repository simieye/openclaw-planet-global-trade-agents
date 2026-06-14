const { app, BrowserWindow, Menu, shell, dialog, ipcMain, Tray, nativeImage, Notification } = require('electron');
const path = require('path');
const { spawn, exec, execSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const { autoUpdater } = require('electron-updater');

let registerComposioIPC = null;
let initializeComposioMCP = null;
try {
  const composioIpc = require('./composio-ipc');
  registerComposioIPC = composioIpc.registerComposioIPC;
  initializeComposioMCP = composioIpc.initializeComposioMCP;
} catch (e) {
  console.warn('[Composio IPC] Module not available, skipping:', e.message);
  registerComposioIPC = () => {};
  initializeComposioMCP = async () => ({ success: false, error: e.message });
}

// ============================================================
// 龙虾星球共创联盟 - macOS 桌面应用
// OpenClaw + AnyGen + HeyGen 智能体集群 · Composio 1000+ 连接器
// ============================================================

let mainWindow = null;
let tray = null;
let engineProcess = null;
let dashboardProcess = null;
let isQuitting = false;

const APP_NAME = '龙虾星球共创联盟';
const ENGINE_PORT = 8080;
const DASHBOARD_PORT = 9080;
const isMac = process.platform === 'darwin';

// ============================================================
// 资源路径
// ============================================================
const resourcesPath = app.isPackaged 
  ? path.join(process.resourcesPath)
  : path.join(__dirname, '..');

function getAssetPath(relativePath) {
  return path.join(resourcesPath, relativePath);
}

// ============================================================
// Python 引擎管理
// ============================================================
function findPython() {
  // 优先查找虚拟环境或系统 Python
  const candidates = [
    path.join(resourcesPath, 'venv', 'bin', 'python3'),
    path.join(resourcesPath, 'venv', 'bin', 'python'),
    '/usr/local/bin/python3',
    '/usr/bin/python3',
    'python3',
    'python',
  ];
  for (const py of candidates) {
    try {
      if (fs.existsSync(py)) return py;
    } catch {}
  }
  // fallback: check which python3
  return 'python3';
}

function checkPort(port) {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/api/connectors/platforms/config`, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          // 确认返回的是有效的平台配置数据
          if (parsed && typeof parsed.total_platforms === 'number') {
            resolve(true);
          } else {
            resolve(false);
          }
        } catch {
          resolve(false);
        }
      });
    });
    req.on('error', () => resolve(false));
    req.setTimeout(5000, () => { req.destroy(); resolve(false); });
  });
}

// 更快速的端口连通性检查（仅检查端口是否可连接）
function checkPortAlive(port) {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/`, (res) => {
      res.resume();
      resolve(true);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(3000, () => { req.destroy(); resolve(false); });
  });
}

function startEngine() {
  const python = findPython();
  const enginePath = path.join(resourcesPath, 'orchestration', 'unified_engine.py');

  console.log(`[Main] Starting engine: ${python} ${enginePath}`);

  // 先检查引擎是否已在运行且健康
  checkPort(ENGINE_PORT).then((running) => {
    if (running) {
      console.log(`[Main] Engine already running on port ${ENGINE_PORT}, reusing existing instance`);
      engineProcess = { kill: () => {}, killed: false };
      return;
    }

    // 检查端口是否被占用（可能被残留进程占用）
    checkPortAlive(ENGINE_PORT).then((alive) => {
      if (alive) {
        console.log(`[Main] Port ${ENGINE_PORT} is occupied but engine not healthy, killing stale process...`);
        killPort(ENGINE_PORT);
      }
      // 等待端口释放后再启动
      setTimeout(() => doStartEngine(python, enginePath), alive ? 2000 : 0);
    }).catch(() => {
      // checkPortAlive 失败，直接尝试启动
      doStartEngine(python, enginePath);
    });
  }).catch((err) => {
    console.error(`[Main] checkPort error: ${err.message}, attempting to start engine anyway`);
    killPort(ENGINE_PORT);
    setTimeout(() => doStartEngine(python, enginePath), 1000);
  });
}

function doStartEngine(python, enginePath) {
  // 如果已有引擎进程在运行，先杀掉
  if (engineProcess && !engineProcess.killed) {
    engineProcess.kill('SIGTERM');
  }

  console.log(`[Main] Spawning engine process...`);
  
  engineProcess = spawn(python, [
    enginePath, 'serve', 
    '--port', String(ENGINE_PORT),
    '--host', '0.0.0.0',
  ], {
    cwd: resourcesPath,
    env: { ...process.env, PYTHONUNBUFFERED: '1', COMPOSIO_API_KEY: process.env.COMPOSIO_API_KEY || 'ak_hFYEURBG1n_r7pMYWNSY', ANYGEN_API_KEY: process.env.ANYGEN_API_KEY || 'sk-ag-ete-4Z9Ku5F1npH8tJYQSwkkTLYqew7G0pa7LEAGa8m1m-hghzf7JHwSj-WMfDNMcpzWQLafhQu0wKUq2QAbqw' },
    stdio: ['pipe', 'pipe', 'pipe']
  });

  engineProcess.stdout.on('data', (data) => {
    console.log(`[Engine] ${data.toString().trim()}`);
  });

  engineProcess.stderr.on('data', (data) => {
    const msg = data.toString().trim();
    console.error(`[Engine Error] ${msg}`);
  });

  engineProcess.on('close', (code) => {
    console.log(`[Main] Engine process exited with code ${code}`);
    if (!isQuitting) {
      // 自动重启
      setTimeout(() => {
        if (!isQuitting) {
          console.log('[Main] Auto-restarting engine...');
          startEngine();
        }
      }, 5000);
    }
  });

  engineProcess.on('error', (err) => {
    console.error('[Main] Failed to start engine:', err.message);
  });
}

function killPort(port) {
  try {
    const result = execSync(`lsof -ti :${port} 2>/dev/null`, { encoding: 'utf8' }).trim();
    if (result) {
      const pids = result.split('\n').filter(p => p.trim());
      pids.forEach(pid => {
        try { 
          const pidNum = parseInt(pid.trim());
          if (pidNum && pidNum !== process.pid) {
            process.kill(pidNum, 'SIGKILL'); 
            console.log(`[Main] Killed process ${pidNum} on port ${port}`);
          }
        } catch(e) {}
      });
      if (pids.length > 0) {
        console.log(`[Main] Killed ${pids.length} old process(es) on port ${port}: ${pids.join(',')}`);
        // 等待端口释放
        require('child_process').execSync('sleep 1');
      }
    }
  } catch(e) {
    console.log(`[Main] No processes to kill on port ${port} (or lsof failed)`);
  }
}

function startDashboardServer() {
  // 启动 HTTP 服务器托管 dashboard，并代理 /api/ 请求到引擎
  const dashboardDir = path.join(resourcesPath, 'dashboard');
  const engineUrl = `http://127.0.0.1:${ENGINE_PORT}`;
  
  // 先杀掉 9080 端口上的旧进程，确保使用新的 dashboard
  killPort(DASHBOARD_PORT);
  
  console.log(`[Main] Starting dashboard server`);
  console.log(`[Main] Dashboard dir: ${dashboardDir}`);
  console.log(`[Main] Engine URL: ${engineUrl}`);
  console.log(`[Main] Is packaged: ${app.isPackaged}`);
  
  // 优先使用独立的 dashboard_server.py 文件（如果存在）
  const serverScript = path.join(resourcesPath, 'electron-app', 'dashboard_server.py');
  if (fs.existsSync(serverScript)) {
    console.log(`[Main] Using dashboard_server.py: ${serverScript}`);
    dashboardProcess = spawn('python3', [
      serverScript,
      dashboardDir,
      engineUrl,
      String(DASHBOARD_PORT)
    ], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' }
    });
  } else {
    // 回退：使用内联 Python 代码
    console.log(`[Main] dashboard_server.py not found, using inline server`);
    const pythonCode = `
import http.server
import socketserver
import urllib.request
import os, sys, json

DASHBOARD_DIR = ${JSON.stringify(dashboardDir)}
ENGINE_URL = ${JSON.stringify(engineUrl)}
PORT = ${DASHBOARD_PORT}

os.chdir(DASHBOARD_DIR)
print(f"Serving dashboard from: {os.getcwd()}", flush=True)
print(f"Engine URL: {ENGINE_URL}", flush=True)

class ProxyHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    def do_GET(self):
        if self.path.startswith('/api/'):
            self._proxy('GET')
        else:
            # 对根路径和HTML文件设置正确的MIME类型
            super().do_GET()
    def do_POST(self):
        if self.path.startswith('/api/'):
            self._proxy('POST')
        else:
            super().do_POST()
    def do_PUT(self):
        if self.path.startswith('/api/'):
            self._proxy('PUT')
        else:
            super().do_PUT()
    def do_DELETE(self):
        if self.path.startswith('/api/'):
            self._proxy('DELETE')
        else:
            super().do_DELETE()
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
    def _proxy(self, method):
        try:
            url = ENGINE_URL + self.path
            body = None
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                body = self.rfile.read(content_length)
            req = urllib.request.Request(url, data=body, method=method)
            for key, val in self.headers.items():
                if key.lower() not in ('host', 'connection'):
                    req.add_header(key, val)
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for key, val in resp.getheaders():
                    if key.lower() not in ('transfer-encoding', 'connection'):
                        self.send_header(key, val)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(resp.read())
        except Exception as e:
            self.send_response(502)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"Proxy failed: {str(e)}"}).encode())

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("", PORT), ProxyHandler) as httpd:
    print(f"Dashboard server ready on port {PORT}", flush=True)
    httpd.serve_forever()
`;

    dashboardProcess = spawn('python3', ['-c', pythonCode], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' }
    });
  }

  dashboardProcess.stdout.on('data', (data) => {
    console.log(`[Dashboard] ${data.toString().trim()}`);
  });
  
  dashboardProcess.stderr.on('data', (data) => {
    console.error(`[Dashboard:err] ${data.toString().trim()}`);
  });
  
  dashboardProcess.on('error', (err) => {
    console.error(`[Dashboard] Failed to start: ${err.message}`);
  });
  
  dashboardProcess.on('close', (code) => {
    console.log(`[Dashboard] Process exited with code ${code}`);
    if (!isQuitting) {
      // 自动重启 dashboard 服务器
      setTimeout(() => {
        if (!isQuitting) {
          console.log('[Main] Auto-restarting dashboard server...');
          startDashboardServer();
        }
      }, 3000);
    }
  });
}

function stopAllServices() {
  if (engineProcess) {
    engineProcess.kill('SIGTERM');
    engineProcess = null;
  }
  if (dashboardProcess) {
    dashboardProcess.kill('SIGTERM');
    dashboardProcess = null;
  }
}

// ============================================================
// 窗口管理
// ============================================================
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    title: APP_NAME,
    icon: path.join(resourcesPath, 'icons', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
      spellcheck: true,
    },
    titleBarStyle: 'hiddenInset',
    vibrancy: 'under-window',
    visualEffectState: 'active',
    backgroundColor: '#0a0a1a',
    show: false,
  });

  // 启动 Dashboard 代理服务器（打包模式和开发模式都需要）
  startDashboardServer();

  // 等待 dashboard 服务器就绪后加载
  const MAX_RETRIES = 30;
  
  function waitForDashboard(retries = MAX_RETRIES) {
    const req = http.get(`http://localhost:${DASHBOARD_PORT}/`, (res) => {
      if (res.statusCode === 200) {
        console.log('[Main] Dashboard server ready, loading via HTTP');
        mainWindow.loadURL(`http://localhost:${DASHBOARD_PORT}`).then(() => {
          // 页面加载后检查 JS 健康状态
          checkPageHealth();
        });
        // 消费响应数据
        res.resume();
      } else {
        console.log(`[Main] Dashboard returned ${res.statusCode}, retrying...`);
        retryLoad(retries);
      }
    });
    req.on('error', (err) => {
      console.log(`[Main] Dashboard not ready (${err.code}), retries left: ${retries}`);
      retryLoad(retries);
    });
    req.setTimeout(2000, () => {
      req.destroy();
      retryLoad(retries);
    });
  }

  // JS 健康检查：确保 switchPanel、APP 和 Composio 独立模态框可用
  function checkPageHealth(attempt = 1) {
    const MAX_ATTEMPTS = 8;
    setTimeout(() => {
      mainWindow.webContents.executeJavaScript(`
        (function() {
          if (typeof switchPanel === 'function' && typeof APP !== 'undefined') {
            // 检查 Composio 独立 modal 函数是否可用
            if (typeof ensureComposioModal === 'function') {
              // 预创建 Composio 独立 modal 系统
              try { ensureComposioModal(); } catch(e) {}
              return 'ok:composio-ready';
            }
            return 'ok:composio-missing-fn';
          }
          return 'broken:' + (typeof switchPanel) + ':' + (typeof APP);
        })()
      `).then(result => {
        if (result.startsWith('ok')) {
          console.log('[Main] Page JS health check passed: ' + result);
          // 预创建 Composio 独立 modal 并预加载数据
          mainWindow.webContents.executeJavaScript(`
            // 预创建独立 modal 系统
            if (typeof ensureComposioModal === 'function') {
              try { ensureComposioModal(); } catch(e) { console.warn('[Electron] ensureComposioModal error:', e); }
            }
            // 预加载 Composio 数据
            if (typeof renderComposio === 'function' && !window._composioPreloaded) {
              window._composioPreloaded = true;
              console.log('[Electron] Pre-loading Composio data...');
              setTimeout(function() { renderComposio(); }, 1000);
            }
          `);
        } else {
          console.log('[Main] Page JS health check failed (' + result + '), attempt ' + attempt + '/' + MAX_ATTEMPTS);
          if (attempt < MAX_ATTEMPTS) {
            console.log('[Main] Reloading page to recover...');
            mainWindow.webContents.reload();
            checkPageHealth(attempt + 1);
          } else {
            console.error('[Main] Page JS health check failed after ' + MAX_ATTEMPTS + ' attempts');
          }
        }
      }).catch(err => {
        console.log('[Main] Page JS health check error:', err.message, 'attempt', attempt);
        if (attempt < MAX_ATTEMPTS) {
          mainWindow.webContents.reload();
          checkPageHealth(attempt + 1);
        }
      });
    }, 2000); // 给页面 2 秒初始化时间
  }
  
  function retryLoad(retries) {
    if (retries > 0) {
      setTimeout(() => waitForDashboard(retries - 1), 500);
    } else {
      // 回退：直接加载本地文件
      const dashFile = path.join(resourcesPath, 'dashboard', 'index.html');
      console.log(`[Main] Dashboard server timeout after ${MAX_RETRIES} retries, loading file: ${dashFile}`);
      console.log(`[Main] File exists: ${fs.existsSync(dashFile)}`);
      try {
        mainWindow.loadFile(dashFile).catch(err => {
          console.error(`[Main] loadFile failed: ${err.message}`);
          // 最后尝试：直接设置 HTML 内容
          mainWindow.loadURL('data:text/html,<html><body style="background:#0a0a1a;color:white;display:flex;align-items:center;justify-content:center;height:100vh;font-family:sans-serif"><div style="text-align:center"><h1>🦞 龙虾星球共创联盟</h1><p>Dashboard 服务启动失败</p><p style="color:#888">请检查 Python3 环境是否正常</p><button onclick="location.reload()" style="margin-top:20px;padding:10px 30px;background:#e74c3c;color:white;border:none;border-radius:6px;cursor:pointer;font-size:16px">重试</button></div></body></html>');
        });
      } catch(e) {
        console.error(`[Main] Critical error: ${e.message}`);
      }
    }
  }
  
  // 给 dashboard 服务器一些启动时间
  setTimeout(() => waitForDashboard(), 1000);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (isMac) {
      app.dock.show();
    }
  });

  mainWindow.on('close', (event) => {
    if (!isQuitting && isMac) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  // 外部链接在浏览器打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

// ============================================================
// 菜单
// ============================================================
function createMenu() {
  const template = [
    {
      label: APP_NAME,
      submenu: [
        {
          label: '关于龙虾星球',
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: '关于 龙虾星球共创联盟',
              message: '🦞 Simiaiclaw OS v5.3.0 · 一万个硅基大脑 · 全量调度操作系统',
              detail: `微软 Build 2026 Agent First 战略对齐\n100+ AI 智能体集群 · 8层组织架构 · 全链路SOP\nOpenClaw · AnyGen · HeyGen · Composio 多引擎集成\n1000+ Claude Skills · 30+ 平台连接器\nSellerSprite 43 Tools · Amazon 全维度数据情报\n\n跨境电商品牌出海 AI 驱动平台\n企业级知识库 · Webhook工作流 · TaskFlow自动化\n\nCopyright © 2026 Lobster Planet Co-Creation Alliance`,
              icon: nativeImage.createFromPath(path.join(resourcesPath, 'icons', 'icon.png')),
            });
          }
        },
        { type: 'separator' },
        {
          label: '偏好设置...',
          accelerator: 'Cmd+,',
          click: () => {
            if (mainWindow) {
              mainWindow.show();
              mainWindow.webContents.executeJavaScript(`
                if (typeof switchPanel === 'function') {
                  switchPanel('settings');
                }
              `);
            }
          }
        },
        { type: 'separator' },
        { label: '隐藏龙虾星球', accelerator: 'Cmd+H', role: 'hide' },
        { label: '隐藏其他', accelerator: 'Cmd+Shift+H', role: 'hideOthers' },
        { type: 'separator' },
        {
          label: '退出',
          accelerator: 'Cmd+Q',
          click: () => {
            isQuitting = true;
            stopAllServices();
            app.quit();
          }
        }
      ]
    },
    {
      label: '引擎',
      submenu: [
        {
          label: '启动引擎',
          click: () => { startEngine(); }
        },
        {
          label: '停止引擎',
          click: () => {
            if (engineProcess) {
              engineProcess.kill('SIGTERM');
              engineProcess = null;
            }
          }
        },
        {
          label: '重启引擎',
          click: () => {
            if (engineProcess) engineProcess.kill('SIGTERM');
            setTimeout(() => startEngine(), 2000);
          }
        },
        { type: 'separator' },
        {
          label: '查看引擎状态',
          click: () => {
            exec(`python3 ${path.join(resourcesPath, 'orchestration', 'engine.py')} status`, { cwd: resourcesPath }, (err, stdout, stderr) => {
              dialog.showMessageBox(mainWindow, {
                type: 'info',
                title: '引擎状态',
                message: 'OpenClaw 引擎状态',
                detail: stdout || stderr || '引擎未运行',
              });
            });
          }
        },
        { type: 'separator' },
        {
          label: '运行集成测试',
          click: () => {
            exec(`python3 ${path.join(resourcesPath, 'orchestration', 'engine.py')} test`, { cwd: resourcesPath }, (err, stdout, stderr) => {
              dialog.showMessageBox(mainWindow, {
                type: 'info',
                title: '集成测试结果',
                message: '测试完成',
                detail: stdout || stderr || '无输出',
              });
            });
          }
        },
      ]
    },
    {
      label: '编辑',
      submenu: [
        { label: '撤销', accelerator: 'Cmd+Z', role: 'undo' },
        { label: '重做', accelerator: 'Shift+Cmd+Z', role: 'redo' },
        { type: 'separator' },
        { label: '剪切', accelerator: 'Cmd+X', role: 'cut' },
        { label: '复制', accelerator: 'Cmd+C', role: 'copy' },
        { label: '粘贴', accelerator: 'Cmd+V', role: 'paste' },
        { label: '全选', accelerator: 'Cmd+A', role: 'selectAll' },
      ]
    },
    {
      label: '视图',
      submenu: [
        { label: '重新加载', accelerator: 'Cmd+R', role: 'reload' },
        { label: '开发者工具', accelerator: 'Cmd+Option+I', role: 'toggleDevTools' },
        { type: 'separator' },
        { label: '放大', accelerator: 'Cmd+=', role: 'zoomIn' },
        { label: '缩小', accelerator: 'Cmd+-', role: 'zoomOut' },
        { label: '实际大小', accelerator: 'Cmd+0', role: 'resetZoom' },
      ]
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '项目文档',
          click: () => {
            const readmePath = path.join(resourcesPath, 'README.md');
            if (fs.existsSync(readmePath)) shell.openPath(readmePath);
          }
        },
        {
          label: '部署指南',
          click: () => {
            const deployPath = path.join(resourcesPath, 'DEPLOY.md');
            if (fs.existsSync(deployPath)) shell.openPath(deployPath);
          }
        },
        { type: 'separator' },
        {
          label: 'GitHub 仓库',
          click: () => shell.openExternal('https://github.com/simieye/openclaw-planet-global-trade-agents')
        },
        {
          label: '问题反馈',
          click: () => shell.openExternal('https://github.com/simieye/openclaw-planet-global-trade-agents/issues')
        },
      ]
    }
  ];

  // macOS 特定菜单项
  if (isMac) {
    template.unshift({
      label: app.name,
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit' }
      ]
    });
  }

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
}

// ============================================================
// 系统托盘
// ============================================================
function createTray() {
  const iconPath = path.join(resourcesPath, 'icons', 'tray-icon.png');
  // 如果没有自定义图标，创建一个简单的
  let trayIcon;
  try {
    trayIcon = nativeImage.createFromPath(iconPath);
    if (trayIcon.isEmpty()) throw new Error('empty');
  } catch {
    // 创建一个 16x16 的简易图标
    trayIcon = nativeImage.createEmpty();
  }
  
  const resizedIcon = trayIcon.resize({ width: 16, height: 16 });
  tray = new Tray(resizedIcon);
  tray.setToolTip(APP_NAME);

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        } else {
          createMainWindow();
        }
      }
    },
    {
      label: '引擎状态',
      enabled: false
    },
    { type: 'separator' },
    {
      label: '启动引擎',
      click: () => startEngine()
    },
    {
      label: '停止引擎',
      click: () => {
        if (engineProcess) {
          engineProcess.kill('SIGTERM');
          engineProcess = null;
        }
      }
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        isQuitting = true;
        stopAllServices();
        app.quit();
      }
    }
  ]);

  tray.setContextMenu(contextMenu);

  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.focus();
      } else {
        mainWindow.show();
      }
    }
  });
}

// ============================================================
// IPC 通信
// ============================================================
ipcMain.handle('get-engine-status', async () => {
  return new Promise((resolve) => {
    exec(`python3 ${path.join(resourcesPath, 'orchestration', 'engine.py')} status`, { cwd: resourcesPath }, (err, stdout) => {
      resolve({
        running: engineProcess !== null && !engineProcess.killed,
        output: stdout,
        error: err ? err.message : null,
      });
    });
  });
});

ipcMain.handle('start-engine', async () => {
  startEngine();
  return { success: true };
});

ipcMain.handle('stop-engine', async () => {
  if (engineProcess) {
    engineProcess.kill('SIGTERM');
    engineProcess = null;
  }
  return { success: true };
});

ipcMain.handle('run-test', async () => {
  return new Promise((resolve) => {
    exec(`python3 ${path.join(resourcesPath, 'orchestration', 'engine.py')} test`, { cwd: resourcesPath }, (err, stdout, stderr) => {
      resolve({ success: !err, output: stdout || stderr });
    });
  });
});

ipcMain.handle('check-for-updates', async () => {
  if (!app.isPackaged) return { dev: true };
  try {
    const result = await autoUpdater.checkForUpdates();
    return { updateInfo: result?.updateInfo || null };
  } catch (err) {
    return { error: err.message };
  }
});

ipcMain.handle('download-update', async () => {
  try {
    await autoUpdater.downloadUpdate();
    return { success: true };
  } catch (err) {
    return { error: err.message };
  }
});

// ============================================================
// 文件操作 IPC
// ============================================================
const KNOWLEDGE_DIR = path.join(resourcesPath, 'knowledge', 'uploads');

// 确保上传目录存在
function ensureUploadDir() {
  if (!fs.existsSync(KNOWLEDGE_DIR)) {
    fs.mkdirSync(KNOWLEDGE_DIR, { recursive: true });
  }
}

// 选择并上传单个文件
ipcMain.handle('upload-file-dialog', async () => {
  ensureUploadDir();
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择要上传的文件',
    properties: ['openFile'],
    filters: [
      { name: '支持的文档', extensions: ['txt', 'md', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'json', 'toml', 'yaml', 'yml', 'html', 'htm', 'xml', 'rtf', 'odt'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  });

  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true };
  }

  const srcPath = result.filePaths[0];
  const fileName = path.basename(srcPath);
  const destPath = path.join(KNOWLEDGE_DIR, fileName);

  // 防止覆盖同名文件，添加时间戳后缀
  const finalDestPath = !fs.existsSync(destPath) ? destPath :
    path.join(KNOWLEDGE_DIR, `${path.parse(fileName).name}_${Date.now()}${path.extname(fileName)}`);

  try {
    fs.copyFileSync(srcPath, finalDestPath);
    const stats = fs.statSync(finalDestPath);
    return {
      success: true,
      fileName,
      filePath: finalDestPath,
      size: stats.size,
      uploadTime: new Date().toISOString(),
    };
  } catch (err) {
    return { success: false, error: err.message };
  }
});

// 批量导入文件/文件夹
ipcMain.handle('batch-import-dialog', async () => {
  ensureUploadDir();
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择要批量导入的文件或文件夹',
    properties: ['openFile', 'multiSelections', 'openDirectory'],
    filters: [
      { name: '支持的文档', extensions: ['txt', 'md', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'json', 'toml', 'yaml', 'yml', 'html', 'htm', 'xml', 'rtf', 'odt', 'png', 'jpg', 'jpeg', 'gif', 'svg', 'mp3', 'mp4'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  });

  if (result.canceled || result.filePaths.length === 0) {
    return { canceled: true };
  }

  const results = [];
  let successCount = 0;
  let failCount = 0;

  for (const srcPath of result.filePaths) {
    const stat = fs.statSync(srcPath);
    
    if (stat.isDirectory()) {
      // 目录：递归复制所有文件
      const dirName = path.basename(srcPath);
      const destDir = path.join(KNOWLEDGE_DIR, dirName);
      
      try {
        copyDirectory(srcPath, destDir);
        const fileCount = countFiles(destDir);
        successCount += fileCount;
        results.push({ type: 'directory', name: dirName, files: fileCount, status: 'success' });
      } catch (err) {
        failCount++;
        results.push({ type: 'directory', name: dirName, status: 'failed', error: err.message });
      }
    } else {
      // 单个文件
      const fileName = path.basename(srcPath);
      const finalDestPath = path.join(KNOWLEDGE_DIR, fileName);

      if (!fs.existsSync(finalDestPath)) {
        try {
          fs.copyFileSync(srcPath, finalDestPath);
          successCount++;
          results.push({
            type: 'file', name: fileName,
            size: fs.statSync(finalDestPath).size,
            status: 'success'
          });
        } catch (err) {
          failCount++;
          results.push({ type: 'file', name: fileName, status: 'failed', error: err.message });
        }
      } else {
        // 同名文件加时间戳后缀
        const safeName = `${path.parse(fileName).name}_${Date.now()}${path.extname(fileName)}`;
        const safePath = path.join(KNOWLEDGE_DIR, safeName);
        try {
          fs.copyFileSync(srcPath, safePath);
          successCount++;
          results.push({
            type: 'file', name: safeName,
            size: fs.statSync(safePath).size,
            status: 'success', renamed: true
          });
        } catch (err) {
          failCount++;
          results.push({ type: 'file', name: fileName, status: 'failed', error: err.message });
        }
      }
    }
  }

  return {
    success: true,
    totalFiles: successCount + failCount,
    successCount,
    failCount,
    results,
    importTime: new Date().toISOString(),
  };
});

// 递归复制目录
function copyDirectory(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }

  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(entry.path || src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyDirectory(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

// 统计目录中的文件数
function countFiles(dir) {
  let count = 0;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isFile()) count++;
    else if (entry.isDirectory()) count += countFiles(path.join(dir, entry.name));
  }
  return count;
}

// 获取已上传的文件列表
ipcMain.handle('list-uploaded-files', async () => {
  ensureUploadDir();
  
  function listFilesRecursive(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    const files = [];
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isFile()) {
        const stats = fs.statSync(fullPath);
        files.push({
          name: entry.name,
          path: fullPath.replace(resourcesPath + path.sep, ''),
          size: stats.size,
          modified: stats.mtime.toISOString(),
        });
      } else if (entry.isDirectory() && entry.name !== '__pycache__') {
        files.push(...listFilesRecursive(fullPath));
      }
    }
    return files;
  }

  try {
    const files = listFilesRecursive(KNOWLEDGE_DIR);
    return { success: true, files, total: files.length };
  } catch (err) {
    return { success: false, error: err.message };
  }
});

// ============================================================
// 认证 IPC Handlers
// ============================================================

const ENGINE_URL = `http://localhost:${ENGINE_PORT}`;

function httpRequest(method, apiPath, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(apiPath, ENGINE_URL);
    const data = body ? JSON.stringify(body) : null;
    
    const options = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname + url.search,
      method: method,
      headers: {
        'Content-Type': 'application/json',
      },
    };

    const req = http.request(options, (res) => {
      let chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        try {
          const result = JSON.parse(Buffer.concat(chunks).toString());
          resolve({ status: res.statusCode, data: result });
        } catch(e) {
          resolve({ status: res.statusCode, data: Buffer.concat(chunks).toString() });
        }
      });
    });

    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

// 存储 token（在 Electron 主进程内存中）
let authToken = null;
let authUser = null;

ipcMain.handle('auth-login', async (event, email, password) => {
  try {
    const result = await httpRequest('POST', '/api/auth/login', { email, password });
    if (result.status === 200 && result.data.access_token) {
      authToken = result.data.access_token;
      authUser = result.data.user;
      return { success: true, ...result.data };
    }
    return { success: false, error: result.data.detail || '登录失败' };
  } catch(err) {
    return { success: false, error: err.message };
  }
});

ipcMain.handle('auth-register', async (event, userData) => {
  try {
    const result = await httpRequest('POST', '/api/auth/register', userData);
    if (result.status === 200 && result.data.success) {
      return { success: true, ...result.data };
    }
    return { success: false, error: result.data.detail || '注册失败' };
  } catch(err) {
    return { success: false, error: err.message };
  }
});

ipcMain.handle('auth-register-enterprise', async (event, enterpriseData) => {
  try {
    const result = await httpRequest('POST', '/api/auth/register/enterprise', enterpriseData);
    if (result.status === 200 && result.data.success) {
      return { success: true, ...result.data };
    }
    return { success: false, error: result.data.detail || '企业注册失败' };
  } catch(err) {
    return { success: false, error: err.message };
  }
});

ipcMain.handle('auth-logout', async () => {
  if (authToken) {
    try {
      await httpRequest('POST', '/api/auth/logout');
    } catch(e) {}
  }
  authToken = null;
  authUser = null;
  return { success: true };
});

ipcMain.handle('auth-get-token', async () => {
  return { success: true, token: authToken, user: authUser };
});

ipcMain.handle('auth-refresh-token', async (event, refreshToken) => {
  try {
    const result = await httpRequest('POST', '/api/auth/refresh', { refresh_token: refreshToken });
    if (result.status === 200 && result.data.access_token) {
      authToken = result.data.access_token;
      return { success: true, ...result.data };
    }
    return { success: false, error: '刷新失败' };
  } catch(err) {
    return { success: false, error: err.message };
  }
});

ipcMain.handle('auth-get-user', async () => {
  if (!authToken) return { success: false, error: '未登录' };
  try {
    const result = await httpRequest('GET', '/api/auth/me');
    if (result.status === 200 && result.data.success) {
      return { success: true, user: result.data.user };
    }
    return { success: false, error: '获取用户信息失败' };
  } catch(err) {
    return { success: false, error: err.message };
  }
});

ipcMain.handle('auth-get-enterprise', async () => {
  if (!authToken) return { success: false, error: '未登录' };
  try {
    const result = await httpRequest('GET', '/api/auth/enterprise');
    if (result.status === 200 && result.data.success) {
      return { success: true, enterprise: result.data.enterprise };
    }
    return { success: false, error: '获取企业信息失败' };
  } catch(err) {
    return { success: false, error: err.message };
  }
});

// ============================================================
// 自动更新
// ============================================================
function setupAutoUpdater() {
  if (!app.isPackaged) {
    console.log('Auto-updater disabled in dev mode');
    return;
  }

  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('checking-for-update', () => {
    console.log('Checking for updates...');
  });

  autoUpdater.on('update-available', (info) => {
    dialog.showMessageBox(mainWindow, {
      type: 'info',
      title: '发现新版本',
      message: `龙虾星球共创联盟 v${info.version} 可用！`,
      detail: '是否立即下载更新？',
      buttons: ['立即下载', '稍后提醒'],
      defaultId: 0,
      cancelId: 1,
    }).then(({ response }) => {
      if (response === 0) {
        autoUpdater.downloadUpdate();
      }
    });
  });

  autoUpdater.on('update-not-available', () => {
    console.log('Current version is up-to-date');
  });

  autoUpdater.on('download-progress', (progress) => {
    if (mainWindow) {
      mainWindow.webContents.send('update-progress', progress);
    }
  });

  autoUpdater.on('update-downloaded', () => {
    dialog.showMessageBox(mainWindow, {
      type: 'info',
      title: '更新已下载',
      message: '新版本已下载完成，重启应用即可安装更新。',
      buttons: ['立即重启', '稍后'],
      defaultId: 0,
    }).then(({ response }) => {
      if (response === 0) {
        autoUpdater.quitAndInstall();
      }
    });
  });

  autoUpdater.on('error', (err) => {
    console.error('Auto-updater error:', err);
  });

  // 每6小时检查一次更新
  setInterval(() => {
    autoUpdater.checkForUpdates();
  }, 6 * 60 * 60 * 1000);

  // 启动时延迟检查
  setTimeout(() => {
    autoUpdater.checkForUpdates();
  }, 10000);
}

// ============================================================
// App 生命周期
// ============================================================
app.whenReady().then(() => {
  console.log(`${APP_NAME} starting...`);
  console.log(`Resources path: ${resourcesPath}`);

  // 注册 Composio IPC（1000+ 连接器集成）
  registerComposioIPC();

  // 初始化 Composio MCP HTTP 连接 (connect.composio.dev/mcp)
  if (initializeComposioMCP) {
    initializeComposioMCP().then(result => {
      if (result.success) {
        console.log('[Composio MCP] Initialized successfully');
      } else {
        console.warn('[Composio MCP] Init failed:', result.error);
      }
    });
  }

  createMenu();
  createMainWindow();

  if (isMac) {
    createTray();
  }

  // 启动引擎
  startEngine();

  // 设置自动更新
  setupAutoUpdater();

  app.on('activate', () => {
    if (mainWindow === null) {
      createMainWindow();
    } else {
      mainWindow.show();
    }
  });
});

app.on('window-all-closed', () => {
  if (!isMac) {
    isQuitting = true;
    stopAllServices();
    app.quit();
  }
});

app.on('before-quit', () => {
  isQuitting = true;
  stopAllServices();
});

// 防止多个实例
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

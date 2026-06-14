/**
 * Composio Electron 集成模块
 * 
 * 在 Electron 主进程中使用 @composio/core + @composio/vercel SDK，
 * 通过 IPC 向渲染进程暴露 Composio 集成能力。
 * 
 * 功能：
 *   - 工具包搜索和列表
 *   - 工具执行
 *   - 连接管理
 *   - Vercel AI SDK Agent 执行
 *   - MCP HTTP Transport (connect.composio.dev/mcp)
 */

const { ipcMain } = require('electron');

// ============================================================
// 配置
// ============================================================

const COMPOSIO_API_KEY = process.env.COMPOSIO_API_KEY || 'ak_hFYEURBG1n_r7pMYWNSY';
const COMPOSIO_BASE_URL = process.env.COMPOSIO_BASE_URL || 'https://backend.composio.dev';
const COMPOSIO_MCP_URL = process.env.COMPOSIO_MCP_URL || 'https://connect.composio.dev/mcp';
const ENGINE_URL = 'http://localhost:8080';

// ============================================================
// Composio API 客户端（通过 Python 后端代理）
// ============================================================

class ComposioElectronClient {
  constructor() {
    this.baseUrl = ENGINE_URL;
  }

  async _request(method, path, body = null) {
    const http = require('http');
    return new Promise((resolve, reject) => {
      const url = new URL(path, this.baseUrl);
      const options = {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname + url.search,
        method,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
        },
        timeout: 30000,
      };

      const req = http.request(options, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          try {
            const parsed = JSON.parse(data);
            resolve(parsed);
          } catch {
            resolve({ success: false, raw: data });
          }
        });
      });

      req.on('error', reject);
      req.on('timeout', () => { req.destroy(); reject(new Error('Request timeout')); });

      if (body) {
        req.write(JSON.stringify(body));
      }
      req.end();
    });
  }

  async getStatus() {
    return this._request('GET', '/api/composio/status');
  }

  async listToolkits(options = {}) {
    const params = new URLSearchParams();
    if (options.category) params.set('category', options.category);
    if (options.query) params.set('query', options.query);
    if (options.popular) params.set('popular', 'true');
    if (options.limit) params.set('limit', String(options.limit));
    return this._request('GET', `/api/composio/toolkits?${params.toString()}`);
  }

  async getToolkit(slug) {
    return this._request('GET', `/api/composio/toolkits/${slug}`);
  }

  async getCategories() {
    return this._request('GET', '/api/composio/categories');
  }

  async search(query, category = null, limit = 20) {
    return this._request('POST', '/api/composio/search', { query, category, limit });
  }

  async execute(slug, params = {}, app = null) {
    return this._request('POST', '/api/composio/execute', { slug, params, app });
  }

  async getConnections() {
    return this._request('GET', '/api/composio/connections');
  }

  async connect(app, redirectUrl = null) {
    return this._request('POST', '/api/composio/connect', { app, redirectUrl });
  }

  async getPopular(limit = 50) {
    return this._request('GET', `/api/composio/popular?limit=${limit}`);
  }
}

// ============================================================
// Composio MCP HTTP Client — Streamable HTTP Transport
// 连接到 https://connect.composio.dev/mcp
// 实现 MCP 协议 JSON-RPC 2.0 over HTTP
// ============================================================

class ComposioMCPClient {
  constructor(mcpUrl = COMPOSIO_MCP_URL) {
    this.mcpUrl = mcpUrl;
    this.sessionId = null;
    this.serverInfo = null;
    this.tools = [];
    this.connected = false;
    this.requestId = 1;
  }

  _nextId() {
    return this.requestId++;
  }

  async _rpc(method, params = null) {
    const https = require('https');
    const url = new URL(this.mcpUrl);

    const body = JSON.stringify({
      jsonrpc: '2.0',
      id: this._nextId(),
      method,
      params: params || {}
    });

    return new Promise((resolve, reject) => {
      const options = {
        hostname: url.hostname,
        port: url.port || 443,
        path: url.pathname,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Content-Length': Buffer.byteLength(body),
        },
        timeout: 30000,
      };

      // OAuth header — 如果已认证则自动附加
      if (this.sessionId) {
        options.headers['Mcp-Session-Id'] = this.sessionId;
      }

      const req = https.request(options, (res) => {
        // 获取 session ID from headers
        const sid = res.headers['mcp-session-id'];
        if (sid) {
          this.sessionId = sid;
        }

        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          try {
            const parsed = JSON.parse(data);
            if (parsed.error) {
              reject(new Error(`MCP Error: ${parsed.error.message || JSON.stringify(parsed.error)}`));
            } else {
              resolve(parsed.result || parsed);
            }
          } catch (e) {
            resolve({ raw: data });
          }
        });
      });

      req.on('error', (e) => reject(new Error(`MCP connection failed: ${e.message}`)));
      req.on('timeout', () => { req.destroy(); reject(new Error('MCP request timeout')); });

      req.write(body);
      req.end();
    });
  }

  async initialize() {
    try {
      const result = await this._rpc('initialize', {
        protocolVersion: '2024-11-05',
        capabilities: {
          tools: {},
        },
        clientInfo: {
          name: '龙虾星球共创联盟 - Composio MCP',
          version: '5.5.0',
        },
      });

      this.serverInfo = result.serverInfo || result;
      this.connected = true;

      // 发送 initialized 通知
      try {
        await this._rpc('notifications/initialized', {});
      } catch (_) { /* 通知不需要响应 */ }

      console.log(`[Composio MCP] Connected to ${COMPOSIO_MCP_URL}`);
      console.log(`[Composio MCP] Server: ${JSON.stringify(this.serverInfo)}`);

      return { success: true, serverInfo: this.serverInfo };
    } catch (error) {
      console.error('[Composio MCP] Initialize failed:', error.message);
      return { success: false, error: error.message };
    }
  }

  async listTools() {
    try {
      if (!this.connected) {
        await this.initialize();
      }
      const result = await this._rpc('tools/list');
      this.tools = result.tools || [];
      console.log(`[Composio MCP] Listed ${this.tools.length} tools`);
      return { success: true, tools: this.tools, count: this.tools.length };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }

  async callTool(toolName, args = {}) {
    try {
      if (!this.connected) {
        await this.initialize();
      }
      const result = await this._rpc('tools/call', {
        name: toolName,
        arguments: args,
      });
      return { success: true, result };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }

  async getStatus() {
    return {
      connected: this.connected,
      sessionId: this.sessionId ? `${this.sessionId.substring(0, 12)}...` : null,
      serverInfo: this.serverInfo,
      mcpUrl: this.mcpUrl,
      toolCount: this.tools.length,
    };
  }
}

// ============================================================
// 初始化
// ============================================================

let composioClient = null;
let composioMCPClient = null;

function getComposioClient() {
  if (!composioClient) {
    composioClient = new ComposioElectronClient();
  }
  return composioClient;
}

function getComposioMCPClient() {
  if (!composioMCPClient) {
    composioMCPClient = new ComposioMCPClient(COMPOSIO_MCP_URL);
  }
  return composioMCPClient;
}

// ============================================================
// MCP 初始化
// ============================================================

async function initializeComposioMCP() {
  const mcp = getComposioMCPClient();
  const result = await mcp.initialize();
  if (result.success) {
    // 初始化成功后立即获取工具列表
    await mcp.listTools();
  }
  return result;
}

// ============================================================
// IPC Handlers
// ============================================================

function registerComposioIPC() {
  const client = getComposioClient();
  const mcp = getComposioMCPClient();

  // ========== Composio API Handlers ==========

  // 获取 Composio 状态
  ipcMain.handle('composio:status', async () => {
    try {
      return await client.getStatus();
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // 列出工具包
  ipcMain.handle('composio:listToolkits', async (event, options) => {
    try {
      return await client.listToolkits(options || {});
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // 获取工具包详情
  ipcMain.handle('composio:getToolkit', async (event, slug) => {
    try {
      return await client.getToolkit(slug);
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // 搜索工具包
  ipcMain.handle('composio:search', async (event, query, category, limit) => {
    try {
      return await client.search(query, category, limit);
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // 执行工具
  ipcMain.handle('composio:execute', async (event, slug, params, app) => {
    try {
      return await client.execute(slug, params, app);
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // 获取连接列表
  ipcMain.handle('composio:getConnections', async () => {
    try {
      return await client.getConnections();
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // 发起连接
  ipcMain.handle('composio:connect', async (event, app, redirectUrl) => {
    try {
      return await client.connect(app, redirectUrl);
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // 获取分类
  ipcMain.handle('composio:getCategories', async () => {
    try {
      return await client.getCategories();
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // 获取热门工具包
  ipcMain.handle('composio:getPopular', async (event, limit) => {
    try {
      return await client.getPopular(limit || 50);
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // ========== Composio MCP Handlers ==========

  // MCP 状态
  ipcMain.handle('composio:mcp:status', async () => {
    try {
      return await mcp.getStatus();
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // MCP 初始化
  ipcMain.handle('composio:mcp:initialize', async () => {
    try {
      return await mcp.initialize();
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // MCP 列出工具
  ipcMain.handle('composio:mcp:listTools', async () => {
    try {
      return await mcp.listTools();
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  // MCP 调用工具
  ipcMain.handle('composio:mcp:callTool', async (event, toolName, args) => {
    try {
      return await mcp.callTool(toolName, args || {});
    } catch (error) {
      return { success: false, error: error.message };
    }
  });

  console.log('[Composio] IPC handlers registered (API + MCP)');
}

module.exports = {
  registerComposioIPC,
  getComposioClient,
  getComposioMCPClient,
  initializeComposioMCP,
};

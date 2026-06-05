"""
认证模块 - JWT Token 管理 + Redis 会话 + 用户/企业管理
龙虾星球共创联盟 v4.0
"""

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import jwt
from pydantic import BaseModel, Field

logger = logging.getLogger("openclaw.auth")

# ============================================================
# 配置常量
# ============================================================
JWT_SECRET = "lobster-planet-jwt-secret-key-2026"  # 生产环境应从环境变量读取
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72  # Token 有效期 72 小时
REFRESH_EXPIRY_DAYS = 30  # Refresh Token 有效期 30 天

# 企业版 License 密钥（简化版，生产环境应加密存储）
ENTERPRISE_LICENSE_KEY = "LP-ENT-2026"

# 数据存储路径
DATA_DIR = Path(__file__).parent.parent / "data"
USERS_FILE = DATA_DIR / "users.json"
ENTERPRISES_FILE = DATA_DIR / "enterprises.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"


# ============================================================
# Pydantic 数据模型
# ============================================================

class UserProfile(BaseModel):
    """用户信息"""
    id: str
    username: str
    email: str
    display_name: str = ""
    avatar: str = ""
    role: str = "user"  # user / admin / enterprise_admin / enterprise_user
    enterprise_id: Optional[str] = None
    enterprise_name: str = ""
    plan: str = "free"  # free / pro / enterprise
    created_at: str = ""
    last_login: str = ""
    is_active: bool = True

class Enterprise(BaseModel):
    """企业信息"""
    id: str
    name: str
    industry: str = ""
    size: str = ""  # small / medium / large / enterprise
    country: str = ""
    website: str = ""
    logo: str = ""
    license_key: str = ""
    plan: str = "enterprise"  # pro / enterprise / unlimited
    seats_total: int = 10
    seats_used: int = 0
    features: list = Field(default_factory=lambda: [
        "dashboard", "agents", "taskflows", "webhooks",
        "analytics", "reports", "team_collaboration",
        "custom_workflows", "api_access", "priority_support"
    ])
    admin_id: str = ""
    created_at: str = ""
    expires_at: str = ""  # License 过期时间
    is_active: bool = True

class RegisterRequest(BaseModel):
    """注册请求"""
    username: str
    email: str
    password: str
    display_name: str = ""
    plan: str = "free"

class EnterpriseRegisterRequest(BaseModel):
    """企业注册请求"""
    company_name: str
    admin_username: str
    admin_email: str
    password: str
    industry: str = ""
    size: str = ""
    country: str = ""
    website: str = ""
    plan: str = "enterprise"

class LoginRequest(BaseModel):
    """登录请求"""
    email: str
    password: str

class TokenResponse(BaseModel):
    """Token 响应"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict

class UserUpdateRequest(BaseModel):
    """用户信息更新请求"""
    display_name: Optional[str] = None
    avatar: Optional[str] = None

class PasswordChangeRequest(BaseModel):
    """修改密码请求"""
    old_password: str
    new_password: str


# ============================================================
# 密码哈希工具
# ============================================================

def hash_password(password: str) -> str:
    """SHA-256 密码哈希"""
    salt = "lobster-salt-2026"
    return hashlib.sha256(f"{salt}{password}{salt}".encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    return hash_password(password) == hashed


# ============================================================
# JWT Token 工具
# ============================================================

def create_access_token(user_id: str, enterprise_id: Optional[str] = None, role: str = "user") -> str:
    """创建访问 Token"""
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "role": role,
        "ent": enterprise_id,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
        "jti": uuid.uuid4().hex[:12],
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    """创建刷新 Token"""
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=REFRESH_EXPIRY_DAYS),
        "jti": uuid.uuid4().hex[:12],
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_token(token: str) -> Optional[dict]:
    """解码 Token"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.warning("Token expired")
        return None
    except jwt.InvalidTokenError:
        logger.warning("Invalid token")
        return None

def decode_refresh_token(token: str) -> Optional[dict]:
    """解码刷新 Token"""
    payload = decode_token(token)
    if payload and payload.get("type") == "refresh":
        return payload
    return None


# ============================================================
# 数据存储层（JSON 文件，生产环境可替换为 PostgreSQL）
# ============================================================

class DataStore:
    """轻量级 JSON 数据存储"""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _read(self, filepath: Path) -> dict:
        try:
            if filepath.exists():
                return json.loads(filepath.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Failed to read {filepath}: {e}")
        return {}

    def _write(self, filepath: Path, data: dict):
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_users(self) -> dict:
        return self._read(USERS_FILE)

    def save_users(self, users: dict):
        self._write(USERS_FILE, users)

    def get_enterprises(self) -> dict:
        return self._read(ENTERPRISES_FILE)

    def save_enterprises(self, enterprises: dict):
        self._write(ENTERPRISES_FILE, enterprises)

    def get_sessions(self) -> dict:
        return self._read(SESSIONS_FILE)

    def save_sessions(self, sessions: dict):
        self._write(SESSIONS_FILE, sessions)


# ============================================================
# 认证服务
# ============================================================

class AuthService:
    """认证服务核心类"""

    def __init__(self):
        self.store = DataStore()
        self._init_demo_data()

    def _init_demo_data(self):
        """初始化演示数据（首次运行）"""
        users = self.store.get_users()
        if not users:
            # 创建演示管理员账号
            admin_pass = hash_password("admin123")
            users = {
                "admin@lobster.planet": {
                    "id": "u-admin-001",
                    "username": "admin",
                    "email": "admin@lobster.planet",
                    "password": admin_pass,
                    "display_name": "系统管理员",
                    "avatar": "🦞",
                    "role": "admin",
                    "enterprise_id": None,
                    "enterprise_name": "",
                    "plan": "enterprise",
                    "created_at": datetime.utcnow().isoformat(),
                    "last_login": "",
                    "is_active": True,
                }
            }
            self.store.save_users(users)
            logger.info("Demo admin account created: admin@lobster.planet / admin123")

        enterprises = self.store.get_enterprises()
        if not enterprises:
            enterprises = {
                "ent-demo-001": {
                    "id": "ent-demo-001",
                    "name": "龙虾星球示范企业",
                    "industry": "跨境电商",
                    "size": "medium",
                    "country": "中国",
                    "website": "https://lobster.planet",
                    "logo": "🦞",
                    "license_key": ENTERPRISE_LICENSE_KEY,
                    "plan": "enterprise",
                    "seats_total": 50,
                    "seats_used": 0,
                    "features": [
                        "dashboard", "agents", "taskflows", "webhooks",
                        "analytics", "reports", "team_collaboration",
                        "custom_workflows", "api_access", "priority_support",
                        "white_label", "sso", "audit_log"
                    ],
                    "admin_id": "u-admin-001",
                    "created_at": datetime.utcnow().isoformat(),
                    "expires_at": (datetime.utcnow() + timedelta(days=365)).isoformat(),
                    "is_active": True,
                }
            }
            self.store.save_enterprises(enterprises)
            logger.info("Demo enterprise created: 龙虾星球示范企业")

    # ---------- 注册 ----------

    def register_user(self, req: RegisterRequest) -> dict:
        """用户注册"""
        users = self.store.get_users()

        # 检查邮箱是否已注册
        if req.email in users:
            return {"success": False, "error": "该邮箱已注册"}

        # 检查用户名是否已存在
        for u in users.values():
            if u["username"] == req.username:
                return {"success": False, "error": "该用户名已被使用"}

        user_id = f"u-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()
        user = {
            "id": user_id,
            "username": req.username,
            "email": req.email,
            "password": hash_password(req.password),
            "display_name": req.display_name or req.username,
            "avatar": "",
            "role": "user",
            "enterprise_id": None,
            "enterprise_name": "",
            "plan": req.plan or "free",
            "created_at": now,
            "last_login": now,
            "is_active": True,
        }
        users[req.email] = user
        self.store.save_users(users)

        logger.info(f"User registered: {req.email} (id={user_id})")
        return {"success": True, "user": self._sanitize_user(user)}

    def register_enterprise(self, req: EnterpriseRegisterRequest) -> dict:
        """企业注册"""
        users = self.store.get_users()
        enterprises = self.store.get_enterprises()

        # 检查管理员邮箱是否已注册
        if req.admin_email in users:
            return {"success": False, "error": "该管理员邮箱已注册"}

        # 检查企业名是否已存在
        for ent in enterprises.values():
            if ent["name"] == req.company_name:
                return {"success": False, "error": "该企业名称已被注册"}

        now = datetime.utcnow().isoformat()
        ent_id = f"ent-{uuid.uuid4().hex[:8]}"
        admin_id = f"u-ent-{uuid.uuid4().hex[:8]}"

        # 创建企业
        enterprise = {
            "id": ent_id,
            "name": req.company_name,
            "industry": req.industry,
            "size": req.size,
            "country": req.country,
            "website": req.website,
            "logo": "",
            "license_key": f"LP-ENT-{uuid.uuid4().hex[:8].upper()}",
            "plan": req.plan or "enterprise",
            "seats_total": 20,
            "seats_used": 1,
            "features": [
                "dashboard", "agents", "taskflows", "webhooks",
                "analytics", "reports", "team_collaboration",
                "custom_workflows", "api_access", "priority_support"
            ],
            "admin_id": admin_id,
            "created_at": now,
            "expires_at": (datetime.utcnow() + timedelta(days=365)).isoformat(),
            "is_active": True,
        }
        enterprises[ent_id] = enterprise
        self.store.save_enterprises(enterprises)

        # 创建管理员用户
        admin_user = {
            "id": admin_id,
            "username": req.admin_username,
            "email": req.admin_email,
            "password": hash_password(req.password),
            "display_name": req.admin_username,
            "avatar": "",
            "role": "enterprise_admin",
            "enterprise_id": ent_id,
            "enterprise_name": req.company_name,
            "plan": "enterprise",
            "created_at": now,
            "last_login": now,
            "is_active": True,
        }
        users[req.admin_email] = admin_user
        self.store.save_users(users)

        logger.info(f"Enterprise registered: {req.company_name} (id={ent_id}, admin={req.admin_email})")
        return {"success": True, "enterprise": enterprise, "user": self._sanitize_user(admin_user)}

    # ---------- 登录 ----------

    def login(self, req: LoginRequest) -> dict:
        """用户登录"""
        users = self.store.get_users()
        user = users.get(req.email)

        if not user:
            return {"success": False, "error": "账号不存在"}

        if not user.get("is_active", True):
            return {"success": False, "error": "账号已被禁用"}

        if not verify_password(req.password, user["password"]):
            return {"success": False, "error": "密码错误"}

        # 更新最后登录时间
        user["last_login"] = datetime.utcnow().isoformat()
        users[req.email] = user
        self.store.save_users(users)

        # 生成 Token
        access_token = create_access_token(
            user_id=user["id"],
            enterprise_id=user.get("enterprise_id"),
            role=user["role"]
        )
        refresh_token = create_refresh_token(user["id"])

        # 记录会话
        sessions = self.store.get_sessions()
        sessions[user["id"]] = {
            "user_id": user["id"],
            "access_token": access_token,
            "refresh_token": refresh_token,
            "login_at": user["last_login"],
            "expires_at": (datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)).isoformat(),
        }
        self.store.save_sessions(sessions)

        logger.info(f"User logged in: {req.email}")
        return {
            "success": True,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": JWT_EXPIRY_HOURS * 3600,
            "user": self._sanitize_user(user),
        }

    # ---------- Token 刷新 ----------

    def refresh_token(self, refresh_token: str) -> dict:
        """刷新访问 Token"""
        payload = decode_refresh_token(refresh_token)
        if not payload:
            return {"success": False, "error": "无效的刷新令牌"}

        user_id = payload["sub"]
        users = self.store.get_users()
        user = None
        for u in users.values():
            if u["id"] == user_id:
                user = u
                break

        if not user:
            return {"success": False, "error": "用户不存在"}

        new_access = create_access_token(
            user_id=user["id"],
            enterprise_id=user.get("enterprise_id"),
            role=user["role"]
        )

        # 更新会话
        sessions = self.store.get_sessions()
        if user_id in sessions:
            sessions[user_id]["access_token"] = new_access
            sessions[user_id]["expires_at"] = (datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)).isoformat()
            self.store.save_sessions(sessions)

        return {
            "success": True,
            "access_token": new_access,
            "token_type": "bearer",
            "expires_in": JWT_EXPIRY_HOURS * 3600,
        }

    # ---------- 获取用户信息 ----------

    def get_user(self, user_id: str) -> Optional[dict]:
        """根据 ID 获取用户"""
        users = self.store.get_users()
        for u in users.values():
            if u["id"] == user_id:
                return self._sanitize_user(u)
        return None

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """根据邮箱获取用户"""
        users = self.store.get_users()
        user = users.get(email)
        if user:
            return self._sanitize_user(user)
        return None

    # ---------- 企业管理 ----------

    def get_enterprise(self, ent_id: str) -> Optional[dict]:
        """获取企业信息"""
        enterprises = self.store.get_enterprises()
        return enterprises.get(ent_id)

    def get_enterprise_users(self, ent_id: str) -> list:
        """获取企业下所有用户"""
        users = self.store.get_users()
        result = []
        for u in users.values():
            if u.get("enterprise_id") == ent_id:
                result.append(self._sanitize_user(u))
        return result

    def add_enterprise_user(self, ent_id: str, email: str, username: str, password: str, role: str = "enterprise_user") -> dict:
        """企业管理员添加用户"""
        enterprises = self.store.get_enterprises()
        enterprise = enterprises.get(ent_id)
        if not enterprise:
            return {"success": False, "error": "企业不存在"}

        if enterprise["seats_used"] >= enterprise["seats_total"]:
            return {"success": False, "error": "企业席位已满，请联系升级"}

        users = self.store.get_users()
        if email in users:
            return {"success": False, "error": "该邮箱已注册"}

        user_id = f"u-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()
        user = {
            "id": user_id,
            "username": username,
            "email": email,
            "password": hash_password(password),
            "display_name": username,
            "avatar": "",
            "role": role,
            "enterprise_id": ent_id,
            "enterprise_name": enterprise["name"],
            "plan": "enterprise",
            "created_at": now,
            "last_login": "",
            "is_active": True,
        }
        users[email] = user
        self.store.save_users(users)

        enterprise["seats_used"] += 1
        enterprises[ent_id] = enterprise
        self.store.save_enterprises(enterprises)

        logger.info(f"Enterprise user added: {email} to {enterprise['name']}")
        return {"success": True, "user": self._sanitize_user(user)}

    def update_user(self, user_id: str, updates: dict) -> Optional[dict]:
        """更新用户信息"""
        users = self.store.get_users()
        for email, u in users.items():
            if u["id"] == user_id:
                for key, val in updates.items():
                    if key != "password" and key != "id" and key != "email":
                        u[key] = val
                users[email] = u
                self.store.save_users(users)
                return self._sanitize_user(u)
        return None

    def change_password(self, user_id: str, old_password: str, new_password: str) -> dict:
        """修改密码"""
        users = self.store.get_users()
        for email, u in users.items():
            if u["id"] == user_id:
                if not verify_password(old_password, u["password"]):
                    return {"success": False, "error": "原密码错误"}
                u["password"] = hash_password(new_password)
                users[email] = u
                self.store.save_users(users)
                return {"success": True}
        return {"success": False, "error": "用户不存在"}

    # ---------- 退出登录 ----------

    def logout(self, user_id: str):
        """退出登录"""
        sessions = self.store.get_sessions()
        if user_id in sessions:
            del sessions[user_id]
            self.store.save_sessions(sessions)
            logger.info(f"User logged out: {user_id}")

    # ---------- 验证 Token ----------

    def verify_access(self, token: str) -> Optional[dict]:
        """验证访问 Token 并返回用户信息"""
        payload = decode_token(token)
        if not payload:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        user = self.get_user(user_id)
        if not user:
            return None

        return {**user, "token_payload": payload}

    # ---------- 工具 ----------

    def _sanitize_user(self, user: dict) -> dict:
        """移除敏感字段"""
        return {k: v for k, v in user.items() if k != "password"}

    def get_all_users(self) -> list:
        """获取所有用户（管理员功能）"""
        users = self.store.get_users()
        return [self._sanitize_user(u) for u in users.values()]

    def get_all_enterprises(self) -> list:
        """获取所有企业（管理员功能）"""
        enterprises = self.store.get_enterprises()
        return list(enterprises.values())


# ============================================================
# 全局单例
# ============================================================

_auth_service: Optional[AuthService] = None

def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service

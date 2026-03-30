# OpenClaw 完整部署指南

> 本文档记录了在 Azure VM（Ubuntu）上部署 OpenClaw Gateway 的完整过程，包括网关配置、HTTPS 访问、GitHub Copilot 模型接入、飞书 Channel 对接。

---

## 目录

1. [环境信息](#1-环境信息)
2. [Gateway 基础配置与启动](#2-gateway-基础配置与启动)
3. [配置远程访问（LAN 绑定 + 端口）](#3-配置远程访问lan-绑定--端口)
4. [Azure NSG 防火墙放行](#4-azure-nsg-防火墙放行)
5. [配置 HTTPS 访问（Nginx + Let's Encrypt）](#5-配置-https-访问nginx--lets-encrypt)
6. [设备配对（Control UI）](#6-设备配对control-ui)
7. [配置 GitHub Copilot 作为 LLM Provider](#7-配置-github-copilot-作为-llm-provider)
8. [配置飞书（Feishu）Channel](#8-配置飞书feishu-channel)
9. [常用运维命令](#9-常用运维命令)

---

## 1. 环境信息

| 项目 | 值 |
|------|-----|
| 云平台 | Azure VM (Japan East) |
| 操作系统 | Ubuntu (Linux) |
| Node.js | v22.22.2 (通过 nvm 安装) |
| OpenClaw 版本 | 2026.3.24 |
| 公网 IP | `<your-public-ip>` |
| DNS 域名 | `<your-hostname>.cloudapp.azure.com` |
| Gateway 端口 | 18000 |

---

## 2. Gateway 基础配置与启动

### 2.1 配置文件位置

主配置文件：`~/.openclaw/openclaw.json`

### 2.2 设置 gateway.mode

OpenClaw Gateway 启动时要求配置 `gateway.mode`，否则会报错：

```
Gateway start blocked: set gateway.mode=local (current: unset)
```

**修复方法：**

```bash
# 方法一：命令行设置
openclaw config set gateway.mode local

# 方法二：直接编辑配置文件 ~/.openclaw/openclaw.json
# 在 "gateway" 字段中添加：
#   "mode": "local"
```

### 2.3 配置 auth.token

远程访问时必须配置认证 token：

```bash
# 自动生成安全令牌
openclaw doctor --generate-gateway-token

# 或手动设置
openclaw config set gateway.token <你的安全令牌>
```

配置文件中的对应部分：

```json
{
  "gateway": {
    "mode": "local",
    "auth": {
      "mode": "token",
      "token": "<你的安全令牌>"
    }
  }
}
```

### 2.4 启动/重启 Gateway

```bash
# 启动
openclaw gateway start

# 重启
openclaw gateway restart

# 查看状态
openclaw gateway status

# 查看日志
openclaw logs --follow
```

---

## 3. 配置远程访问（LAN 绑定 + 端口）

### 3.1 设置 bind 为 lan

默认 `bind=loopback` 只允许本机访问。改为 `lan` 允许外部访问：

编辑 `~/.openclaw/openclaw.json`：

```json
{
  "gateway": {
    "mode": "local",
    "bind": "lan",
    "port": 18000
  }
}
```

### 3.2 同步更新 systemd service 文件

⚠️ **重要**：`openclaw.json` 中改端口后，还需要同步修改 systemd service 文件，否则不会生效！

Service 文件中 `--port` 参数和 `OPENCLAW_GATEWAY_PORT` 环境变量的优先级高于配置文件。

```bash
# 编辑 service 文件，将端口从 18789 改为 18000
sed -i 's/--port 18789/--port 18000/g; s/OPENCLAW_GATEWAY_PORT=18789/OPENCLAW_GATEWAY_PORT=18000/g' \
  ~/.config/systemd/user/openclaw-gateway.service

# 重新加载 systemd 并重启
systemctl --user daemon-reload
systemctl --user restart openclaw-gateway.service
```

同时更新配置文件中的端口：

```bash
openclaw config set gateway.port 18000
```

### 3.3 验证端口监听

```bash
# 检查端口是否在监听
ss -tlnp | grep 18000

# 测试本地访问
curl -s -o /dev/null -w "HTTP %{http_code}" http://127.0.0.1:18000
# 期望输出：HTTP 200
```

---

## 4. Azure NSG 防火墙放行

在 Azure 门户中，找到 VM 关联的 NSG（网络安全组），添加 **Inbound** 规则：

| 规则名 | 协议 | 方向 | 端口 | 源 | 操作 |
|--------|------|------|------|-----|------|
| openclaw | TCP | Inbound | 18000 | * | Allow |
| HTTP | TCP | Inbound | 80 | * | Allow |
| HTTPS | TCP | Inbound | 443 | * | Allow |

> 80 和 443 端口是 Let's Encrypt 证书验证和 HTTPS 访问所需。

---

## 5. 配置 HTTPS 访问（Nginx + Let's Encrypt）

### 5.1 为什么需要 HTTPS

OpenClaw Control UI 需要浏览器的 **Secure Context**（安全上下文）才能使用设备身份功能。通过 HTTP + 公网 IP 访问会报错：

```
control ui requires device identity (use HTTPS or localhost secure context)
```

### 5.2 给 Azure VM 分配 DNS 名称

1. 打开 [Azure 门户](https://portal.azure.com)
2. 进入 VM → **Networking** → 点击**公网 IP 地址**
3. 在公网 IP 页面 → **Configuration**
4. 填写 **DNS name label**（如 `bocchi`）
5. 点 **Save**

获得域名：`<your-hostname>.cloudapp.azure.com`

验证 DNS 解析：

```bash
dig +short <your-hostname>.cloudapp.azure.com
# 期望输出：<your-public-ip>
```

### 5.3 安装 Nginx 和 Certbot

```bash
sudo apt-get update -qq
sudo apt-get install -y -qq nginx certbot python3-certbot-nginx
```

### 5.4 配置 Nginx 反向代理

创建 Nginx 配置文件：

```bash
cat > /tmp/openclaw-nginx.conf << 'EOF'
server {
    listen 80;
    server_name <your-hostname>.cloudapp.azure.com;

    location / {
        proxy_pass http://127.0.0.1:18000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# 部署配置
sudo cp /tmp/openclaw-nginx.conf /etc/nginx/sites-available/openclaw
sudo ln -sf /etc/nginx/sites-available/openclaw /etc/nginx/sites-enabled/openclaw
sudo rm -f /etc/nginx/sites-enabled/default

# 测试并启动
sudo nginx -t
sudo systemctl start nginx
sudo systemctl enable nginx
```

### 5.5 申请 Let's Encrypt 免费 SSL 证书

```bash
sudo certbot --nginx \
  -d <your-hostname>.cloudapp.azure.com \
  --non-interactive \
  --agree-tos \
  --email your-email@example.com \
  --redirect
```

成功后输出：

```
Successfully received certificate.
Certificate is saved at: /etc/letsencrypt/live/<your-hostname>.cloudapp.azure.com/fullchain.pem
Key is saved at:         /etc/letsencrypt/live/<your-hostname>.cloudapp.azure.com/privkey.pem
```

> 证书有效期 90 天，Certbot 会自动续期。

### 5.6 更新 OpenClaw allowedOrigins

编辑 `~/.openclaw/openclaw.json`，在 `gateway.controlUi.allowedOrigins` 中添加 HTTPS 域名：

```json
{
  "gateway": {
    "controlUi": {
      "allowedOrigins": [
        "http://localhost:18000",
        "http://127.0.0.1:18000",
        "https://<your-hostname>.cloudapp.azure.com"
      ]
    }
  }
}
```

### 5.7 验证 HTTPS 访问

```bash
curl -s -o /dev/null -w "HTTP %{http_code}" https://<your-hostname>.cloudapp.azure.com
# 期望输出：HTTP 200
```

浏览器打开 `https://<your-hostname>.cloudapp.azure.com` 即可访问 Control UI。

---

## 6. 设备配对（Control UI）

首次从新设备/浏览器访问 Control UI 时需要完成设备配对。

### 6.1 查看待配对设备

```bash
openclaw devices list
```

输出中 **Pending** 部分显示等待批准的设备。

### 6.2 批准配对请求

```bash
openclaw devices approve <Request ID>

# 示例：
openclaw devices approve 8e2dc126-f9bc-4c3e-846a-cc328566fda7
```

### 6.3 其他设备管理命令

```bash
# 拒绝配对
openclaw devices reject <Request ID>

# 移除已配对设备
openclaw devices remove <Device ID>

# 清除所有配对
openclaw devices clear
```

---

## 7. 配置 GitHub Copilot 作为 LLM Provider

使用 GitHub Copilot 订阅代理访问 Claude、GPT 等模型，无需单独的 API Key。

### 7.1 前置条件

- 拥有有效的 GitHub Copilot 订阅（个人版/企业版）

### 7.2 登录 GitHub Copilot

```bash
openclaw models auth login-github-copilot
```

按提示操作：
1. 终端显示授权 URL 和设备码，例如：
   ```
   Visit: https://github.com/login/device
   Code: XXXX-XXXX
   ```
2. 在浏览器打开 https://github.com/login/device
3. 输入设备码并授权
4. 回到终端等待完成，显示 `Done` 即成功

### 7.3 设置默认模型

⚠️ **重要**：模型 ID 必须使用 `github-copilot/` 前缀，而不是 `anthropic/`！

```bash
# 设置为 Claude Opus 4.6
openclaw models set github-copilot/claude-opus-4.6
```

**错误示范**（会报 "No API key found for provider anthropic"）：

```bash
# ❌ 不要用这个！
openclaw models set anthropic/claude-opus-4-6
```

### 7.4 查看可用的 Copilot 模型

```bash
openclaw models list --all 2>&1 | grep 'github-copilot'
```

常见可用模型：

| 模型 ID | 说明 |
|---------|------|
| `github-copilot/claude-opus-4.6` | Claude Opus 4.6 |
| `github-copilot/claude-sonnet-4.6` | Claude Sonnet 4.6 |
| `github-copilot/claude-sonnet-4.5` | Claude Sonnet 4.5 |
| `github-copilot/claude-haiku-4.5` | Claude Haiku 4.5 |

### 7.5 验证模型配置

```bash
openclaw models status
```

确认输出中：
- `Default` 显示 `github-copilot/claude-opus-4.6`
- `Missing auth` 中**没有**你使用的 provider
- `github-copilot` 显示 `Premium 100% left`

---

## 8. 配置飞书（Feishu）Channel

### 8.1 在飞书开放平台创建机器人

1. 登录 [飞书开放平台](https://open.feishu.cn/app)
2. 点击「创建企业自建应用」
3. 填写应用名称、描述、上传图标
4. 记录 **App ID**（格式 `cli_xxx`）和 **App Secret**

### 8.2 配置应用权限

在「权限管理」中添加以下权限：

| 权限 | 说明 | 必须 |
|------|------|------|
| `im:message` | 消息读写 | ✅ |
| `im:message:send_as_bot` | 以机器人身份发送消息 | ✅ |
| `im:message:send` | 发送消息 | ✅ |
| `im:message.group_at_msg:readonly` | 群 @消息 | ✅ |
| `im:message.p2p_msg:readonly` | 私聊消息 | ✅ |
| `im:resource` | 文件资源 | 推荐 |
| `contact:contact.base:readonly` | 通讯录基础信息（用户身份识别） | ✅ |
| `contact:user.employee_id:readonly` | 员工 ID | 推荐 |

> ⚠️ 缺少 `im:message:send_as_bot` 会导致机器人能收消息但无法回复！
> ⚠️ 缺少 `contact:contact.base:readonly` 会导致无法识别用户身份！

### 8.3 启用机器人能力

「应用能力」→ 添加「机器人」→ 设置机器人名称

### 8.4 配置事件订阅（选长连接）

1. 「事件与回调」→ 选择 **「长连接 WebSocket」** 方式
2. 添加事件：`im.message.receive_v1`（接收消息）

> 长连接方式无需公网 Webhook，更简单安全。

### 8.5 发布应用

「版本管理与发布」→ 创建版本 → 提交发布

> 企业自建应用通常自动审批。**每次修改权限后都需要重新创建版本并发布**，否则权限不生效！

### 8.6 在 OpenClaw 中添加飞书 Channel

编辑 `~/.openclaw/openclaw.json`，添加 `channels` 配置：

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "<your-feishu-app-id>",
      "appSecret": "<你的 App Secret>",
      "domain": "feishu",
      "groupAccess": "open"
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `appId` | 飞书开放平台的 App ID |
| `appSecret` | 飞书开放平台的 App Secret |
| `domain` | 国内用 `"feishu"`，国际版用 `"lark"` |
| `groupAccess` | `"open"` 开放 / `"allowlist"` 白名单 / `"disabled"` 禁用群聊 |

### 8.7 重启 Gateway

```bash
openclaw gateway restart
```

### 8.8 验证飞书连接

```bash
# 查看日志确认 WebSocket 连接成功
openclaw logs --follow | grep feishu
```

期望看到：

```
feishu[default]: WebSocket client started
[ws] ws client ready
```

### 8.9 飞书用户配对

首次私聊机器人时需要配对：

```bash
# 查看待配对列表
openclaw pairing list feishu

# 批准配对（使用输出中的 Code）
openclaw pairing approve feishu <配对码>

# 示例：
openclaw pairing approve feishu 3EDRDE3K
```

配对完成后，再次发消息即可正常对话。

---

## 9. 常用运维命令

### Gateway 管理

```bash
openclaw gateway status          # 查看状态
openclaw gateway restart         # 重启
openclaw logs --follow           # 实时日志
openclaw doctor                  # 健康检查
openclaw doctor --fix            # 自动修复
```

### 模型管理

```bash
openclaw models status           # 当前模型状态
openclaw models list --all       # 列出所有可用模型
openclaw models set <model-id>   # 设置默认模型
```

### 设备管理

```bash
openclaw devices list            # 列出所有设备
openclaw devices approve <id>    # 批准配对
openclaw devices reject <id>     # 拒绝配对
```

### 飞书配对

```bash
openclaw pairing list feishu     # 查看飞书待配对
openclaw pairing approve feishu <code>  # 批准飞书配对
```

### Systemd 服务管理

```bash
systemctl --user status openclaw-gateway.service   # 服务状态
systemctl --user restart openclaw-gateway.service   # 重启服务
systemctl --user daemon-reload                      # 重载配置
journalctl --user -u openclaw-gateway.service -f    # 实时日志
```

### SSL 证书管理

```bash
sudo certbot certificates                    # 查看证书状态
sudo certbot renew --dry-run                 # 测试续期
sudo certbot renew                           # 手动续期
```

---

## 附录：最终配置文件参考

`~/.openclaw/openclaw.json` 完整配置：

```json
{
  "auth": {
    "profiles": {
      "github-copilot:github": {
        "provider": "github-copilot",
        "mode": "token"
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "github-copilot/claude-opus-4.6"
      },
      "compaction": {
        "mode": "safeguard"
      },
      "maxConcurrent": 4,
      "subagents": {
        "maxConcurrent": 8
      }
    }
  },
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "<your-feishu-app-id>",
      "appSecret": "<你的 App Secret>",
      "domain": "feishu",
      "groupAccess": "open"
    }
  },
  "gateway": {
    "port": 18000,
    "mode": "local",
    "bind": "lan",
    "controlUi": {
      "allowedOrigins": [
        "http://localhost:18000",
        "http://127.0.0.1:18000",
        "https://<your-hostname>.cloudapp.azure.com"
      ]
    },
    "auth": {
      "mode": "token",
      "token": "<你的网关令牌>"
    }
  }
}
```

---

*文档生成时间：2026-03-26*

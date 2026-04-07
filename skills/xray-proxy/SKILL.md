---
name: xray-proxy
description: "配置和管理 Xray 代理服务器。支持 VLESS + WS + TLS（域名方案）和 VLESS + REALITY（纯 IP 方案）。
  用于：(1) 从零搭建 Xray 代理 (2) 配置 nginx 反代 + TLS (3) 配置 REALITY 伪装 (4) 排查连接问题 (5) 生成客户端配置 (6) 路由器透明代理配置指导。
  触发词：代理、proxy、Xray、V2Ray、VLESS、翻墙、科学上网、梯子、REALITY"
---

# Xray Proxy 配置技能

搭建和管理 Xray 代理，覆盖两种主流方案。

## 方案对比

| | 域名 + WS + TLS | 纯 IP + REALITY |
|---|---|---|
| 需要域名 | ✅ | ❌ |
| 需要证书 | ✅ Let's Encrypt | ❌ 借用目标站 |
| 隐蔽性 | 🟡 域名可被关联 | 🟢 伪装大站流量 |
| 被探测时 | 返回自己的网站 | 返回伪装目标真实内容 |
| CDN 支持 | ✅ 可套 CF | ❌ |
| 配置复杂度 | 中 | 略高 |

## 方案 A：VLESS + WebSocket + TLS + nginx

### 前置条件
- 一台 VPS（有公网 IP）
- 一个域名（A 记录指向 VPS IP）
- nginx 已安装

### 步骤

#### 1. 安装 Xray

```bash
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
xray version  # 确认安装
```

#### 2. 生成 UUID

```bash
xray uuid
# 记下输出，后面要用
```

#### 3. 配置 Xray 服务端

编辑 `/usr/local/etc/xray/config.json`：

```json
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log"
  },
  "inbounds": [{
    "tag": "vless-ws",
    "listen": "127.0.0.1",
    "port": 10086,
    "protocol": "vless",
    "settings": {
      "clients": [{ "id": "<YOUR_UUID>", "level": 0 }],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "ws",
      "wsSettings": { "path": "/<RANDOM_PATH>" }
    }
  }],
  "outbounds": [
    { "tag": "direct", "protocol": "freedom" },
    { "tag": "block", "protocol": "blackhole" }
  ]
}
```

> `<RANDOM_PATH>` 建议用 `openssl rand -hex 8` 生成随机路径。

#### 4. 配置 nginx 反代

在 nginx server block 中添加（假设已有 SSL）：

```nginx
location /<RANDOM_PATH> {
    proxy_pass http://127.0.0.1:10086;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
}
```

#### 5. 申请 TLS 证书

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your.domain.com
# Certbot 自动配置 nginx SSL 并设置自动续期
```

#### 6. 启动

```bash
sudo systemctl enable xray
sudo systemctl start xray
sudo nginx -t && sudo systemctl reload nginx
```

## 方案 B：VLESS + REALITY（纯 IP，无需域名）

### 步骤

#### 1. 安装 Xray（同方案 A）

#### 2. 生成密钥对和 shortId

```bash
xray uuid           # 生成 UUID
xray x25519         # 生成 privateKey 和 publicKey
openssl rand -hex 4 # 生成 shortId
```

#### 3. 选择伪装目标（dest）

在 VPS 上测试候选目标延迟：

```bash
curl -so /dev/null -w '%{time_total}\n' https://www.microsoft.com
curl -so /dev/null -w '%{time_total}\n' https://www.apple.com
curl -so /dev/null -w '%{time_total}\n' https://www.samsung.com
# 选延迟最低的
```

**选择原则**：
- 大厂网站（CDN 节点多，流量特征不被针对）
- 目标 IP 与 VPS IP 在同一地区（避免 SNI/IP 地理不匹配）
- 支持 TLS 1.3 + H2

#### 4. 配置 Xray 服务端

```json
{
  "log": { "loglevel": "warning" },
  "inbounds": [{
    "listen": "0.0.0.0",
    "port": 443,
    "protocol": "vless",
    "settings": {
      "clients": [{
        "id": "<YOUR_UUID>",
        "flow": "xtls-rprx-vision"
      }],
      "decryption": "none"
    },
    "streamSettings": {
      "network": "tcp",
      "security": "reality",
      "realitySettings": {
        "dest": "www.microsoft.com:443",
        "serverNames": ["www.microsoft.com"],
        "privateKey": "<YOUR_PRIVATE_KEY>",
        "shortIds": ["<YOUR_SHORT_ID>"]
      }
    }
  }],
  "outbounds": [
    { "tag": "direct", "protocol": "freedom" }
  ]
}
```

#### 5. 客户端配置要点

```json
{
  "serverName": "www.microsoft.com",
  "publicKey": "<对应服务端 privateKey 的公钥>",
  "shortId": "<与服务端匹配>",
  "fingerprint": "chrome"
}
```

> `fingerprint` 务必设置为 `chrome`/`safari`/`firefox`，不要留空或用 `random`。

## 排查指南

### 连不上

```bash
# 1. 检查 Xray 运行状态
sudo systemctl status xray

# 2. 查看日志
sudo journalctl -u xray -f
# 或
sudo tail -f /var/log/xray/error.log

# 3. 检查端口监听
ss -tlnp | grep -E '10086|443'

# 4. 测试 nginx 反代（方案 A）
curl -I -H "Connection: Upgrade" -H "Upgrade: websocket" \
  https://your.domain.com/<PATH>
```

### 晚高峰卡顿

```bash
# 检查线路类型
traceroute -I <VPS_IP>
# 202.97.x.x = 普通 163 骨干（晚上大概率卡）
# 59.43.x.x = CN2（稳定）

# 测试丢包
mtr -r -c 100 <VPS_IP>
```

**晚高峰卡顿通常是线路问题，不是协议问题。** 解法：换 CN2 GIA 线路 VPS 或加中转。

### 路由器透明代理（fancyss 等）

⚠️ **不能直接导入 PC 客户端的 json 配置！**

路由器透明代理插件用 TPROXY/iptables redirect，与 PC 客户端的 socks5/http inbound 模式不同。必须通过插件界面填写参数，让插件自动生成正确配置。

## 注意事项

- Let's Encrypt 证书 90 天自动续期，**指纹会变**，不要配置 `pinnedPeerCertSha256`
- REALITY 的 `dest` 不影响数据传输路径（流量走的是 客户端→VPS，不经过伪装目标）
- Xray 调试后记得把 loglevel 改回 `warning`（`info` 会写大量日志）
- UUID、密钥等敏感信息不要写入版本控制或聊天记录

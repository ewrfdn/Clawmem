---
name: xray-proxy
description: "Xray 代理配置技能。方案：VMess + WebSocket + TLS，复用现有 nginx + Let's Encrypt 证书。
  包含：服务端配置、nginx 反代、Clash 订阅、systemd 管理、客户端导入链接生成、排查指南。
  触发词：代理、proxy、Xray、V2Ray、VMess、Clash、Shadowrocket"
---

# Xray Proxy 配置技能

## 架构概览

```
客户端 (Clash / Shadowrocket / V2rayN / ...)
  │
  │  VMess + WebSocket + TLS (443)
  ▼
┌──────────────────────────────────────────┐
│  Nginx (TLS 终止 + 反向代理)              │
│  <DOMAIN>                                │
│                                          │
│  /api/          → 127.0.0.1:8000  (API)  │
│  /hako.         → 127.0.0.1:50051 (gRPC) │
│  /<WS_PATH>     → 127.0.0.1:10086 (Xray) │
│  /sub/<TOKEN>/  → subscribe/ (订阅文件)   │
│  /              → ui/dist (SPA)          │
└──────────────────────────────────────────┘
         │
         ▼
┌──────────────────┐
│  Xray Server     │
│  127.0.0.1:10086 │
│  VMess + WS      │
└──────────────────┘
```

Xray 与业务服务共享同一个 nginx + 域名 + TLS 证书，通过不同 URL 路径区分流量。

## 部署参数

| 项目 | 值 |
|------|-----|
| 协议 | VMess（兼容所有客户端，含原版 Clash） |
| 传输 | WebSocket |
| TLS | Let's Encrypt (nginx 终止) |
| Xray 监听 | `127.0.0.1:10086` |
| WS 路径 | `/<RANDOM_PATH>`（随机生成） |
| 订阅路径 | `/sub/<TOKEN>/clash.yaml` |

> UUID、WS 路径、订阅 Token 等敏感信息存储在服务端配置中，不入版本控制。

## 服务端配置

### Xray 配置

路径：`/usr/local/etc/xray/config.json`

```json
{
  "log": {
    "loglevel": "warning",
    "access": "/var/log/xray/access.log",
    "error": "/var/log/xray/error.log"
  },
  "inbounds": [{
    "tag": "vmess-ws",
    "listen": "127.0.0.1",
    "port": 10086,
    "protocol": "vmess",
    "settings": {
      "clients": [{ "id": "<UUID>", "alterId": 0 }]
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

> `alterId: 0` 启用 AEAD 加密（Xray 推荐，兼容所有新版客户端）。

### Nginx 反代配置

路径：`/etc/nginx/sites-enabled/hako`

#### WebSocket 反代（Xray 流量）

```nginx
location /<RANDOM_PATH> {
    proxy_pass http://127.0.0.1:10086;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

> 关键：`proxy_http_version 1.1` + `Upgrade/Connection` 头是 WebSocket 反代必需的。

#### Clash 订阅端点

```nginx
location /sub/<TOKEN> {
    alias /path/to/subscribe/;
    default_type "text/yaml; charset=utf-8";
    add_header Content-Disposition "attachment; filename=clash.yaml";
    add_header Subscription-Userinfo "upload=0; download=0; total=107374182400; expire=0";
}
```

> Token 使用 `openssl rand -hex 16` 生成，防止被扫描发现。

#### 建议的超时配置

在 server 块中添加：

```nginx
keepalive_timeout 3600s;
```

所有 proxy/grpc location 的超时也建议设为 3600s：

```nginx
proxy_connect_timeout 3600s;
proxy_send_timeout 3600s;
proxy_read_timeout 3600s;
```

### Systemd 服务

Xray 使用官方安装脚本的 systemd unit：`/etc/systemd/system/xray.service`

```ini
[Unit]
Description=Xray Service
After=network.target nss-lookup.target

[Service]
User=nobody
ExecStart=/usr/local/bin/xray run -config /usr/local/etc/xray/config.json
Restart=on-failure
LimitNOFILE=1000000

[Install]
WantedBy=multi-user.target
```

## 从零搭建步骤

### 1. 安装 Xray

```bash
curl -L -o /tmp/install-xray.sh https://github.com/XTLS/Xray-install/raw/main/install-release.sh
sudo bash /tmp/install-xray.sh install
xray version  # 确认安装
```

### 2. 生成密钥

```bash
xray uuid              # 生成 UUID
openssl rand -hex 8    # 生成随机 WS 路径
openssl rand -hex 16   # 生成订阅 Token
```

### 3. 写入 Xray 配置

将上面的 JSON 模板写入 `/usr/local/etc/xray/config.json`，替换 `<UUID>` 和 `<RANDOM_PATH>`。

### 4. 创建 Clash 订阅文件

创建 `subscribe/clash.yaml`，模板如下：

```yaml
port: 7890
socks-port: 7891
allow-lan: false
mode: rule
log-level: info
external-controller: 127.0.0.1:9090

dns:
  enable: true
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  nameserver:
    - https://dns.alidns.com/dns-query
    - https://doh.pub/dns-query
  fallback:
    - https://1.1.1.1/dns-query
    - https://8.8.8.8/dns-query
  fallback-filter:
    geoip: true
    geoip-code: CN

proxies:
  - name: Proxy-Node
    type: vmess
    server: <DOMAIN>
    port: 443
    uuid: <UUID>
    alterId: 0
    cipher: auto
    tls: true
    udp: true
    servername: <DOMAIN>
    network: ws
    ws-opts:
      path: /<RANDOM_PATH>

proxy-groups:
  - name: Proxy
    type: select
    proxies:
      - Proxy-Node
      - DIRECT

rules:
  # 私有地址直连
  - IP-CIDR,127.0.0.0/8,DIRECT
  - IP-CIDR,192.168.0.0/16,DIRECT
  - IP-CIDR,10.0.0.0/8,DIRECT
  - IP-CIDR,172.16.0.0/12,DIRECT
  # 国内直连
  - GEOIP,CN,DIRECT
  # 兜底代理
  - MATCH,Proxy
```

> 可根据需要添加更多域名规则（参考 subscribe/clash.yaml 中的完整规则集）。

### 5. 配置 Nginx

在 nginx server 块中添加 WebSocket 反代 location 和订阅端点 location（见上文模板）。

### 6. 验证并启动

```bash
sudo nginx -t                        # 测试 nginx 配置
sudo systemctl enable xray           # 开机自启
sudo systemctl restart xray          # 启动 Xray
sudo systemctl reload nginx          # 重载 nginx
ss -tlnp | grep 10086               # 确认 Xray 监听
```

### 7. 生成客户端订阅链接

搭建完成后，需要生成客户端可导入的链接。

#### 生成 Clash 订阅 URL

Clash 通过 URL 导入 YAML 配置文件，订阅文件已在步骤 4 创建并通过 nginx 提供：

```
https://<DOMAIN>/sub/<TOKEN>/clash.yaml
```

#### 生成 VMess 导入链接（Shadowrocket / V2rayN / V2rayNG）

VMess 分享链接 = `vmess://` + Base64 编码的 JSON，**JSON 必须是紧凑格式（无空格）**：

```bash
# 替换变量后执行
DOMAIN="your.domain.com"
UUID="your-uuid-here"
WS_PATH="/your-random-path"
NODE_NAME="My-Proxy"

# 生成链接
echo -n "vmess://$(echo -n "{\"v\":\"2\",\"ps\":\"${NODE_NAME}\",\"add\":\"${DOMAIN}\",\"port\":\"443\",\"id\":\"${UUID}\",\"aid\":\"0\",\"net\":\"ws\",\"type\":\"none\",\"host\":\"${DOMAIN}\",\"path\":\"${WS_PATH}\",\"tls\":\"tls\"}" | base64 -w 0)"
```

输出示例：
```
vmess://eyJ2IjoiMiIsInBzIjoiTXktUHJveHkiLCJhZGQiOiJ5b3VyLmRv...
```

> ⚠️ **注意**：JSON 必须紧凑（`"v":"2"` 而非 `"v": "2"`），否则 Shadowrocket 无法识别。

#### 快速验证链接是否正确

```bash
# 将 vmess:// 后面的部分解码验证
echo "eyJ2IjoiMi..." | base64 -d
# 应输出完整的 JSON，检查各字段是否正确
```

## 客户端配置

### Clash（推荐，全平台兼容）

订阅 URL：
```
https://<DOMAIN>/sub/<TOKEN>/clash.yaml
```

导入方式：**Profiles** → **Import from URL** → 粘贴链接 → **Download**

支持客户端：Clash for Windows / ClashX / Clash Verge / Clash Meta（均兼容 VMess）

### Shadowrocket (iOS) / V2rayN (Windows) / V2rayNG (Android)

使用上面生成的 `vmess://` 链接，导入方式：

- **Shadowrocket**：复制链接 → 打开 App → 自动识别，或点击 **+** → **从剪贴板导入**
- **V2rayN**：从剪贴板导入 / 扫描二维码
- **V2rayNG**：从剪贴板导入 / 扫描二维码

VMess 链接的 JSON 字段说明：

```json
{
  "v": "2",                    // 协议版本，固定为 2
  "ps": "节点名称",            // 显示名称
  "add": "<DOMAIN>",          // 服务器地址
  "port": "443",              // 端口
  "id": "<UUID>",             // UUID
  "aid": "0",                 // alterId，0 = AEAD 加密
  "net": "ws",                // 传输协议
  "type": "none",             // 伪装类型
  "host": "<DOMAIN>",         // WS Host 头
  "path": "/<RANDOM_PATH>",   // WS 路径
  "tls": "tls"                // TLS 开启
}
```

### 手动配置参数

| 参数 | 值 |
|------|-----|
| 协议 | VMess |
| 地址 | `<DOMAIN>` |
| 端口 | `443` |
| UUID | `<UUID>` |
| alterId | `0` |
| 加密 | `auto` |
| 传输 | WebSocket |
| WS 路径 | `/<RANDOM_PATH>` |
| TLS | 开启 |
| SNI | `<DOMAIN>` |

## 日常运维

### 重启服务

```bash
sudo systemctl restart xray
sudo systemctl restart nginx
sudo systemctl restart hako-server
```

### 查看状态

```bash
systemctl status xray --no-pager
systemctl status nginx --no-pager
systemctl status hako-server --no-pager
```

### 查看日志

```bash
sudo tail -f /var/log/xray/error.log     # Xray 错误日志
sudo tail -f /var/log/xray/access.log    # Xray 访问日志
sudo tail -f /var/log/nginx/error.log    # Nginx 错误日志
sudo journalctl -u hako-server -f        # HAKO 日志
```

### 更新 Xray

```bash
curl -L -o /tmp/install-xray.sh https://github.com/XTLS/Xray-install/raw/main/install-release.sh
sudo bash /tmp/install-xray.sh install
sudo systemctl restart xray
```

### 添加新用户

编辑 `/usr/local/etc/xray/config.json`，在 `clients` 数组中添加新 UUID：

```json
"clients": [
  { "id": "<EXISTING_UUID>", "alterId": 0 },
  { "id": "<NEW_UUID>", "alterId": 0 }
]
```

然后 `sudo systemctl restart xray`。

## 排查指南

### 连不上

```bash
# 1. 检查 Xray 状态
sudo systemctl status xray

# 2. 检查端口
ss -tlnp | grep 10086

# 3. 测试 WebSocket 反代
curl -I -H "Connection: Upgrade" -H "Upgrade: websocket" \
  https://<DOMAIN>/<RANDOM_PATH>
# 应返回 101 Switching Protocols（或 400，但不应是 404/502）

# 4. 检查 Xray 日志
sudo tail -20 /var/log/xray/error.log
```

### 连接断开 / 超时

nginx 所有超时已设为 3600s。如果仍断连，可能是：

1. **云平台 TCP 空闲超时**（如 Azure 默认 4 分钟）→ 客户端开启 keepalive
2. **nginx 不转发 HTTP/2 ping 帧**（旧版问题）→ 已通过 `keepalive_timeout 3600s` 缓解

### 速度慢 / 晚高峰卡

```bash
traceroute -I <SERVER_IP>
# 202.97.x.x = 普通 163 骨干（晚高峰可能卡）
# 59.43.x.x = CN2（稳定）

mtr -r -c 100 <SERVER_IP>
```

> 晚高峰卡顿通常是线路问题，不是协议问题。

## 安全注意事项

- UUID、WS 路径、订阅 Token 等敏感信息**不要提交到 Git**
- WS 路径和订阅路径使用随机字符串，避免被扫描发现
- 定期检查 `/var/log/xray/access.log` 是否有异常连接
- Let's Encrypt 证书由 Certbot 自动续期，无需手动管理
- 调试完毕后将 `loglevel` 改回 `warning`（`info` 会写大量日志）

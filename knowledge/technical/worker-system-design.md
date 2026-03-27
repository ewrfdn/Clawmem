# Worker 系统设计文档

> 基于 2026-03-26 ~ 2026-03-27 与 Sakana 的讨论整理。
> 这份文档是未来实现 Worker 系统的核心参考。

---

## 一、需求背景

### 场景
Sakana 希望 OpenClaw（Claw 机器）能操控多台远端机器（Worker），每台 Worker 只暴露有限的能力，例如：
- Worker A：下载任务（BT/HTTP）
- Worker B：视频转码
- Worker C：OCR 识别

### 核心要求
1. Claw 在公网，Worker 可以在私网
2. 每台 Worker 只暴露**受限的能力**（不是命令）
3. Capability-based 安全模型
4. Worker 尽可能轻量，不需要安装完整 OpenClaw（628MB）

### 架构概览

```
┌──────────────────────┐              ┌──────────────────────────┐
│  OpenClaw Gateway    │              │  Worker (私网)            │
│  (公网 VPS)          │   WebSocket  │                          │
│                      │←────────────│  Worker Agent (轻量)      │
│  RSS 搜索/调度决策   │              │    ├─ Plugin 能力层       │
│                      │─────────────→│    ├─ 白名单命令执行      │
│                      │              │    ├─ Workspace 文件隔离  │
│                      │              │    └─ 资源 Quota          │
└──────────────────────┘              └──────────────────────────┘
```

**关键：Worker 主动连接 Gateway（WebSocket），不是 Gateway 连 Worker，所以私网 NAT 不是问题。**

---

## 二、OpenClaw Node 系统分析

### Node 系统已有的能力

| 能力 | 说明 |
|:--|:--|
| 远端命令执行 | `system.run` 通过 WebSocket 转发 |
| 命令白名单 | `exec-approvals.json` 路径级白名单 |
| Shell 注入防护 | 命令替换 `$()` 被拒、链接 `&&` 每段需白名单、重定向被禁 |
| 内联 eval 防护 | `strictInlineEval=true` 拦截 `python -c`、`node -e` 等 |
| 环境变量清理 | 自动剥离 `DYLD_*`、`LD_*`、`NODE_OPTIONS`、`PATH` 等 |
| 身份认证 | Device pairing + nonce challenge 签名 |
| 文件篡改检测 | 审批绑定具体文件，执行前检测变化 |
| 浏览器代理 | Node 自动暴露 browser proxy |
| TLS 支持 | 可选但非强制 |

### Node 系统的局限

| 缺失能力 | 影响 |
|:--|:--|
| **无参数级控制** | 白名单只管命令路径，不管参数。`aria2c --on-download-complete=evil.sh` 能通过 |
| **无文件系统隔离** | `system.run` 可访问 Node 机器上任何文件（受 OS 权限限制） |
| **无能力抽象** | 只有命令级（`system.run`），没有能力级（`download(url)`） |
| **无资源 Quota** | 无磁盘配额、并发限制、带宽限制 |
| **无 URL/域名限制** | 不管命令参数内容 |
| **无完整审计日志** | 只记录 allowlist 最后一次使用 |
| **安装体积大** | 需要完整 OpenClaw（628MB） |
| **无文件回传** | 只返回 stdout/stderr/exitCode |

---

## 三、Worker 系统设计（在 Node 之上）

### 核心设计原则

1. **能力级抽象** — Claw 说"下载这个 URL"，不说"执行 aria2c"
2. **Plugin 层拼装参数** — Worker 自己拼命令，`shell=False` 执行，杜绝注入
3. **Workspace 隔离** — 文件访问限定目录，不能碰系统文件
4. **资源 Quota** — 磁盘、并发、带宽都有上限
5. **审计可追溯** — 所有指令和执行结果都记录

### 三层安全模型

```
┌─────────────────────────────────────────┐
│  Layer 1: 连接安全（继承 Node）          │
│  - Device pairing + nonce 签名           │
│  - Token 认证 + TLS 加密（必须）         │
│  - Token 定期轮换                        │
└─────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────┐
│  Layer 2: 能力安全（Worker 新增）        │
│  - Plugin 注册制：只暴露声明的能力        │
│  - 参数白名单：Plugin 内部拼装，不透传    │
│  - URL/域名白名单：限制下载来源           │
│  - shell=False 执行：杜绝 shell 注入     │
└─────────────────────────────────────────┘
                    ▼
┌─────────────────────────────────────────┐
│  Layer 3: 资源安全（Worker 新增）        │
│  - Workspace 目录隔离（只能访问指定目录） │
│  - 磁盘配额（防写满宿主机）              │
│  - 并发任务上限（防资源耗尽）            │
│  - 带宽限制（防 DDoS）                  │
│  - noexec 挂载（下载文件不可执行）       │
│  - 审计日志（不可远程删除）              │
└─────────────────────────────────────────┘
```

### Plugin 能力定义格式

```yaml
worker:
  name: download-worker
  capabilities:
    - name: download
      description: "下载文件到本地存储"
      params:
        url:
          type: string
          required: true
          validate: "^(https?://|magnet:)"  # 只允许 HTTP/HTTPS/磁力
        savepath:
          type: string
          default: "/workspace/downloads"
          restrict: "/workspace/"           # 只能写 workspace 下
      limits:
        max_file_size: "10GB"
        max_concurrent: 3
        allowed_domains:                    # URL 域名白名单
          - "kisssub.org"
          - "v2.uploadbt.com"
          - "nyaa.si"
      implementation:
        binary: "/usr/bin/aria2c"
        # Plugin 内部拼装参数，不透传外部参数
```

### Plugin 内部安全实现

```python
class DownloadPlugin:
    WORKSPACE = "/workspace/downloads"
    ALLOWED_DOMAINS = ["kisssub.org", "v2.uploadbt.com", "nyaa.si"]
    MAX_CONCURRENT = 3
    
    def download(self, url: str, filename: str = None):
        # 1. 协议验证
        if not url.startswith(("http://", "https://", "magnet:")):
            raise SecurityError("Invalid URL scheme")
        
        # 2. 域名白名单
        from urllib.parse import urlparse
        if url.startswith(("http://", "https://")):
            domain = urlparse(url).hostname
            if not any(domain.endswith(d) for d in self.ALLOWED_DOMAINS):
                raise SecurityError(f"Domain not allowed: {domain}")
        
        # 3. 路径固定，防穿越
        savepath = self.WORKSPACE
        if filename:
            # 去掉路径分隔符，防穿越
            filename = os.path.basename(filename)
        
        # 4. 并发检查
        if self.active_count >= self.MAX_CONCURRENT:
            raise ResourceError("Max concurrent downloads reached")
        
        # 5. 用数组形式执行，shell=False
        cmd = ["/usr/bin/aria2c",
               "-d", savepath,
               "--max-overall-download-limit=10M",
               "--file-allocation=none",
               url]
        result = subprocess.run(cmd, shell=False, capture_output=True, timeout=3600)
        
        # 6. 下载完成后去掉执行权限
        for f in os.listdir(savepath):
            os.chmod(os.path.join(savepath, f), 0o644)
        
        # 7. 记录审计日志
        self.audit_log(action="download", url=url, result=result.returncode)
        
        return {"exit_code": result.returncode}
```

### Claw → Worker 交互协议

```
Claw 发送:
{
    "type": "capability_invoke",
    "capability": "download",
    "params": {
        "url": "magnet:?xt=urn:btih:xxx"
    },
    "request_id": "uuid-xxx"
}

Worker 返回:
{
    "type": "capability_result",
    "request_id": "uuid-xxx",
    "status": "success",
    "result": {
        "exit_code": 0,
        "files": ["xxx.mkv"],
        "size": "375.5 MB"
    }
}
```

**注意：Claw 传的是能力+参数，不是命令。Worker Plugin 自己决定怎么执行。**

---

## 四、Docker/沙箱模式补充

### Windows 宿主机 + Docker Worker 方案

```
Windows 宿主机
├── D:\bt-workspace\        ← 挂载给 Docker（NTFS 配额限制）
│   └── downloads\          ← 下载目录
│
Docker 容器 (Worker)
├── /workspace/downloads/   ← 只能看到这个目录
├── qbittorrent-nox         ← BT 下载工具
└── Worker Plugin           ← 能力层
```

Docker 运行参数：
```bash
docker run -d \
  --name bt-worker \
  --memory=512m \
  --cpus=1 \
  -v D:\bt-workspace:/workspace:rw \
  --security-opt=no-new-privileges \
  worker-image
```

### Docker 能防/不能防

| 风险 | Docker 能防吗 |
|:--|:--|
| 恶意软件感染系统目录 | ✅ 容器只能写挂载目录 |
| 读取宿主机其他文件 | ✅ 只挂载了一个目录 |
| 提权到宿主机 | ✅ WSL2 VM 双层隔离 |
| 恶意文件等人手动执行 | ❌ **最大风险** — 文件躺在共享目录 |
| 磁盘炸弹 | ❌ 需要 NTFS 配额 |
| NTFS ADS 隐藏文件 | ❌ 需要定期扫描 |
| Docker 逃逸 | ✅ 极低概率（WSL2 双层） |

**缓解措施：**
- 挂载目录开 Windows Defender 实时扫描
- 文件扩展名白名单（只保留媒体文件）
- 挂载目录设 NTFS 配额
- 不从共享目录直接打开文件

---

## 五、Node 系统 vs 轻量 Worker 对比

| 维度 | Node 系统（完整 OpenClaw） | 轻量 Worker（自建） |
|:--|:--|:--|
| 安装体积 | 628MB | < 5MB（Go/Rust 单二进制） |
| 内存占用 | ~100-200MB | < 10MB |
| 安全模型 | 命令白名单（三层） | 能力白名单（三层 + Plugin 层） |
| 能力抽象 | ❌ 命令级 | ✅ 能力级 |
| 文件隔离 | ❌ 无 | ✅ Workspace 目录限制 |
| 参数控制 | ❌ 不管参数 | ✅ Plugin 拼装，shell=False |
| 资源限制 | ❌ 无 | ✅ 磁盘/并发/带宽 Quota |
| 文件回传 | ❌ 只有 stdout | ✅ 可自定义 |
| 部署方式 | `npm install -g openclaw` | 单二进制分发 |
| 协议兼容 | 原生 Gateway WebSocket | 需自建或用社区包 |
| 开发成本 | 零（已有） | 中-高 |

---

## 六、风险矩阵总表

| 风险 | 严重度 | Node 系统 | Worker Plugin | Docker | 完整方案 |
|:--|:--|:--|:--|:--|:--|
| Shell 注入（`&&` `$()` `;`） | 🔴 | ✅ 防住 | ✅ 防住 | — | ✅ |
| 参数注入（`--on-complete`） | 🔴 | ❌ | ✅ Plugin 拼装 | — | ✅ |
| 内联代码执行（`python -c`） | 🔴 | ✅ strictInlineEval | ✅ 不暴露解释器 | — | ✅ |
| 环境变量投毒 | 🟡 | ✅ 自动清理 | ✅ 继承 | — | ✅ |
| PATH 劫持 | 🟡 | ✅ 拒绝 PATH override | ✅ 继承 | — | ✅ |
| 文件系统越界 | 🔴 | ❌ | ✅ Workspace 限制 | ✅ 挂载隔离 | ✅ |
| 磁盘耗尽 | 🟡 | ❌ | ✅ Quota | ✅ NTFS 配额 | ✅ |
| 并发资源耗尽 | 🟡 | ❌ | ✅ 并发上限 | ✅ --memory/--cpus | ✅ |
| 下载恶意文件自动执行 | 🔴 | 🟡 间接防 | ✅ noexec + 权限控制 | 🟡 手动打开风险 | ✅ |
| Token 嗅探 | 🔴 | 🟡 TLS 非强制 | ✅ 必须 TLS | — | ✅ |
| 身份伪装/重放 | 🟡 | ✅ nonce 签名 | ✅ 继承 | — | ✅ |
| 任意 URL 下载 | 🟡 | ❌ | ✅ 域名白名单 | — | ✅ |
| 无审计追溯 | 🟡 | 🟡 只记最后一次 | ✅ 完整日志 | — | ✅ |
| Docker 逃逸 | 🔴 | — | — | ✅ WSL2 双层 | ✅ |

---

## 七、实施路线

### Phase 1：用 Node 系统验证需求（立即可做）
- 远端装 OpenClaw node host
- 配置 exec-approvals 白名单
- 写 Skill 封装下载逻辑
- 验证"远端下载"这个场景是否真的好用

### Phase 2：开发轻量 Worker Agent
- 用 Go 或 Rust 写单二进制 Worker
- 实现 Plugin 能力层 + Workspace 隔离
- 兼容 Gateway WebSocket 协议（或自定义协议）
- 目标：< 5MB 安装包，< 10MB 内存

### Phase 3：完善安全和生态
- 完整审计日志
- 资源 Quota 系统
- 多 Worker 能力注册和发现（Capability Registry）
- 发布到 ClawHub

---

## 八、已验证的技术点

### kisssub RSS 接口
- 搜索：`https://www.kisssub.org/rss-{关键词}.xml`
- 最新：`https://www.kisssub.org/rss.xml`
- Magnet 链接：从 RSS enclosure 的 hash 构造 `magnet:?xt=urn:btih:{hash}`
- Torrent 文件：`http://v2.uploadbt.com/?r=down&hash={hash}`
- 不需要登录，不需要过 reCAPTCHA

### qBittorrent-nox API
- 登录：`POST /api/v2/auth/login`
- 添加任务：`POST /api/v2/torrents/add`（支持 magnet 和 torrent 文件）
- 查询状态：`GET /api/v2/torrents/info`
- 用 torrent 文件比纯磁力快（自带 tracker）
- 实测 375MB 文件约 2 分钟下完

### kisssub-search Skill（已开发）
- 位置：`Clawmem/skills/kisssub-search/`
- 四个独立模块：search.py / latest.py / download.py / status.py
- Python 编写，跨平台（Linux/Windows）
- 模块间无依赖

---

*文档版本: v1.0 | 最后更新: 2026-03-27 | 作者: Bocchi 🎸*

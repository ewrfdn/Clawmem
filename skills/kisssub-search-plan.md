# Skill 规划：kisssub-search

## 调研结论

**ClawHub 上没有现成的 kisssub skill。**

但好消息是 kisssub.org 有可用的 RSS 接口，不需要过 reCAPTCHA：

### 已确认的接口

| 接口 | URL | 说明 |
|:--|:--|:--|
| 最新资源 | `https://www.kisssub.org/rss.xml` | 全站最新发布 |
| 搜索 | `https://www.kisssub.org/rss-{关键词}.xml` | 按关键词搜索 |
| 分类 | `https://www.kisssub.org/rss-sort-{id}.xml` | 按分类浏览（待确认） |

### RSS 返回的数据结构

每个 item 包含：
- `title` — 资源标题（含字幕组、分辨率、编码等信息）
- `link` — 详情页链接
- `description` — 详细描述（可能含 HTML）
- `author` — 发布者
- `enclosure.url` — 种子下载链接（`http://v2.uploadbt.com/?r=down&hash=xxx`）
- `pubDate` — 发布时间
- `category` — 分类（动画、漫画等）

## Skill 功能规划

### 核心功能
1. **搜索** — 按关键词搜索资源（解析 RSS-搜索 接口）
2. **最新** — 获取最新发布的资源列表
3. **详情** — 获取某个资源的详细信息
4. **种子链接提取** — 从结果中提取 torrent 下载链接和 magnet 链接

### 可选功能（未来）
5. **订阅追番** — 订阅特定关键词，有新资源时通知（配合 cron）
6. **字幕组筛选** — 按字幕组过滤结果（LoliHouse、喵萌、北宇治等）
7. **分辨率筛选** — 按 1080p/4K 等过滤

## 技术方案

### 数据获取：RSS 接口
纯 RSS 解析，不需要浏览器、不需要登录、不需要过验证码。
磁力链接可直接从 RSS 的 enclosure hash 构造：`magnet:?xt=urn:btih:{hash}`

### 下载工具：qbittorrent-nox
选择理由：
- 后台 daemon 常驻，下载+做种一体化
- REST API 完善，Agent 可通过 API 管理任务
- Web UI 可视化管理（默认 8080 端口）
- 支持磁力链接和 torrent 文件

**qbittorrent-nox API 核心接口：**

| 操作 | API |
|:--|:--|
| 登录 | `POST /api/v2/auth/login` |
| 添加磁力链接 | `POST /api/v2/torrents/add` (urls=magnet:...) |
| 添加 torrent 文件 | `POST /api/v2/torrents/add` (multipart) |
| 查询任务列表 | `GET /api/v2/torrents/info` |
| 查询下载进度 | `GET /api/v2/torrents/info?hashes=xxx` |
| 暂停/恢复 | `POST /api/v2/torrents/pause` / `resume` |
| 删除任务 | `POST /api/v2/torrents/delete` |
| 全局状态 | `GET /api/v2/transfer/info` |

### Skill 结构

```
~/.openclaw/skills/kisssub-search/
├── SKILL.md              # Skill 定义（描述、触发条件）
├── scripts/
│   ├── search.sh         # 搜索并展示结果
│   ├── latest.sh         # 最新资源
│   ├── download.sh       # 通过 qbittorrent-nox API 添加下载
│   ├── status.sh         # 查询下载进度
│   └── parse-rss.sh      # RSS 解析工具
└── references/
    └── api-notes.md      # kisssub RSS + qbittorrent API 文档
```

### SKILL.md 草案

```yaml
---
name: kisssub-search
description: "搜索和浏览爱恋字幕社(kisssub.org)的动漫资源，并通过 qbittorrent 下载。
  用于：搜索动漫/字幕资源、查看最新发布、获取磁力链接、添加下载任务、查看下载进度、追番订阅。
  触发词：kisssub、爱恋、搜番、找动漫资源、字幕组、下载动漫"
---
```

### 完整使用流程

```
用户: "帮我搜一下孤独摇滚"
  │
  ▼ [kisssub-search: search.sh]
  curl RSS → 解析 → 展示结果列表（标题、字幕组、分辨率、大小、时间）
  │
用户: "下载第一个"
  │
  ▼ [kisssub-search: download.sh]
  构造 magnet 链接 → 调用 qbittorrent-nox API 添加任务
  │
用户: "下载进度怎么样了"
  │
  ▼ [kisssub-search: status.sh]
  调用 qbittorrent-nox API 查询进度 → 展示百分比、速度、ETA
```

### 与远端 Worker 方案的联动

这个 Skill 天然适配远端 Worker 方案：
1. **本地模式：** qbittorrent-nox 跑在 Claw 机器上
2. **远端模式：** qbittorrent-nox 跑在远端 Worker 上，Skill 通过 Worker 的 API 地址调用

切换只需要改 API 地址，Skill 逻辑不变。

## 部署前置条件

```bash
# 安装 qbittorrent-nox
sudo apt install qbittorrent-nox

# 启动 daemon
qbittorrent-nox -d

# Web UI 默认地址
# http://localhost:8080 (默认用户 admin, 密码看终端输出)
```

## 待确认

- [ ] 分类 RSS 的 URL 格式（sort-id 对应关系）
- [ ] RSS 返回的结果数量上限
- [ ] qbittorrent-nox 是否需要额外配置 tracker
- [ ] 是否需要代理/VPN 做种

## 时间估算

- qbittorrent-nox 安装配置：30 分钟
- Skill 本体开发（搜索+下载+状态）：2 小时
- 测试和完善：1 小时
- 追番订阅功能（cron）：额外 1 小时

---

*状态：规划中，等 Sakana 确认后动手*

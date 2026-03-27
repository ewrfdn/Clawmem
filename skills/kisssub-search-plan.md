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

### 方案选型
纯 RSS 解析，不需要浏览器、不需要登录、不需要过验证码。

**实现方式：** Shell 脚本（curl + 简单的 XML 解析）
- 优点：零依赖，任何机器都能跑
- 缺点：XML 解析不够优雅

**备选：** Node.js 脚本
- 优点：XML 解析更干净
- 缺点：需要 Node.js 环境

### Skill 结构

```
~/.openclaw/skills/kisssub-search/
├── SKILL.md              # Skill 定义（描述、触发条件）
├── scripts/
│   ├── search.sh         # 搜索脚本
│   ├── latest.sh         # 最新资源脚本
│   └── parse-rss.sh      # RSS 解析工具
└── references/
    └── api-notes.md      # 接口文档
```

### SKILL.md 草案

```yaml
---
name: kisssub-search
description: "搜索和浏览爱恋字幕社(kisssub.org)的动漫资源。
  用于：搜索动漫/字幕资源、查看最新发布、获取种子下载链接、追番订阅。
  触发词：kisssub、爱恋、搜番、找动漫资源、字幕组"
---
```

## 与远端 Worker 方案的联动

这个 Skill 搜索到种子链接后，可以配合远端 Worker 方案：
1. Bocchi 用 kisssub-search 搜索到资源
2. 提取 torrent/magnet 链接
3. 发送到远端 Worker 执行下载（aria2c/qbittorrent）
4. 下载完成后通知

这正好是你之前说的"远端下载"场景的一个完整用例。

## 待确认

- [ ] 分类 RSS 的 URL 格式（sort-id 对应关系）
- [ ] 是否有 magnet 链接接口（目前只看到 torrent）
- [ ] RSS 返回的结果数量上限
- [ ] 是否有频率限制

## 时间估算

- Skill 本体开发：1-2 小时
- 测试和完善：1 小时
- 追番订阅功能：额外 1 小时

---

*状态：规划中，等 Sakana 确认后动手*

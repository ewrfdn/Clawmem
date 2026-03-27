---
name: kisssub-search
description: "搜索和下载爱恋字幕社(kisssub.org)的动漫资源。
  用于：(1) 搜索动漫/字幕资源 (2) 查看最新发布 (3) 获取磁力链接和种子文件 (4) 通过 qbittorrent 添加下载任务 (5) 查看下载进度和状态。
  触发词：kisssub、爱恋、搜番、找动漫、搜动漫、字幕组、下载动漫、下载番剧"
---

# Kisssub Search & Download

搜索爱恋字幕社 (kisssub.org) 的动漫资源，通过 qBittorrent 管理下载。

## 模块说明

所有脚本位于 `scripts/` 目录下，**各模块独立，无相互依赖**。

| 模块 | 脚本 | 功能 | 依赖 |
|:--|:--|:--|:--|
| 搜索 | `search.py` | 按关键词搜索资源 | Python 3, curl |
| 最新 | `latest.py` | 获取最新发布的资源 | Python 3, curl |
| 下载 | `download.py` | 添加磁力/种子到 qBittorrent | Python 3, curl |
| 状态 | `status.py` | 查询 qBittorrent 下载进度 | Python 3, curl |

## 平台支持

- **Linux**: ✅ 完整支持
- **Windows**: ✅ 支持（脚本使用 Python，跨平台兼容）

各脚本内部通过 `platform` 模块检测系统，自动适配路径分隔符和默认目录。

## 使用方式

### 搜索资源
```bash
python3 scripts/search.py "孤独摇滚"
python3 scripts/search.py "孤独摇滚" --limit 5
```

### 查看最新发布
```bash
python3 scripts/latest.py
python3 scripts/latest.py --limit 10
```

### 添加下载任务
```bash
# 通过 hash 下载（推荐，会自动下载 .torrent 文件）
python3 scripts/download.py --hash abc123def456

# 通过磁力链接下载
python3 scripts/download.py --magnet "magnet:?xt=urn:btih:abc123"

# 通过本地 torrent 文件下载
python3 scripts/download.py --torrent /path/to/file.torrent

# 指定保存目录
python3 scripts/download.py --hash abc123 --savepath /data/anime
```

### 查询下载状态
```bash
# 查看所有任务
python3 scripts/status.py

# 查看特定任务
python3 scripts/status.py --hash abc123
```

## 配置

各脚本通过环境变量或命令行参数配置，**无配置文件依赖**：

| 变量 | 默认值 | 说明 |
|:--|:--|:--|
| `QB_HOST` | `http://localhost:8080` | qBittorrent Web API 地址 |
| `QB_USER` | `admin` | qBittorrent 用户名 |
| `QB_PASS` | (无) | qBittorrent 密码 |
| `QB_SAVEPATH` | `~/Downloads` | 默认下载目录 |

## 前置条件

- Python 3.6+
- qBittorrent-nox（用于下载/状态模块）
- 网络可访问 kisssub.org（用于搜索模块）

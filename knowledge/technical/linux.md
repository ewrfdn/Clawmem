# 技术教训

## Ubuntu / Linux

### snap 包管理器的坑
- **日期：** 2026-03-26
- **场景：** 在 Azure VPS 上安装 Chromium
- **问题：** Ubuntu Noble 的 `chromium-browser` apt 包实际上是个 snap 包装器，下载速度只有 ~100KB/s，预计 60+ 分钟
- **解决：** 直接从 Google 官方下载 `google-chrome-stable` deb 包，几秒装完
- **教训：** 在服务器上永远优先用官方 deb 包，避开 snap

### headless Chrome 配置
- **日期：** 2026-03-26
- **场景：** 在无显示器的 VPS 上运行 Chrome
- **必需配置：** `headless: true` + `noSandbox: true` + 指定 `executablePath`
- **教训：** 服务器环境下 Chrome 必须 headless + no-sandbox，否则启动超时

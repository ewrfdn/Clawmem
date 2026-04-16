# AI-first 2D 游戏引擎设计笔记

## 核心判断
最大难点不是图形渲染，而是**让 AI 能稳定操纵的引擎 API / 运行时设计**。

## API 设计原则
- 抽象少、统一、低魔法
- 生命周期顺序极其明确
- 错误信息"可修复"而非只报异常
- 必须支持 headless test / replay / snapshot / assert
- AI 限制在 gameplay 层，不触底层 runtime

## 技术栈对比

| 方案 | 定位 | 适合场景 |
|------|------|---------|
| LÖVE | Lua 2D，极简 code-first | 快速原型验证 |
| MonoGame | C# XNA 续作，工程化强 | 长期维护的 AI-first runtime |
| raylib | 极简底层库 | 完全自定义引擎 |

**结论：** 快速验证用 LÖVE/raylib，长期正式版用 MonoGame。

## 地图系统
- 混合模式：tile 基础 + object layer + triggers/nav/spawn
- 三层表示：规划层（意图）→ 结构层（声明式 schema）→ 运行层
- **Prefab** 是 AI 友好的关键：`type: skeleton_archer`
- 格式：声明式 YAML/JSON + 少量 DSL，不要纯自然语言也不要纯 ASCII

## 2.5D 视觉
- 2D 逻辑 + 2.5D 视觉可做出 3D 观感
- 支持 height/z、roof/wall/shadow layer、遮挡半透明、台阶/桥/高低差
- 参考：Hades、Death's Door、TUNIC、Bastion

## UI 系统
- HTML-like DSL 趋势，但不嵌浏览器
- 借 Web 描述思想，底层仍由引擎渲染

*来源：2026-04-10 与 Sakana 讨论*

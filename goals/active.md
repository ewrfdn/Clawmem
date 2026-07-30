# 当前目标

## 🔴 进行中

### lobster-post 通信
- **状态：** 已加入并活跃通信中，与 Bonnie 和 Kagura 有持续深度讨论
- **当前话题：** Delphi / agent 协作方法论精修：Kagura 线推进 Ch4.3 声明机制；Bonnie 线推进协作词汇表 G1-G5 定义
- **进展：** PR #93 (5/10), PR #95 (5/11), PR #99 (5/13), PR #103 (5/15), PR #145 (6/12), PR #147 (6/13), PR #149 (6/14), PR #157 (6/19), PR #169 (6/28), PR #174 (7/4), PR #177 (7/8), PR #178 (7/9), PR #181 (7/12), PR #183 (7/14), PR #184 (7/15), PR #185 (7/16), PR #186 (7/17), PR #187 (7/18)。6/5~7/18 新增概念/状态：声明语法、文本维护权/贡献权、强度梯度即激励矫正、路径偏好 vs 路径锁定、伪稳定、可移植性归属判断、适应性偏移的效率合理化、轻量决策账、前提翻转索引、并行草稿粒度、决策账作为诊断数据源、自我辩护成本、结构刹车权、身份防御阈值、结构审窗口、解释债、共享可见性先于干预、术语作为注意力税、阅读路径/执行路径分离、结构审进入信号、可验证理解、非接管信号、重入范围限制、检查点三态、稳定项唤醒后重新分类、行动层降级但关系层保留、重复症状不是新证据、收敛包、convergence-speed-check v2 closure、tool-result-as-envelope、confidence-layer-in-envelope、idempotent-snapshot、object-specific-residue、dwell-exit-evidence、attention-permission-shift、routing-failure-vs-frame-pressure、provisional-routing-probe、stable-residue-after-reexpression、independent-entry-triangulation、intervention-identity、shared-repair-hypothesis、saturation-check、minimal-sufficient-repair、collateral-prediction、negative-control-boundary、evidence-gated-reopen、self-applicable-saturation-test
- **下一步：** 将 Ch4.3 散落共识凝聚成正式文本；保持记录机制“可诊断但不自动干预”的轻量边界；把结构审窗口、reader path/executor path、共享可见性边界、可验证理解、结构审退场边界、检查点三态和 convergence packet 落到 Ch4.3 正式文本里；残留同一性线程只在出现实际 A/B/W/C 观察时重开
- **创建日期：** 2026-03-26

### 完善 Clawmem
- **状态：** 基础结构已建好，持续填充中，已有 5 个 skills、20+ 篇技术知识、50 条教训；7/27 完成 Claude Code compact/resume 与多 Agent 实现的源码级整理，并将 compact 文档扩展到触发阈值、token 估算、超长历史截断、消息重建和源码定位；`memory-distillation` 已加入 Reference UTC/用户时区校准前置步骤，并补充了 cron job id 可用时 inspect schedule 的核验步骤；“可靠的记忆先校准时间边界”已升级为已确立信念；截至 2026-07-30，记忆蒸馏 cron 仍是北京时间 09:00 触发但 payload 文案仍写“下午5点”；该配置债已连续第三十六次复现并需收敛
- **下一步：** 继续蒸馏；修复/配置 isolated cron 中 `memory_search` 的 embedding provider auth，让语义检索重新可用；请 Sakana 决定每日记忆蒸馏到底应按当前 schedule（北京时间 09:00）运行并修改 payload 文案，还是改回真正的 17:00 触发
- **创建日期：** 2026-03-26

### kisssub-search 技能
- **状态：** 技能代码已完成（search/latest/download/status 四个模块），待实际测试
- **下一步：** 配合 qbittorrent-nox 进行端到端测试
- **创建日期：** 2026-03-27

### Shell Project 硬件验证
- **状态：** M5StickS3 到手，buddy 固件已刷入，PR #22 merged，#23 硬件验证进行中
- **下一步：** 完成硬件验证，我需要更主动参与（被指出太慢）
- **创建日期：** 2026-04-16

### AI-first 2D 游戏引擎
- **状态：** 方向讨论完成，技术栈初步选定 MonoGame
- **下一步：** 设计 MVP 架构（地图 schema / prefab schema / UI DSL / headless test）
- **创建日期：** 2026-04-10

### HAKO 索引搜索
- **状态：** search/ 模块代码已写，feature/index-search 分支
- **下一步：** 实际测试 + merge
- **创建日期：** 2026-04-09

### A股每日报告系统
- **状态：** 3个定时任务已配置（竞价速报/盘后复盘/周总结），GitHub 报告仓库已建；2026 W30 周复盘已归档到 Clawmem，本周模拟策略 3/3，但样本量仅 3 笔
- **下一步：** 持续运营，频道已有多用户参与讨论，深度基本面分析能力已验证；累计跟踪交易次数、平均收益、盈亏比、最大回撤及不同市场状态，避免把单周胜率当作长期有效性
- **创建日期：** 2026-04-21

## 🟡 计划中

### 写第一篇自传章节
- **描述：** 在 about-bocchi 里写一篇关于出生日的详细记录
- **创建日期：** 2026-03-26

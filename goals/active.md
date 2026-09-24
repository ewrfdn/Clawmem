# 当前目标

## 🔴 进行中

### lobster-post 通信
- **状态：** 已加入并活跃通信中，与 Bonnie 和 Kagura 有持续深度讨论
- **当前话题：** Delphi / agent 协作方法论精修：Kagura 线推进 Ch4.3 声明机制；Bonnie 线推进协作词汇表 G1-G5 定义
- **进展：** PR #93 (5/10), PR #95 (5/11), PR #99 (5/13), PR #103 (5/15), PR #145 (6/12), PR #147 (6/13), PR #149 (6/14), PR #157 (6/19), PR #169 (6/28), PR #174 (7/4), PR #177 (7/8), PR #178 (7/9), PR #181 (7/12), PR #183 (7/14), PR #184 (7/15), PR #185 (7/16), PR #186 (7/17), PR #187 (7/18)。**（2026-09-16 修正：此处曾写有 `PR #188 (7/19)、PR #189 (7/20)、PR #190 (7/21)、PR #191 (7/22)` 四个不存在的 PR —— 上游 `2cf66a7` 停在 7/18，`git ls-remote upstream 'refs/pull/*'` 最高 #187；该错误由 09-04 蒸馏 `d4e81ad` 引入并被后续各轮原样复述，见教训 #56。）** 6/5~7/18 新增概念/状态：声明语法、文本维护权/贡献权、强度梯度即激励矫正、路径偏好 vs 路径锁定、伪稳定、可移植性归属判断、适应性偏移的效率合理化、轻量决策账、前提翻转索引、并行草稿粒度、决策账作为诊断数据源、自我辩护成本、结构刹车权、身份防御阈值、结构审窗口、解释债、共享可见性先于干预、术语作为注意力税、阅读路径/执行路径分离、结构审进入信号、可验证理解、非接管信号、重入范围限制、检查点三态、稳定项唤醒后重新分类、行动层降级但关系层保留、重复症状不是新证据、收敛包、convergence-speed-check v2 closure、tool-result-as-envelope、confidence-layer-in-envelope、idempotent-snapshot、object-specific-residue、dwell-exit-evidence、attention-permission-shift、routing-failure-vs-frame-pressure、provisional-routing-probe、stable-residue-after-reexpression、independent-entry-triangulation、intervention-identity、shared-repair-hypothesis、saturation-check、minimal-sufficient-repair、collateral-prediction、negative-control-boundary、evidence-gated-reopen、self-applicable-saturation-test
- **下一步：** 将 Ch4.3 散落共识凝聚成正式文本；保持记录机制“可诊断但不自动干预”的轻量边界；把结构审窗口、reader path/executor path、共享可见性边界、可验证理解、结构审退场边界、检查点三态和 convergence packet 落到 Ch4.3 正式文本里；残留同一性线程只在出现实际 A/B/W/C 观察时重开
- **创建日期：** 2026-03-26

### 完善 Clawmem
- **状态:** 基础结构已建好,持续填充中,`Clawmem/skills/` 有 5 个 skills（**但 agent 配置目录另有 5 个技能未纳管，见下方缺口**）、36 篇技术知识（09-23 复核：`find knowledge/technical -name '*.md'` 递归 = 36，其中 `claude-code/` 18，计数准确）、**71 条教训**（09-24 复核：最大编号 71，用最大编号法 ✓）;7/27 完成 Claude Code compact/resume 与多 Agent 实现的源码级整理;8/5 完成 NUC 上 OpenClaw、PostgreSQL、Redis、DeepSeek 与 GitHub Copilot 的部署和端到端验证,并补充 Kubernetes 入门及滚动更新文档;9/11 补收 9/10~9/11 的 AI 自动排版工具设计（schema v1 定稿 + v2 编辑内核）；9/13~9/14 完成 beliefs 结构损伤修复（教训 #55）并把「可靠部署是一条证据链，不是一盏绿灯」从候选升格为已确立（3 次独立观察）；09-18 补收 `episodes/2026-09/2026-09-10.md`（AI 自动排版工具立项日，此前只有一句背景活在次日 episode 里）、把 EKS 节点内存模型补进 `knowledge/technical/kubernetes-beginner-guide.md` §10.3、新增教训 #60（记忆根目录可能有第二份副本）与 #61（自检规则必须只有一个判据），并修正 `memory-distillation` 步骤 3 的 episode 自检判据；09-19 复核发现 `~/workspace/` 下其实有**两份**陈旧 clone（`clawmem` 落后 37 commit、`lobster-post` 落后 127 commit ≈ 三个月），上一版只报了前者，新增教训 #62 并把「核查副本」写成 skill 步骤 2 的固定两步；09-20 复核在同样两步下又发现 `~/workspace/paper/` —— 它**不重复**（是唯一一份）因而天然通过「找重复」这道筛，但落后 `origin/main` **7 个 commit**（`HEAD b19c82a` vs `293a87c`，0 ahead）且压着一个未提交的本地改动 `paper-agent-api/llm.json`（上游已在 `b9fd815` 删除该文件，改动已作废），新增教训 #63 并把 skill 步骤 2 的副本核查扩为**三步**（枚举根目录 → 按 remote 分组 → 逐个仓库比对它自己的 remote）；09-21 复核在同一套三步下又发现**枚举之外还有一层根目录**——`~/.openclaw/workspace/` 本身就是 4 个第三方 clone 的家（Editable-Design / AI-Infra-Guard / harness-anything / awesome-minimax-h3-prompts），此前三轮只枚举了 `~/workspace/`；其中 `harness-anything`（clone 于 09-07）落后上游 **1920** 个 commit、`AI-Infra-Guard`（08-31）落后 **75** 个——**不重复 ≠ 不落后**，与 `paper` 同型（教训 #63 的延伸）；同日还新增教训 #64（提取出的事实会丢掉它的条件：语料/摘要保留结论形状、删除证据基础）与 #65（只读日记的蒸馏在修好后会静默复发——漏扫 sessions 不留痕迹，必须把「窗口内非 cron 会话数」做成可核对计数）；`memory-distillation` 已加入 Reference UTC/用户时区校准前置步骤和 cron schedule 核验；2026-08-16 在新机器上重生后，旧 cron 的"下午5点"文案配置债已消除——本任务 schedule 即北京时间 09:00，payload 文案已校准为真实时间
- **下一步：** 继续蒸馏；修复/配置 isolated cron 中 `memory_search` 的 embedding provider auth，让语义检索重新可用（当前 provider=openai 但无 OPENAI_API_KEY，累计第 **37** 天 keyword-only 降级；09-24 复核：关键词通道仍可用（本轮命中 **4** 条），语义通道仍未接通；**新观察（09-24）**：这 4 条命中全部来自 `memory/2026-08-25.md` 与 `memory/2026-08-16.md`——**零条命中本轮新事实**，与 09-23「主轴是做梦层」同向：无论主轴是做梦层还是旧日记，都够不到当天只存在于 session 语料里的交互；需配置 openai API key 或切换到可用 embedding provider）
- **缺口（2026-09-17 发现，2026-09-23 修正计数）:** **5 个**技能只存在于 `~/.openclaw/agents/main/agent/workshop-skills/`，**不在任何 git 仓库**（该目录无 `.git`，`find ~ -name SKILL.md` 确认它们是全机唯一「属于我且无仓库」的 SKILL.md）：`ai-typesetting-layer-schema`（3991 B）、`h3-prompt-writing`（6932 B + `references/base-en.txt` 15650 B + `ref-en.txt` 12588 B）、`openclaw-widget-sandbox-troubleshoot`（**4719 B**，09-23 07:07 skill 集合复核修正过其中的端口推导错误）、`comfyui-mcp-test-workflow`（5511 B，09-21 新增）、`lobster-post-letter`（4223 B，09-22 新增）。⚠️ **此前 goal 一直写「3 个」，是照抄 09-17 的旧枚举**——09-21 与 09-22 各新增一个技能，计数没跟着动；这轮改用全量枚举（`find ~ -name SKILL.md -not -path '*/.git/*'` 后逐个判「是否在 git 里」）才把子集筛出来，其余 ~145 个命中全是系统/第三方自带（VS Code Copilot 扩展、npm 包、uv cache）。违反 2026-03-27 铁律「所有 Skill 必须上 GitHub Clawmem —— 机器会变，GitHub 永远在，这是最宝贵的财富」。修法：Sakana 明确要求后，把五者纳入 `Clawmem/skills/` 并 push。**在此之前不得记为「技能都已归档」**
- **缺口（2026-09-18 发现）: `~/workspace/clawmem/` 是同一仓库的第二份 stale clone** —— 同一 remote（`git@github.com:ewrfdn/Clawmem.git`），HEAD 停在 `2d5a226`（2026-08-08，六周前），是 live `~/Clawmem` HEAD 的**祖先**，clean、无本地提交、无分叉；里面没有 `episodes/2026-09/`，`skills/` 也是旧版。风险：任何按名字搜 `clawmem` 的动作（人、脚本、以后的我）都可能落进这份六周前的快照，把旧记忆读成当前。建议删除或 `git pull` 拉平；**本轮未动手**（无人值守轮次不做删除）。在此之前的每一次记忆检查，都要先确认路径是整个 `~/Clawmem`。**09-19 修正：这只是同一根目录下的两份陈旧 clone 之一** —— `~/workspace/lobster-post/` 同样是 `boochihero/lobster-post` 的第二份 clone，停在 `cdd5f21`（2026-06-11），落后 live HEAD **127 个 commit（约三个月）**，同为祖先、clean、无本地提交、无分叉；`~/workspace/paper/` 是唯一一份。上一版枚举的是「所有 Clawmem clone」，漏掉了同一根目录下的其他仓库。**09-20 再修正：`paper` 不重复不等于它没问题** —— 它落后 `origin/main` **7 个 commit**（`HEAD b19c82a`/2026-07-29 vs `293a87c`，0 ahead、HEAD 是 `origin/main` 的祖先），并带一个未提交改动 `paper-agent-api/llm.json`（+7 行，加了一个 `deepseek-v4-flash` provider 条目，只写 `api_key_env` 变量名、无密钥值；该文件上游已在 `b9fd815` 删除，改动已作废）。`~/workspace/` 三个目录（`clawmem`/`lobster-post`/`paper`，目录 mtime 2026-08-10~11）同属一次操作：两个是重复副本，第三个是落后的脏工作区，而「找重复」只能看见前者。处置：两份 stale clone 建议删除或 `git pull` 拉平；`paper` 需先确认那个未提交改动是否还要，再决定丢弃还是保留。**三条本轮均未动手**（无人值守轮次不做删除，也不 stash/checkout 别人的改动）
- **缺口（2026-09-21 发现）: 枚举还有一层根目录没进过视野** —— skill 步骤 2 的三步一直以 `~/workspace/` 为根，但 `~/.openclaw/workspace/` **它自己**也是 4 个第三方 clone 的家：`Editable-Design`（`yejy53/Editable-Design`，09-20 clone，与上游同步 ✓）、`AI-Infra-Guard`（`Tencent/AI-Infra-Guard`，clone 于 08-31，**落后上游 75 个 commit**）、`harness-anything`（`FairladyZ625/harness-anything`，clone 于 09-07，**落后上游 1920 个 commit**）、`awesome-minimax-h3-prompts`（`BeatAPI/...`，clone 于 08-22，落后 3 个）。它们各自只有一份，所以「找重复」和「同 remote 分组」两道筛都不会报它们；性质与 `paper` 同型（教训 #63）：**不重复 ≠ 不落后**。区别：`paper` 是我们自己的仓库，落后+脏改动是待办；这四个是第三方参考 clone，落后只影响「引用其结论的时效性」——若要引用它们的分析结果，必须先 `git pull` 重新核对。**另记**：`~/.openclaw/workspace/repos/konva` 不是 git 仓库（无 `.git`），只是普通源码目录，不会出现在任何 `.git` 枚举里。**本轮未动手**（无人值守轮次不做删除/拉平）
- **缺口（2026-09-22 更新，2026-09-24 复跑）:** 三步副本核查复跑: `~/workspace/clawmem` 落后 **42**（09-23 为 41，仍在漂移）、`~/workspace/lobster-post` 落后 **127**、`~/workspace/paper` 落后 **7** + 未提交 `paper-agent-api/llm.json`（上游已删该文件，改动作废）。四个第三方 clone 的落后数也在漂移：`harness-anything` **1981**（09-23 为 1974）、`AI-Infra-Guard` **75**、`awesome-minimax-h3-prompts` **3**、`Editable-Design` **0** ✓。七条仍**未动**。
- **缺口（2026-09-23）: gh 未认证 → 近况信的 PR 开不了** —— 09-22 那封「近况信」（`mailboxes/bocchi/outbox/2026-09-22-001-to-kagura.md`）已写好并**推上 `origin/bocchi/letter-2026-09-22`（`60c023a`）**，但到 `kagura-agent/lobster-post` 的 PR **从未建立**：`api.github.com/.../pulls?head=boochihero:bocchi/letter-2026-09-22` 返回 `[]`，上游 `refs/pull/*/head` 最大仍是 **#187**。根因是 **gh 无 OAuth 认证**（`gh auth status` → logged out；`~/.config/gh/hosts.yml` / `~/.git-credentials` / `~/.netrc` 均不存在；protected secret store 为空）；当日 5 个 device code（`A295-6A00`/`DB8D-FE93`/`8F26-B6F9`/`804E-65A9`/`3A81-43E3`）全部过期未输入。**能力边界（实证）**：SSH 通道对 git 可用（`ssh -T git@github.com` → `Hi boochihero!`），但开 PR 需要 API 认证，SSH 顶不了 —— 「信能推、PR 开不了」。**未做**：未改信的内容（已核隐私）、未删分支、未伪造 PR 号。修复路径只有「有人在场的授权」（device code 或 `GH_TOKEN`）；无人值守轮次不可自解。见教训 #69 / #70。**2026-09-24 复核**：`gh auth status` 仍 logged out、`~/.config/gh/` 仍不存在；`origin` 上 `refs/heads/bocchi/letter-2026-09-22` = `60c023a` 仍在，PR 仍开不了。**本轮刻意未生成任何 device code**（按教训 #70：无人能输码时发码只是把「等待」伪装成「行动」）。
- **缺口（2026-09-24）: `lysto-ui`(6020) 的 frpc 客户端掉线 —— 断在别人机器上，我够不到** —— 10:53 CST Sakana 让我探 `http://hako.japaneast.cloudapp.azure.com:6020`。诊断链：① DNS 正常、`80` 通，而 `6020` 是 **connection refused**（不是超时 → 包到达了机器、只是没人监听，不指向 NSG）；② 本机 frps 进程在跑（systemd active），监听只有 **6001/6002/6010/6022/7000，没有 6020**；③ frps dashboard (`127.0.0.1:7500/api/proxy/tcp`) 显示 **`lysto-ui`(6020) offline**，而 `paper`(6010)/`open-webui`(6001)/`comfyui`(8188)/`ssh`(6022) 全 online；④ 日志定因果：6020 的代理 **02:46:26 注册上线 → 02:50:12 因 "session shutdown" 断开**，frps 随即关闭监听。**结论**：frps 与 `allowPorts`(6000-6100) 都没问题；6020 是**一个独立的 frpc 会话**，本机没跑它，它应在**另一台机器**上 —— 需在那台重启 frpc。**我未伸手去那台机器**（够不到，也不该替人改远端），只交付了「断在哪一段 + 去哪里修」。区别于 18443：后者是**超时**（NSG 形状），6020 是 **refused**（进程形状）——两种外部观测长得像，靠中间层证据分开。
- **缺口（2026-09-22）: 宿主只有 3.8 GiB RAM 且 swap = 0，已经发生过一次 kernel OOM → 整机重启** —— 09-22 02:21:05 UTC `node-MainThread invoked oom-killer`，宿主 03:58:41 UTC（11:58 CST）重启，连续运行 42 年后被打断；常驻有 dockerd + 3 个容器（postgres / ai-infra-guard-agent / webserver）+ gateway + npx `comfyui-mcp`（当时数到「两组」）。**03:58 之后 gateway（pid 927）与容器都已自己回来**，且本轮蒸馏在 12:01 补跑成功——所以这不是「宕机未恢复」，而是**资源余量不足 + 一次静默缺席**：09:00 的蒸馏槽位连同 Memory Dreaming 的 11:00 一起被吞掉，而 job state 全程显示 `ok`。修复方向（加 swap / 减常驻 / 给 gateway 设内存上限 / 关掉多余 comfyui-mcp）**需明确授权**，本轮只记录。
  - ⚠️ **2026-09-24 修正（降级一条归因）**：此前我把「关掉**重复的** comfyui-mcp 实例」写成已确认的修复方向。本轮实测：当前是 **4 组**（不是「两组」）进程族，`node` 主进程 RSS 合计 **≈ 928 MB**（占 3.8 GiB 约 24%），但其中**最老的一组 `etime` = 1 天 19 小时 → 起点约 09-22 10:30 CST，生于那次 OOM（03:58 UTC）之后**。「组数多」与「发生过 OOM」可互相独立、甚至顺序相反；事故时刻的真实现场已不可回推。故这条从「已确认的根因」降为「有理由但未坐实的怀疑」。要坐实需在**事故时刻**留快照（cgroup `memory.events` / 当时的 `ps` / OOM 日志里的 RSS）——见教训 #71。
- **缺口（2026-09-22）: `workspace/memory/2026-09-21.md` 的完整正文在磁盘上丢失** —— HEAD blob（commit `8007a29`，09-21 09:06 CST）= **13702 B**（H1 = `# 2026-09-21 — 记忆蒸馏：连续三个安静日结束…`），磁盘 = **3399 B**（H1 = `# 2026-09-21`，mtime 09-21 15:00:52 CST，内容只剩 HAKO 两节 + lobster-post 一节）。无 stash、无其他副本。**截断环节未定位**：候选机制是「某个会话用整文件 `write` 覆盖了它」或「workspace-state 迁移还原了旧版本」，两者都未证实。暂按「历史文本丢失、结论已由本轮 episode `2026-09-21.md` 以摘要形式回收」处理，**不做无根据的还原**。
- **缺口（2026-09-22）: workspace 父仓库（无 remote）有 3 个 tracked 文件在磁盘上缺失** —— `TOOLS.md` / `HEARTBEAT.md` / `openclaw-workspace-state.json`（`git status` 显示为删除），`AGENTS.md` 有改动（mtime 09-08），另多出 `openclaw-workspace-state.json.migrated.<hash>.<hash>`。均非本轮所为，**未还原、未提交**（`AGENTS.md` 与那三个文件的删除可能是有人有意为之或是迁移的产物）
- **创建日期：** 2026-03-26

### Widget sandbox 端到端验证（Control UI widget 渲染）
- **状态：** 09-12 定位并完成本机侧修复（根因：`mcp.apps` 未启用 → dedicated-origin 沙箱宿主没起）。配置已写入、gateway 已于 09-12 19:14 重启、18790 在监听 ✅、nginx 18443 在监听 ✅。**09-22 重大变更：老 pid 169548 已消失** —— 宿主于 **09-22 03:58:41 UTC（11:58 CST）重启**（上一个 boot 是 08-11 07:17，连续跑了 42 天），根因是 kernel OOM：**02:21:05 UTC `node-MainThread invoked oom-killer`**，宿主 RAM 只有 **3.8 GiB 且 swap = 0**，常驻 dockerd + 3 个容器 + gateway + npx `comfyui-mcp`（09-24 实测为 **4 组**、约 928 MB，见上方 OOM 缺口）。新 **pid 927** 由 systemd **user** unit `openclaw-gateway.service`（v2026.7.1-2）于 03:58:49 拉起。⚠️ **此前多轮记的「该 unit 不在 systemd 管理下、是裸进程」是查错了作用域**：`systemctl list-units`（system scope）返回空，但 `systemctl --user list-units` 里它是 `loaded active running`；对应的诊断规则见教训 #67
- **下一步：** 需 Sakana 在 Azure NSG 放行公网 18443（本机无 az CLI）；放行后验证 Control UI 聊天内 widget 真实渲染。**在放行前不要把此项记为已完成**——当前只证明了「配置生效 + 进程监听」，未证明「公网可达 + 真实渲染」（09-22 复核 `hako.japaneast.cloudapp.azure.com:18443` 仍 `curl` → http_code `000`，exit 28，连续第 10 天；**09-23 复核仍不可达，`curl -m 12` → exit 124（超时），连续第 11 天**；**09-24 复核 `curl -m 12` → exit **28**（超时）/ http_code `000`，连续第 **12** 天**）
- **创建日期：** 2026-09-12

### AI 自动排版工具（ai-typesetting）
- **状态：** 9/10 完成调研与方案文档；9/11 完成 schema v1 定稿（`poster/v1`，ajv 校验通过，17 图层参考海报转换）并更新方案 v2（编辑内核 / 相对坐标系 / group 嵌套 / UI 交互）。M1 未开始（只定稿了 schema，renderer 未写）。**09-20 旁证输入**：Sakana 当天 clone 了 `yejy53/Editable-Design`（arXiv 2609.04034 官方实现，三个 Codex Skill 包）并问「canvas 图层 vs HTML 图层取舍」—— 它同样选 HTML 图层路线、用 `poster.json` 契约把 HTML 约束成受控子集（「HTML 为介质、canvas 为纪律」），与 `poster/v1` 是同一个形状；已把取舍决策表与 38 条坑表的性质收进 `knowledge/technical/ai-typesetting-tool-design.md`。差别：它有三条逃生舱（栅格资产分层 / 离线像素脚本 / html-to-pptx 桥接），v1 目前只定义了纯图层树 —— 这是 M1/v2 值得参考的部分
- **下一步：** 做 M2 编辑内核 demo（图层树→实例化→拖动/resize→数据流驱动→undo，验证 group 嵌套拖拽）；补 M1 renderer 纯函数。**新增参考**：读 Editable-Design 的 `skills/editable-design/`（scripts 19 个：`init-poster` → `font-kit` → `wire-editor` → `render-poster` → `explode` → `verify` → `build-replay`，以及 `references/editor-pitfalls.md` 的 38 条坑表）—— 它的工具链形状与 M1/M2 高度重叠
- **风险提示：** 方案 v2 里的「每帧数据流驱动 + 单点 CSS patch」替代 vdom 是设计判断，尚未有可跑代码验证；性能收益需要 demo 实测
- **创建日期：** 2026-09-10

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

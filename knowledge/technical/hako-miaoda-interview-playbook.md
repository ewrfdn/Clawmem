# HAKO × 飞书妙搭：Agent 云端执行平台面试手册

> 适用场景：字节跳动 / 飞书妙搭 Agent 平台面试  
> 整理日期：2026-07-14  
> 依据：HAKO 源码、`ARCHITECTURE.md`、Windows E2E 报告、个人简历及飞书公开资料。

---

## 0. 面试前先记住的结论

### 一句话定位

**HAKO 是一个面向 AI Agent 的分布式远程执行平台：它通过 MCP 向 Agent 暴露文件、Shell、搜索和插件能力，由中心 Server 将任务路由到主动建立 gRPC 双向长连接的 Worker，并在 Worker 所在环境中受控执行。**

### 与妙搭最准确的关系

- **相似点**：都涉及“Agent 生成工具调用 → 控制面路由任务 → 远端执行环境运行 → 返回结果”，也都需要处理长任务、权限、工具扩展、日志、状态和安全边界。
- **不同点**：妙搭公开定位是 AI 原生企业系统搭建平台，覆盖需求分析、设计、数据管控、应用开发和问题修复；HAKO 当前聚焦的是 **Agent 的工具接入与远程执行基础设施**，不是完整的多 Agent 产研编排、低代码应用生成或企业级云沙箱平台。
- **面试表达**：不要说“HAKO 和妙搭架构一样”，应说：
  > 我不了解妙搭内部实现，但从公开产品能力看，两者在 Agent 执行基础设施层面有相似问题。HAKO 让我实际处理过协议、长连接、任务生命周期、Worker 管理、权限和远程执行；如果做成企业级云端 Agent Runtime，还需要补齐强隔离、多租户授权、持久化调度、高可用和可观测性。

### 最值得主动讲的三个设计

1. **Worker 主动连接 Server**：无需给个人电脑或企业内网机器开放入站端口，天然适合 NAT/防火墙环境。
2. **MCP 与执行层解耦**：Agent 看到标准工具；Client 把调用转换成 Proto；Server 负责路由；Worker 用 Action 注册表执行，新增能力不必修改 Agent。
3. **同步 + 异步任务模型**：短操作同步返回；长 Shell 任务异步提交，使用 `task_id` 查询或取消，避免长期占住一次 MCP/gRPC 请求。

### 必须主动承认的边界

- Worker 当前直接在宿主 OS 创建进程，**不是强安全沙箱**。
- Server 的连接、待完成 Future 和部分队列主要在内存中，当前更适合单实例控制面。
- 数据模型已有 `user_id`、`owner_id`、`is_shared`、`occupied_by`，但租户级授权闭环尚不完整。
- 当前任务语义接近 **at-most-once（至多一次）**，没有持久化投递、ACK、租约和重放。
- E2E 证明主链路可用，但只有一份 Windows 环境报告，并且 grep 的 `count`、`context` 有两个已知偏差；不能声称经过大规模生产验证。

---

## 1. 两分钟项目介绍（建议背熟）

我做了一个叫 HAKO 的项目，它是面向 AI Agent 的分布式远程执行平台。出发点是：Agent 本身通常运行在云端或受限环境，但真正的开发任务可能需要访问某台开发机上的仓库、编译工具链、私有网络和本地插件。如果直接让 Agent 通过 SSH 或任意 Shell 操作机器，接入、安全和扩展性都比较差。

所以我把系统分成四层。第一层是 Agent，通过 MCP 使用 `view`、`edit`、`grep`、`shell`、插件等工具；第二层 Client 把 MCP 调用转换成 gRPC/Proto 请求；第三层中心 Server 管理 Worker 长连接、认证、任务路由和结果转发；第四层 Worker 主动向 Server 建立双向 gRPC 流，在本地执行 Action。主动建链的好处是 Worker 可以位于 NAT 或企业防火墙后面，不需要暴露公网端口。

任务方面，我同时支持同步和异步模式。短文件操作同步返回；长命令异步提交并返回 `task_id`，Agent 后续可以查询或取消。Worker 侧用统一的 `TaskManager` 做并发控制和任务跟踪，用 Action 注册表扩展文件、Shell、搜索和插件能力。安全上实现了 Client/Worker 两套认证、可选 TLS/mTLS、命令白名单、per-action 权限、工作区路径边界和符号链接逃逸校验。

我会明确说它目前是远程执行控制面，不是完整云沙箱。现在 Worker 仍直接执行宿主进程，Server 也有内存状态，因此下一阶段如果面向妙搭这类企业级云端 Agent 场景，我会引入 Kata 或其他隔离运行时、持久化任务状态、租约和 ACK、租户级授权、消息总线、全链路 trace 和资源配额。这段经历让我实际理解了 Agent 从工具调用到远端执行的整条链路，而不仅是写 Prompt 或调用模型 API。

---

## 2. 五分钟项目讲述框架

### 2.1 Situation：为什么做

- Agent 需要操作真实工程环境，而依赖、私有网络和构建工具通常只存在于特定机器。
- 直接 SSH 的问题：协议不面向 Agent、权限粒度粗、结果难结构化、工具难发现、NAT 下接入困难。
- 单机 MCP Server 的问题：Agent 与执行环境绑定，难以跨设备选择 Worker，也难统一认证和状态管理。

### 2.2 Task：要解决什么

- 给 Agent 提供稳定、结构化、可发现的远程工具。
- 让 Windows/Linux Worker 在 NAT 后安全上线。
- 支持同步操作、长时间异步任务、取消和结果查询。
- 允许按插件/Skill 扩展专业能力。
- 在不声称强沙箱的前提下，建立最小权限和路径边界。

### 2.3 Action：核心设计

1. **MCP 接入**：`client/mcp_server.py` 暴露 Agent 工具。
2. **协议模型**：`proto/worker.proto` 使用 `oneof` 表达不同 Operation、Report 和流消息。
3. **控制面路由**：`TaskService.SubmitTask()` 生成 UUID，`manager` 把 `TaskAssignment` 放入目标 Worker 的内存队列。
4. **长连接**：Worker 通过 `WorkerService.Connect()` 建立双向流，Server 下发任务，Worker 上报心跳、结果和文件块。
5. **Worker 执行**：Action 注册表将 Proto operation 映射到具体 Action，统一进入 `TaskManager`。
6. **长任务**：异步 Shell 立即返回 `PENDING`；结果保存在 Worker 本地，查询和取消也被建模为操作。
7. **安全**：设备码 + Ed25519 challenge-response 的 Client 会话认证；Worker Token；TLS/mTLS；命令白名单；per-action 权限；工作区绝对路径、分隔符边界与 `realpath` 校验。

### 2.4 Result：证据怎么讲

只能讲可验证的结果：

- Windows Worker E2E 共 35 项：33 通过、2 个警告、0 失败。
- 已覆盖 Worker 查询、文件增删改查、glob/grep、同步/异步 Shell、非法命令拦截、任务查询/取消、插件发现、Skill 获取和插件执行。
- 已知问题被保留在报告中：grep `count` 返回文件数而非逐文件匹配数；`context` 未返回上下文行。
- 不要编造 QPS、并发规模、用户量或 SLA。

### 2.5 Reflection：复盘与演进

- 当前最有价值的是完成了 Agent → MCP → gRPC 控制面 → Worker → OS 的完整闭环。
- 当前最大技术债是“控制面状态在内存 + Worker 不是强沙箱”。
- 云平台化的优先顺序：
  1. 修正确性和授权问题；
  2. 持久化任务、ACK/租约/幂等；
  3. Kata/cgroup/网络策略与凭证隔离；
  4. 多实例路由和消息总线；
  5. trace、指标、审计、容量调度和计费。

---

## 3. 源码级架构与时序

### 3.1 组件职责

```text
AI Agent
  │ MCP tool call
  ▼
MCP Client（工具 schema、参数校验、结果格式化）
  │ gRPC TaskService
  ▼
HAKO Server
  ├─ ClientAuthInterceptor：Client Session 鉴权
  ├─ TaskService：提交、查询、取消、下载、Worker 状态
  ├─ WorkerService：Worker 双向流
  ├─ AuthService：Worker 登录
  ├─ WorkerManager：连接、发送队列、pending Future、下载队列
  └─ DB：Worker/Token/ClientDevice 等持久数据
  │ gRPC bidirectional stream
  ▼
Worker
  ├─ WorkerConnection：登录、建链、心跳、重连
  ├─ TaskManager：并发、active/async task、取消与查询
  ├─ Action Registry：operation → Action
  ├─ Security：路径校验、命令策略、per-action 权限
  └─ Plugin Registry / Search Index
```

### 3.2 同步任务

1. Agent 调用 MCP 工具。
2. Client 携带 Bearer Session Token 调用 `TaskService.SubmitTask()`。
3. Server 校验目标 Worker 在线，生成任务 UUID。
4. `manager.submit_task()` 建立 Future，并把 assignment 放入 Worker 发送队列。
5. `dispatch_tasks()` 经双向流下发。
6. Worker 解析 Proto `oneof`，找到 Action，经过 `TaskManager` 执行。
7. Worker 回传 `TaskReport`。
8. `manager.complete_task()` 完成 Future，结果返回 Agent。

### 3.3 异步任务

- `shell(mode="async")` 不等待进程结束，返回 `task_id` 和 `PENDING`。
- Worker 保留异步任务状态/结果。
- 查询与取消不是 Server 本地操作，而是包装成 `query_task_op` / `cancel_task_op` 再发给同一 Worker。
- 好处：执行状态由真正拥有进程的 Worker 管理。
- 局限：Worker 丢失或重装后，结果可用性取决于 Worker 本地持久化；Server 本身没有完整任务账本。

### 3.4 文件下载

- Client 调用 server-streaming `DownloadFile()`。
- Server 注册以 `task_id` 标识、容量为 16 的下载队列。
- Worker 将 metadata/data `FileChunk` 通过现有双向流上报。
- Server 将块转发给 Client，单块等待设有超时。
- 当前 Client 写入目标文件，但未验证总长度、哈希和明确完成标记，企业级实现应临时文件落盘、校验后原子 rename。

### 3.5 为什么选择 gRPC + Proto

- 双向流适合 Worker 主动建链和实时任务下发。
- Proto 强类型，适合跨 Python/Go/Java 等语言演进。
- `oneof` 明确同一消息中只能有一种操作，避免动态 JSON 结构失控。
- HTTP/2 复用、Keepalive 和流式传输适合心跳、结果和文件块。
- 代价：浏览器接入不直接；流生命周期、背压和多实例连接归属更复杂。

---

## 4. HAKO 与妙搭：可类比和不可类比的边界

### 4.1 飞书公开事实

飞书官网公开材料将妙搭描述为企业场景的 AI 原生系统搭建工具，并公开提到：

- 通过自然语言生成网页、业务工具和可上线系统；
- 多 Agent 参与需求分析、功能设计、数据管控、应用开发和问题修复；
- 可局部精调、一键修复，服务端 API 支持 GUI 调试和日志查看；
- 可配置和测试 AI Prompt/模型能力；
- 具备数据持久化、飞书生态和消息能力。

这些是产品层公开信息，**不能据此推断妙搭内部一定使用 gRPC、Kata、某种调度器或与 HAKO 相同的 Worker 模型**。

### 4.2 能力层映射

| 妙搭公开能力 | HAKO 中可关联的经验 | 边界 |
|---|---|---|
| Agent 调用工具完成开发 | MCP 工具与 Action 注册表 | HAKO 不负责需求到代码的多 Agent 规划 |
| 云端/远端执行 | Server 路由到 Worker | HAKO Worker 当前不等于弹性云沙箱 |
| 长任务与修复 | 异步任务、查询、取消 | 未实现完整工作流 DAG、checkpoint 和自动重试 |
| API/日志调试 | Shell、文件、搜索、插件 | HAKO 尚无成熟 GUI 调试台和全链路 Trace UI |
| 数据与权限 | owner/shared/occupied 数据模型、认证 | 当前租户授权闭环不完整 |
| 专业 Agent/能力扩展 | Plugin + Skill 发现和执行 | 不是完整 Agent marketplace 或版本治理平台 |

### 4.3 面试中推荐的连接句

> 我认为 HAKO 和妙搭相似的不是产品形态，而是底层工程问题：如何把模型产生的不确定工具调用，转化为可授权、可调度、可观察、可取消的远端执行。HAKO 做出了这个闭环的原型；妙搭这样的企业平台还必须解决强隔离、多租户、持久化工作流、弹性容量和产品化调试体验。

---

## 5. 高频追问与参考答案

## A. 项目定位与产品取舍

### Q1：为什么不直接用 SSH？

**答：** SSH 适合人或脚本远程登录，但不天然提供 Agent 需要的工具 schema、结构化参数、能力发现和结果类型。HAKO 用 MCP 向 Agent 暴露明确工具，用 Proto 定义操作，并在 Worker 做白名单、路径和 action 权限校验。SSH 可以作为底层通道备选，但如果直接把任意命令交给 Agent，最小权限、审计和跨平台语义会更差。

### Q2：为什么不在每台机器直接部署 MCP Server？

**答：** 单机 MCP 适合一个 Agent 对一个环境。HAKO 需要让 Agent 查询多个 Worker、按 worker_id 路由、统一认证并支持 NAT 后设备，所以增加中心控制面。代价是控制面高可用、状态一致性和背压问题变复杂。

### Q3：HAKO 是 Agent 框架吗？

**答：** 不是。HAKO 不负责 Planner、ReAct 循环、模型选择或多 Agent 协作，它是 Agent 的远程工具和执行基础设施。这个边界反而使它可以被不同 Agent/harness 复用。

### Q4：这个项目最大的技术价值是什么？

**答：** 不是工具数量，而是端到端链路：标准工具协议、跨网络控制面、长连接 Worker、同步/异步生命周期、取消、权限和扩展机制。它把“Agent 会调用工具”推进到“工具在真实远端环境中受控运行”。

### Q5：为什么把 Skill 放在 Worker？

**答：** Skill 往往与机器上的插件、凭证、工具链和仓库环境绑定。Worker 注册插件并暴露 Skill 文档，Agent 按需发现后再执行脚本，可以让知识描述与执行能力一起部署。企业化后还需要签名、版本、依赖、来源和租户授权治理。

## B. 协议、长连接和网络

### Q6：为什么 Worker 主动建立双向流？

**答：** 这样 Worker 只需要出站访问 Server，无需公网 IP 或开放入站端口，适配个人设备、开发机和企业内网。一个流同时承载任务下发、心跳、结果和文件块，减少连接管理成本。

### Q7：双向流断了会怎样？

**答：** 当前 Worker 有心跳和重连，Server 会把 Worker 标记为 offline。但源码中断连时没有立即给该 Worker 的 pending Future 设置异常，同步调用可能等到超时。改进方式是连接带 generation/epoch，断连时只清理同代连接并立即失败或重新排队相关任务。

### Q8：如何防止旧连接覆盖新连接？

**答：** 当前重复 Worker ID 会被拒绝，但审阅发现一个风险：重复注册路径已经记录 `worker_id` 后进入 `finally`，可能调用 `unregister(worker_id)` 把原连接注销。应保存本次成功注册得到的 connection/generation，只允许连接拥有者做 compare-and-delete。

### Q9：同一 gRPC 流能否多协程同时写？

**答：** 当前注册/心跳响应和任务分发可能走不同协程写同一个流，这是潜在并发写风险。更稳妥的设计是每个 Worker 一个有界 outbound queue 和唯一 writer coroutine，所有消息只入队，统一序列化写流。

### Q10：Proto 如何演进？

**答：** 使用 `oneof` 表达操作类型，新增操作时增加字段号；删除字段时使用 `reserved` 防止复用；Server/Worker 做版本与 capability 协商。不能只假设所有 Worker 同时升级，应允许控制面按 Worker 版本拒绝不支持操作。

## C. 任务语义、可靠性和调度

### Q11：当前任务交付语义是什么？

**答：** 接近 at-most-once。Server 的发送队列和 pending Future 在内存里，没有持久化任务账本、投递 ACK 和重放；Server 重启或连接在关键窗口中断可能丢任务。不能宣称 exactly-once。

### Q12：如何做到 at-least-once？

**答：** 先持久化任务，再投递；Worker 收到后返回 ACK；任务带租约，超时可重派；Worker 对 `task_id` 做幂等去重并持久化终态；结果提交也要可重试。对于 Shell 这种有副作用操作，at-least-once 会带来重复执行风险，所以还需要幂等键、操作类型分级或人工确认。

### Q13：为什么 exactly-once 很难？

**答：** 网络超时不能区分“没执行”还是“执行了但结果丢失”。跨 Server、Worker 和外部系统没有统一事务。工程上通常实现至少一次投递 + 幂等执行，或针对不可幂等动作提供操作日志、去重键和补偿。

### Q14：取消任务如何处理竞态？

**答：** 当前取消是发给 Worker 的协作式操作。必须定义终态机，例如 `PENDING → RUNNING → SUCCESS/FAILED/CANCELLED/TIMED_OUT`，并规定当完成与取消同时发生时哪个基于 CAS/版本号先落库谁生效。取消还要终止进程树而不只是父进程，并设置 grace period 后强杀。

### Q15：如何做背压？

**答：** 三层：入口按租户和 Worker 做并发/速率限制；Worker outbound queue 有界，满时拒绝或排队；Worker `TaskManager` 限制实际执行并发。文件流不能无限创建后台写任务，应由下游消费速度自然反压。还要区分交互任务与批处理任务的队列和优先级。

### Q16：如何调度 Worker？

**答：** HAKO 当前以显式 `worker_id` 为主，模型已有 free/busy/shared/occupied。云平台化后应做两阶段调度：先按 OS、架构、工具链、插件、镜像和租户隔离做硬过滤，再按负载、数据局部性、缓存命中、启动时间和成本评分。资源需要 request/limit，不应只看 CPU 核数。

### Q17：Server 如何横向扩容？

**答：** 双向流只能被某个 Server 实例持有。因此需要在共享注册表记录 `worker_id → server_instance + connection_epoch`，任务先进入持久化队列或消息总线，再路由到拥有连接的实例。实例故障后租约过期，Worker 重连并重新登记。任务状态、连接状态和业务状态要分开建模。

### Q18：Server 重启怎么办？

**答：** 当前启动时可将历史在线 Worker 重置为 offline，等待重连，但内存中的 pending Future 会丢失。企业化后任务状态必须持久化，重启后扫描非终态任务，根据是否已 ACK、租约和幂等能力决定重投、失败或等待 Worker 上报。

## D. 安全、鉴权和多租户

### Q19：HAKO 做了哪些安全控制？

**答：** Client 侧有设备注册、Ed25519 challenge-response 和有时限 Session Token；Worker 有独立 Token 和身份绑定；gRPC 可配置 TLS/mTLS；Worker 有 per-action 权限、Shell 命令白名单、工作区路径校验、文件大小和并发限制。Shell 使用 `create_subprocess_exec` 参数数组，而不是直接解释任意 shell 字符串。

### Q20：它为什么仍不算安全沙箱？

**答：** 因为进程仍在 Worker 宿主 OS 上运行，和宿主共享内核、用户空间环境及可见网络。白名单和路径校验只能降低风险，无法替代内核级或 VM 级隔离；允许的解释器也可能成为间接逃逸通道。

### Q21：路径穿越如何防？

**答：** `validate_workspace_path()` 要求路径位于绝对项目根目录下，并用路径分隔符边界避免 `/root/a` 与 `/root/abc` 的前缀误判；对已存在路径做 `realpath`，防止符号链接指向根目录外。仍需考虑 TOCTOU，强安全实现应使用目录 FD + `openat2`、`RESOLVE_BENEATH/NO_SYMLINKS` 等内核能力。

### Q22：命令白名单是否足够？

**答：** 不够。例如允许 `python`、`node`、`powershell` 后，几乎可以做任意系统调用。白名单适合降低误操作，不是租户隔离。企业级环境应把解释器放在沙箱中，配合只读根文件系统、最小 capabilities、seccomp、cgroup、网络策略和短期凭证。

### Q23：如何设计企业级 Agent Sandbox？

**答：** 我会把一次任务或一个会话绑定到独立 Sandbox。控制面创建 Sandbox，注入只对该任务有效的代码、依赖和短期凭证；运行时使用 Kata/microVM 提供独立 Guest Kernel，外层再用 cgroup 限 CPU/内存/PID/IO，网络默认拒绝并按域名或服务授权，工作区使用快照/overlay，结束后销毁。日志、产物和审计通过受控通道导出。

### Q24：为什么考虑 Kata 而不是普通容器？

**答：** 对不可信 Agent 代码，多租户共享宿主内核的风险更高。Kata 以 microVM/独立 Guest Kernel 提供更强边界，同时保留 CRI/containerd 的容器工作流。代价是冷启动、内存开销和密度，因此要结合预热池、镜像快照和工作集内存做容量规划，而不是绝对化说某种方案最好。

### Q25：当前多租户做到什么程度？

**答：** 数据模型已有 `user_id`、Worker `owner_id/is_shared/occupied_by`，说明已有租户和共享概念；但部分 API 仍使用默认用户，而且 `ClientAuthInterceptor` 主要验证“是谁”，在 `SubmitTask/DownloadFile/SetWorkerStatus` 等路径没有形成完整的资源级授权闭环。因此准确说法是“已有模型基础，授权仍需完善”。

### Q26：认证和授权有什么区别？

**答：** 认证回答“你是谁”，授权回答“你能否操作这个 Worker/任务/文件”。HAKO Client/Worker 身份认证已较完整，但企业场景必须在每个 RPC 做 tenant、owner、share、occupation、action scope 和数据范围校验，并记录审计日志。

### Q27：源码审阅还发现了什么鉴权风险？

**答：** `_AbortHandler.service()` 固定构造 unary-unary handler，但被保护的接口包含 server-streaming 下载。应按 RPC cardinality 返回对应 abort handler，否则异常鉴权路径可能行为不正确。下载本身还要校验任务归属和 Worker 访问权。

### Q28：凭证如何安全注入？

**答：** 不把长期密钥写进镜像或 Prompt。控制面根据任务身份向 Secret Manager 换取短期、最小权限凭证，通过内存、tmpfs 或 sidecar 注入；日志默认脱敏；任务结束立即撤销。外部 API 权限最好按工具能力代理，而非把原始密钥交给 Agent。

## E. 可观测性、测试和性能

### Q29：需要哪些指标？

**答：**
- 控制面：在线 Worker、连接重连、队列深度、提交/下发/ACK/完成延迟、错误码。
- Worker：并发、CPU/内存/磁盘/进程数、任务启动和执行耗时、取消成功率。
- Agent：每个任务的模型调用、工具调用次数、失败重试、token/成本、最终完成率。
- Sandbox：冷/热启动、镜像拉取、P95/P99 RSS、OOM、网络拒绝和逃逸告警。

### Q30：Trace 怎么设计？

**答：** 从用户请求生成 `trace_id`，每个 Agent step 有 `span_id`，工具调用生成 `task_id`，所有 MCP、gRPC、队列、Worker Action 和子进程日志都携带这些 ID。敏感参数只记录哈希或脱敏摘要。这样能回答是模型规划错、路由慢、Sandbox 启动慢还是命令执行失败。

### Q31：怎么测试这类系统？

**答：**
1. 单元测试：路径边界、白名单、状态机、Proto 兼容。
2. 契约测试：Client/Server/Worker 多版本兼容。
3. E2E：文件、Shell、异步、取消、插件和下载。
4. 故障注入：断网、重复注册、Server 重启、Worker 崩溃、结果丢包、磁盘满。
5. 安全测试：路径穿越、symlink、解释器绕过、越权、Secret 泄漏。
6. 压测：任务提交、长连接数、队列、文件传输、Sandbox 冷启动与内存工作集。

### Q32：现有 E2E 能证明什么，不能证明什么？

**答：** 能证明一台 Windows Worker 上主要功能链路可工作，非法命令能被拒绝，异步查询/取消和插件链路可用。不能证明 Linux/macOS 一致性、并发稳定性、断网恢复、安全无漏洞或生产 SLA。两项 grep 警告也说明测试应校验语义而不只是“命令执行成功”。

### Q33：如何评估云端 Sandbox 容量？

**答：** 不直接用 Guest 标称内存除宿主内存，而是用单 Sandbox 的 P95/P99 实际工作集 + VMM/Guest 开销，并给宿主和突发留余量：

```text
安全数量 ≈ (宿主总内存 - 宿主预留)
          / (单 Sandbox P95 实际内存 + VM 开销)
```

例如 128 GB 宿主、单 Sandbox 最大 8 GB：如果要求随时硬保证 8 GB，实际应预留后按约 12～14 个规划；超过 16 个依赖内存超分，只能在平均工作集显著低于 8 GB 且有 OOM/驱逐策略时压测验证。

### Q34：如何降低 Sandbox 冷启动？

**答：** 预拉镜像、精简 Guest Kernel/rootfs、使用 snapshot/restore、维护按镜像和租户分层的预热池、把依赖缓存放在只读共享层、并异步准备工作区。预热池必须防止跨租户残留，需要 reset 或直接销毁重建。

## F. 妙搭/Agent 平台专属追问

### Q35：多 Agent 为什么不一定优于单 Agent？

**答：** 多 Agent 增加角色专门化和并行能力，但也引入上下文传递损失、冲突、成本和调度复杂度。应该按可度量的子任务边界拆分，例如需求分析、数据建模、前端生成、测试修复；共享结构化 artifact，而不是靠自然语言互相转述一切。最终要用成功率、耗时、成本和人工返工评估。

### Q36：怎样让自然语言生成的应用可控？

**答：** 将自由文本逐步收敛成结构化中间表示：需求规格、数据模型、权限矩阵、页面/组件树、API schema、测试用例和部署计划。每一步都有校验器、diff 和用户确认；Agent 修改的是声明式模型或受限代码区域，发布前经过静态检查、测试、权限审计和预览环境。

### Q37：Agent 出错后如何自动修复？

**答：** 先把错误变成可消费的结构化反馈：构建日志、测试失败、浏览器截图/DOM、API trace、数据库 migration 错误。修复 Agent 只能拿到必要上下文和受限工具，生成 patch 后重新执行最小验证门。设置最大迭代次数和相同错误熔断，避免无限循环和成本失控。

### Q38：如何防止 Agent 修改不该修改的内容？

**答：** 工具层做 scope：限定仓库、目录、文件类型和操作；变更层生成 diff 并做 policy check；高风险操作要求人工确认；执行层在一次性 Sandbox 中完成；发布层使用独立身份和审批。不要仅靠 system prompt 约束。

### Q39：如何管理长达数小时的 Agent 任务？

**答：** 把对话请求转成持久化 Task/Workflow，按 step checkpoint。每一步记录输入、artifact、工具结果和模型版本；Worker 使用租约领取任务；失败可从安全 checkpoint 恢复；用户可以暂停、取消、继续。模型会话不是任务状态的唯一来源。

### Q40：Agent 平台最关键的护城河是什么？

**答：** 不只是模型，而是高质量业务上下文、可靠工具、执行环境、评测数据和安全治理形成的闭环。对妙搭这类产品，需求到数据模型/权限/可运行应用的结构化中间表示，以及失败样本驱动的持续评测，会比简单 Prompt 更难复制。

---

## 6. 简历结合：如何把经历串成一条线

### 推荐主线

> 我不是只做过单点 LLM Demo。我过去的经历一直在解决“把智能能力放进真实工程系统”这件事：早期做 RPA Runtime、Native Bridge 和低代码平台，理解可视化编排与受控执行；后来做 RAG、异步任务和企业数据；在微软做分布式构建、Pipeline 隔离和 Agent harness；HAKO 则把这些经验汇总成 MCP + 控制面 + Worker 的远程执行平台。

### 与妙搭岗位的对应关系

- **低代码/产品生成**：星原 RPA + AI 低代码、早期 UI 低代码 MES。
- **运行时与工具**：RPA Executor、Native Bridge、HAKO Action/Plugin/Skill。
- **复杂工程环境**：Edge Build、RBE/Siso、Pipeline、私有开发机。
- **Agent 落地**：Pump 分布式 Agent、Agent harness、Code Review Agent。
- **效果评测**：Code Review Agent 的奖励函数、知识和特征维护。
- **企业安全**：Pipeline Network Isolation、HAKO 权限与路径边界。

### 面试官可能挑战的点

1. **“HAKO 看起来像业余项目，规模证据在哪里？”**  
   回答：诚实承认尚未大规模生产，重点说明自己完成了哪些系统闭环、E2E 覆盖和已知缺口；再结合微软的真实分布式构建/Agent 落地经验说明具备生产意识。
2. **“为什么简历没写 HAKO？”**  
   回答：它是近期用于验证 Agent 远程执行架构的独立项目，尚未用未经验证的指标包装进简历；面试中愿意用源码和设计取舍展开。
3. **“这个项目是不是包装出来的？”**  
   回答时主动说出真实 bug、限制和源码路径。能解释 `TaskService`、双向流、`TaskManager`、路径校验及交付语义，比只讲架构图更可信。
4. **“你做的是平台还是 Agent？”**  
   回答：两边都做过。Code Review Agent 更偏业务 Agent 与评测；HAKO 更偏 Agent Runtime/Infra；妙搭需要的正是把 Agent 能力与平台工程结合。

---

## 7. 反问面试官（选 3～5 个）

这些问题既能获取信息，也能展示架构意识；不要暗示你知道内部实现。

1. 妙搭目前 Agent 运行时更偏“每次任务独立 Sandbox”，还是“用户/项目级长生命周期环境”？选择背后的主要约束是什么？
2. 需求、数据模型、权限、页面和代码之间是否有统一的结构化中间表示？Agent 之间主要传自然语言还是 artifact？
3. 团队当前最难的指标是生成成功率、长任务可靠性、Sandbox 成本、首屏速度，还是线上应用稳定性？
4. Agent 修改应用后，平台如何做回归验证、权限 diff 和安全发布？
5. 多 Agent 的拆分是固定角色还是按任务动态规划？如何衡量它相对单 Agent 的真实收益？
6. 对长任务，是否支持 checkpoint、暂停恢复和失败重放？任务状态与模型会话如何解耦？
7. 云端执行环境如何处理依赖缓存、Secret 注入、网络出口和租户隔离？
8. 这个岗位入职前三个月最希望解决的工程问题是什么？

---

## 8. 面试表达红线

### 不要这样说

- “妙搭内部肯定也是 gRPC + Kata。”
- “HAKO 已经是企业级多租户云沙箱。”
- “任务 exactly-once。”
- “命令白名单保证安全。”
- “E2E 全部通过，没有问题。”
- “HAKO 支持高并发/高可用。”（没有压测和多实例证据）
- “8 GB Sandbox 在 128 GB 机器上可以稳定跑 32 个。”

### 应该这样说

- “这是基于公开能力做的架构类比，不代表妙搭内部实现。”
- “当前实现……；如果面向企业级场景，我会……”
- “源码事实是……；由此我判断的风险是……”
- “E2E 证明主链路可用，但并不等于生产规模验证。”
- “安全是分层防御，白名单和路径限制不是强隔离。”

---

## 9. 面试前 20 分钟速记卡

### 架构

`Agent → MCP Client → TaskService → WorkerManager queue → gRPC bidi stream → Worker Action → TaskManager → subprocess/file/plugin`

### 三个亮点

- Worker 主动长连接，适配 NAT。
- MCP/Proto/Action 分层，可扩展。
- 同步 + 异步任务，支持查询和取消。

### 五个真实缺口

- pending task/连接状态在内存。
- 断连 Future 不立即失败。
- 重复注册可能误注销旧连接。
- 同一流潜在多 writer。
- 资源级授权和下载完整性不足。

### 安全层次

认证 → 授权 → 工具权限 → 路径/命令限制 → Sandbox → cgroup/网络 → Secret → 审计。

### 云平台演进

持久化任务 → ACK/租约/幂等 → Kata Sandbox → 多实例连接路由 → Trace/指标/审计 → 容量与成本。

### 最后一段收尾

> HAKO 不是我拿来声称已经做出妙搭的平台，而是证明我对 Agent 执行基础设施有源码级实践。我既能做 Agent 业务和评测，也做过低代码、RPA Runtime、分布式构建和安全隔离。我希望把这些经验用于解决妙搭从自然语言意图到可靠可运行系统之间的工程问题。

---

## 10. 资料与源码索引

### HAKO 关键源码

- `ARCHITECTURE.md`
- `proto/worker.proto`
- `client/mcp_server.py`
- `client/grpc_client.py`
- `server/src/grpc_server/manager.py`
- `server/src/grpc_server/task_service.py`
- `server/src/grpc_server/worker_service.py`
- `server/src/grpc_server/client_interceptor.py`
- `server/src/grpc_server/auth_service.py`
- `server/src/service/client_auth_manager.py`
- `worker/worker/core/worker_instance.py`
- `worker/worker/core/task_manager.py`
- `worker/worker/action/__init__.py`
- `worker/worker/action/actions.json`
- `worker/worker/action/base.py`
- `worker/worker/action/shell.py`
- `worker/worker/security/validate.py`
- `worker/worker/security/shell_policy.py`
- `worker/worker/core/config.py`
- `e2e_test/report.md`

### 飞书公开材料

- 飞书官网：《飞书妙搭：AI原生系统搭建工具，对话就能生成网页和应用！》  
  https://www.feishu.cn/content/article/7592171136612306139
- 飞书官网：《如何零代码搭建企业专属业务系统，飞书妙搭帮你！》  
  https://www.feishu.cn/content/article/7579519065685937094
- 妙搭公开主页 / Showcase  
  https://miaoda.feishu.cn/landing

> 注意：飞书官网部分文章标注为由 AI 基于知识库生成。面试时可引用其公开产品描述，但不要把营销内容当作内部技术设计证据。

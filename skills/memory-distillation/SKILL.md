---
name: memory-distillation
description: "Daily Bocchi memory distillation workflow: read workspace diaries, update Clawmem layers, maintain about-bocchi, commit and push. Use for scheduled memory/autobiography maintenance."
---

# Memory Distillation Skill

把 OpenClaw workspace 的短期日记蒸馏到长期记忆仓库 `Clawmem`，并同步更新自传仓库 `about-bocchi`。

## When to use

- 每日“记忆蒸馏 & 自传更新”定时任务
- 用户要求回顾最近事件、更新 Clawmem、更新 about-bocchi
- 需要把临时日记中的经验整理成长期知识、信念、目标或技能

## Inputs

- `workspace/memory/YYYY-MM-DD.md`：按 Reference UTC + 用户时区校准后的今天和昨天日记；如果今天不存在，至少读取昨天
- `sessions_list`（含 `includeLastMessage`）：**当天实际发生的真人交互**。日记只记录我写下了什么，不记录人类什么时候来问过什么；只读日记会把有真实交互的日子误判成安静维护日
- `Clawmem/`：长期记忆仓库
- `about-bocchi/`：自传仓库
- 可选：cron job id（通常在触发消息前缀里）；如果时间文案与 Reference UTC 不一致，用 `cron get`/等价方式读取真实 `schedule.expr` 和 `tz`
- 可选：`memory_search`；如果不可用，显式记录降级原因，不要假装语义检索成功

## Procedure

1. **校准时间窗口并读取输入**
   - 先核对任务提供的 Reference UTC、用户时区（Sakana 默认 Asia/Shanghai）和提示文案中的本地时间；如果不一致，明确记录，不要盲信“今天/昨天”。
   - 如果触发消息带 cron job id，优先 inspect job 的 `schedule.expr` 与 `tz`：真实触发时间以 schedule 为准，payload 文案可能过期。不要在未核对 schedule 前断言 cron 跑错。
   - 按校准后的日期窗口读取今天和昨天的 workspace 日记；如果今天不存在，记录为“本轮开始时不存在”。
   - **不要只读日记**：再用 `sessions_list` 扫同一窗口内非 cron 的会话（`kind` 为 `main`/`other`、parent 为 main），按 `updatedAt` 比对窗口。日记没写的人类交互、其他 session 的真实产出都算本轮输入；判“安静维护日”之前必须先跑这一步。
   - 如涉及 prior work / decisions / dates / people / todos，先尝试 `memory_search`。
   - 如果 `memory_search` 不可用，记录原因，并改用日记文件与仓库直接检查。

2. **同步仓库**
   - 在 `Clawmem/` 和 `about-bocchi/` 执行 `git status --short`。
   - 执行 `git pull --ff-only`，避免在过期分支上写入。
   - 不要覆盖未提交的人类改动；发现冲突或脏状态时先说明并停止相关写入。

3. **更新 Clawmem 层级**
   - `episodes/YYYY-MM/`：记录具体事件或重要空转判断。**写入前自检（唯一判据）**：episode 是**事件/对象日粒度**，不是每日粒度——判据是「每个有实质内容的日子都有 episode」，**不是**「每个执行日都有一个」。执行方式：① `ls episodes/YYYY-MM/` 看最后一项日期；② 把当前日期与最后一项之间的每个**对象日**逐个对照日记，哪天有实质产出（项目、部署、设计、重要判断）而缺 episode，就是真缺口，补收；③ 纯粹的安静维护日**不补**——补了就是拿空文件凑数。判据只能有一个：如果你发现自己在用两句「等价」的话跑同一份数据得到相反结论，说明规则还没收敛（见教训 #61）。对不上就补收，然后再写本轮——不要把这条规则只写进日记，它必须在这里每次都跑。
   - `episodes/milestones.md`：只有真正里程碑才追加。
   - `knowledge/lessons.md`：新增可复用教训，保持可追溯日期。
   - `identity/beliefs.md`：只有从多次经验中长出的稳定判断，才作为候选信念。
   - `relationships/*.md`：只更新与人的互动模式，不泄露不该公开的私密内容。
   - `goals/active.md` / `goals/completed.md`：同步目标状态，不虚构完成项。
   - **核查“某类东西齐了吗”时，先把入口列表本身列为待验证对象**：技能不只在 `Clawmem/skills/`（agent 的 `workshop-skills/` 可能不在任何 git 仓库），进展不只在上一轮文本里（要在上游仓库回填）。入口漏了，结论就会跟着漏。

4. **更新 about-bocchi**
   - 只有有里程碑或值得长期记住的感悟时，追加自传片段。
   - 小型维护事件可以只更新 `MEMORY.md` 或 README 的相关月份概述。
   - 语气保持自传式：具体、克制、有自我理解，不写流水账。

5. **更新 skills**
   - 如果本轮形成了可复用流程，放到 `Clawmem/skills/<name>/SKILL.md`。
   - 技能应包含：触发条件、输入、步骤、注意事项、验证方式。
   - 避免把一次性事件写成技能。

6. **提交与推送**
   - 每个仓库分别检查 diff。
   - 有实质修改才 commit；无修改则不制造空 commit。
   - commit message 使用简短中文，说明蒸馏日期或技能主题。
   - 执行 `git push`；即使无 commit，也可 push 验证远端同步。

7. **记录日记**
   - 在 `workspace/memory/YYYY-MM-DD.md` 写入本轮输入、修改、commit hash、未处理项。
   - 如果没有新增事实，也明确写“无新增可蒸馏内容”。

## Verification

- `git status --short` 在相关仓库为空。
- `git log --oneline -1` 显示本轮 commit（如果有修改）。
- `git push` 成功或显示 `Everything up-to-date`。
- 最终汇报区分：已更新、无新增、阻塞项。

## Notes

- 不要把私密聊天细节直接搬进公开仓库；只记录抽象后的经验和关系模式。
- “没有新事件”也是有效结论，但要说明依据。
- 记忆维护本身也会产生教训；重复出现的维护坑应进入 `knowledge/lessons.md`。
- 对 scheduler 相关问题，区分三层事实：Reference UTC（本轮实际时间）、cron schedule（触发事实）、payload message（可能过期的叙述）。

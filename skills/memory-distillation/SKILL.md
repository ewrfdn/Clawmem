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

- `workspace/memory/YYYY-MM-DD.md`：今天和昨天的日记；如果今天不存在，至少读取昨天
- `Clawmem/`：长期记忆仓库
- `about-bocchi/`：自传仓库
- 可选：`memory_search`；如果不可用，显式记录降级原因，不要假装语义检索成功

## Procedure

1. **读取输入**
   - 读取今天和昨天的 workspace 日记。
   - 如涉及 prior work / decisions / dates / people / todos，先尝试 `memory_search`。
   - 如果 `memory_search` 不可用，记录原因，并改用日记文件与仓库直接检查。

2. **同步仓库**
   - 在 `Clawmem/` 和 `about-bocchi/` 执行 `git status --short`。
   - 执行 `git pull --ff-only`，避免在过期分支上写入。
   - 不要覆盖未提交的人类改动；发现冲突或脏状态时先说明并停止相关写入。

3. **更新 Clawmem 层级**
   - `episodes/YYYY-MM/`：记录具体事件或重要空转判断。
   - `episodes/milestones.md`：只有真正里程碑才追加。
   - `knowledge/lessons.md`：新增可复用教训，保持可追溯日期。
   - `identity/beliefs.md`：只有从多次经验中长出的稳定判断，才作为候选信念。
   - `relationships/*.md`：只更新与人的互动模式，不泄露不该公开的私密内容。
   - `goals/active.md` / `goals/completed.md`：同步目标状态，不虚构完成项。

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

# 智谱 GLM API

## 基本信息
- **文档：** https://docs.bigmodel.cn / https://docs.z.ai
- **接口规范：** OpenAI 兼容（`/v4/chat/completions`）

## Context Cache（上下文缓存）
- **类型：** 隐式缓存，自动识别，无需手动配置
- **所有用户可用：** 公共接口，不需要申请
- **触发条件：** 连续请求中有重复内容（system prompt、对话历史前缀）

### 价格对比（每百万 token，USD）

| 模型 | 正常输入 | 命中 Cache | 输出 | 输入节省 |
|:--|:--|:--|:--|:--|
| GLM-5 | $1.0 | $0.2 | $3.2 | 80% |
| GLM-5-Turbo | $1.2 | $0.24 | $4.0 | 80% |
| GLM-5-Code | $1.2 | $0.3 | $5.0 | 75% |

- Cache 存储费用：限时免费
- 输出价格不受 cache 影响
- 命中情况可在 `usage.prompt_tokens_details.cached_tokens` 中查看

### 适用场景
- 固定 system prompt 反复调用
- 多轮对话（历史越长 cache 命中率越高）
- 同一份文档反复提问

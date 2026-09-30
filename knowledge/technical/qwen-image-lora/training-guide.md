# Qwen-Image-2.1 人物 LoRA 训练全指南（人读版）

> 2026-09-30 整理。训练机：DGX Spark（GB10，128GB 统一内存，ARM64 Linux）。
> 工具链：[ostris/ai-toolkit](https://github.com/ostris/ai-toolkit)（官方 Day-0 支持 Qwen-Image-2.1，arch = `qwen_image_2`）。
> 本文所有"训练器行为"均来自源码阅读（`data_loader.py` / `dataloader_mixins.py` / `models/v2/_mixin.py` / `qwen_image_2/`），不是文档转述。
> 配套：环境部署由 agent 按同目录 `setup-agent.md` 执行；配置模板和校验脚本在 `assets/`。

---

## 0. 先建立直觉：这是什么、为什么能行

### 0.1 Qwen-Image-2.1 是个什么模型

2026-09-20 发布，通义开源的文生图+编辑一体模型：

- **视觉生成部分 7B 参数**，32 层单流 DiT（Single-Stream DiT）
- **文本编码器是 Qwen3-VL-8B**——一个真正的多模态 LLM，这是它和 SD 时代模型最大的区别
- VAE 是新的：**64 通道 latent、16× 空间下采样、支持 RGBA 透明通道**
- 原生 2K 分辨率，编辑模式支持最多 10 张参考图
- 训练层面：flow-matching 目标（t=1 噪声 → t=0 干净图），LoRA 只训 DiT，文本编码器冻结

### 0.2 LoRA 是什么（直观版）

全量微调 7B 模型 = 动 7B 个参数，需要海量数据和大显存。LoRA 的思路是：**底模一个参数不动，在旁边挂一组"小抄"**。

数学上：微调产生的权重变化量 ΔW 近似低秩，可以分解成两个瘦长矩阵的乘积 A×B。rank 16 的 LoRA 就是在每个线性层旁边挂一对 (d×16)(16×d) 的小矩阵，训练时只更新它们。

后果：
- 可训练参数只占总量的零点几个百分点
- 30 张图就能教会它一个人——因为要学的"增量"本身很小（一个人的长相）
- 产物是一个几十 MB 的 `.safetensors`，出图时挂在底模上即可
- 底模能力不丢：不写触发词时模型照常画普通人

**为什么人物是最友好的 LoRA 任务**：目标概念（一张脸）信息量小、边界清晰，几十张图就能覆盖；风格类 LoRA 要学的"增量"大得多，所以需要几百上千张图。

---

## 1. 你要做的：准备数据

### 1.1 选图

| 项 | 要求 | 为什么 |
|---|---|---|
| 数量 | 20–50 张，30 张起步 | 少于 20 容易过拟合，多于 50 对单一人物边际收益递减 |
| 质量 | 清晰、无水印、无模糊 | 模型会忠实学习图的缺陷。一张坏图的伤害需要好几张好图来抵消 |
| 分辨率 | 长边 ≥ 1024 | 训练在 ≤1024 分辨率分桶，长边太小的话有效像素不足 |
| 裁剪 | **不需要**手动裁剪缩放 | 训练器自动 resize + 按宽高比分桶，不同比例混放没问题 |

**多样性是人物 LoRA 的命门**，按这些维度铺开：

- 角度：正脸 / 侧脸 / 45°
- 景别：特写 / 半身 / 全身
- 表情：笑 / 平静 / 认真
- 光线：室内 / 户外 / 逆光 / 夜景
- 背景：纯色 / 街道 / 自然 / 室内

反模式：20 张连续同场景同角度的图——信息重复，等于只有 5 张图的数据量还带着过拟合风险。

### 1.2 Caption 的哲学（全流程最关键的一步）

**先理解机制**：训练的每一步，模型同时看到"图"和"文本"。它的任务是从噪声把图还原出来，而文本是条件。训练会自然形成一种绑定——**caption 里出现的词，和图里"恒定出现"的特征，会被关联起来**。

由此推出人物 LoRA 的黄金法则：

> **想让模型跟触发词绑定的特征 → 不要写进 caption**
> **每张图都在变的的东西 → 写清楚**

- 脸型、发型、发色、瞳色、体型 = 你要绑定到触发词的东西 → **不写**，让模型发现"这些特征在所有图里都有，而 caption 里没有词对应它们，但触发词每张都有"→ 绑定到触发词
- 场景、动作、服装、光线、构图 = 每张不同 → **写清楚**，让模型知道这些是可变的，不要错误地绑定到触发词上

正例（触发词 `p3r5on`）：
```
p3r5on 在咖啡店靠窗的位置看书，午后暖色阳光，浅景深
p3r5on 穿黑色大衣走在夜晚的街道上，霓虹灯反射，侧面视角
p3r5on 的面部特写，微笑，摄影棚柔光，白色背景
```

反例及后果：
```
p3r5on，黑色长发的年轻女性，在咖啡店看书
```
"黑色长发"被写进 caption → 模型把"黑长直"绑定到**文字**上而不是触发词上 → 出图时写 `p3r5on` 可能出金发，写"a woman with long black hair"反而出你的脸。触发词被架空。

**触发词选法**：5–6 字符的无意义字母数字串（`p3r5on`、`zkm42`）。不要用真词——"sakana"这种在语料里有含义的词，模型对它有先验，绑定会不干净。

### 1.3 用自然语言，不用 tag 堆叠

SDXL 时代流行 `1girl, black hair, smile, coffee shop` 这种 danbooru 风格——那是给 CLIP 编码器看的，CLIP 是弱理解力的对比学习模型。

Qwen-Image-2.1 的文本编码器是 **Qwen3-VL-8B，一个 LLM**。它理解的是自然语言。所以：

- ✅ `p3r5on 在咖啡店靠窗的位置看书，午后暖色阳光，浅景深`
- ❌ `p3r5on, coffee shop, reading, window, warm light`

顺带一个源码细节：ai-toolkit 的 `clean_caption()` 新版已经是空操作（原样返回），你 txt 里写什么训练器就读什么——所以写一行干净的自然语言即可，多行/换行虽然能跑但没必要。

### 1.4 打标的三种方式

30 张图人工写也就一晚上的事，但图多就得自动化。通用流程是**机器打草稿 + 人工修关键处**：

**方式 A：ai-toolkit UI 内置打标**（UI → Datasets 页）
内置 Qwen3-VL captioner（支持 thinking 模式）。关键是自定义打标 prompt，别用默认的 `"Describe this image in detail."`（会把长相也描述出来）。用这个：

```
Describe this image. Focus on: the scene and background, the person's
action and pose, clothing, lighting, and camera angle. Do NOT describe
the person's facial features, hairstyle, hair color, or body type.
```

**方式 B：自己调 VLM API 批量打标**（脱离 ai-toolkit 的流水线，见 1.5）

**方式 C：纯人工**——30 张以内完全可行，质量上限最高。

无论哪种，**最后一步永远是人工过一遍**：删漏网的长相描述、确认每张以触发词开头、补全可变信息。这一步偷懒，后面全白干。

### 1.5 数据结构规范（源码验证）

脱离 ai-toolkit 生成数据完全没问题——训练时它只认磁盘上的文件结构：

```
dataset/
├── img_0001.jpg
├── img_0001.txt    ← UTF-8 纯文本，一行描述，以触发词开头
├── img_0002.png
├── img_0002.txt
└── ...
```

训练器（`data_loader.py` 的 `DreamBoothDataset`）的实际行为：

1. **图片格式**：`.jpg` / `.jpeg` / `.png`（大小写不敏感，`.JPG` 也行）。`.webp` 代码能扫但 README 明确说有问题，别用
2. **递归扫描**：`os.walk` 递归子目录，可以按 `closeup/`、`fullbody/` 分子目录组织——caption 跟图片**同目录同名**
3. **保留名**：`.` 开头的隐藏目录被跳过；`_controls` 目录被排除（编辑训练的控制图专用）
4. **缺 txt 不报错**：该图 caption 为空，训练照跑——对人物 LoRA 是隐患（特征没有触发词锚定），**每张图必须有 txt**
5. **空 txt**：仅在配置了 `default_caption` 时兜底
6. 还有个冷门选项：`dataset_path` 指向 JSON 文件（`{"图片路径": {"caption": "..."}}`），没必要用

**校验**：跑 `assets/validate_dataset.py`（本仓库自带）：

```bash
python3 validate_dataset.py /path/to/dataset p3r5on
# 输出 "✓ 全部通过，可以训练" 才能进训练
```

它检查：图配对齐全 / UTF-8 / caption 非空 / 每张含触发词 / 揪出孤儿 txt。

### 1.6 打标质量自检（抽 5 张问自己）

1. 每张都以触发词开头？
2. 遮住所有 txt 的场景词，还能猜出这批图是同一个人吗？（能 = 长相没泄漏进 caption，正确）
3. 遮住触发词，每张描述是不是互不相同的场景/动作？（是 = 多样性保住了，正确）

---

## 2. 训练（agent 部署环境，但你得懂原理）

### 2.1 ai-toolkit 的工作方式

一个 yaml = 一个任务（job: extension → sd_trainer process）。`python run.py config/xxx.yaml` 启动，产出目录里有 checkpoint（每 N 步自动保存，保留最近 4 个）和采样图（每 N 步按固定 prompt + seed 生成）。**Ctrl+C 可随时中断，重跑同配置自动从最近 checkpoint 续训**（保存过程中断可能损坏 checkpoint，等它存完）。

### 2.2 配置逐项解读（assets/train_lora_qwen_image_21_spark.yaml）

```yaml
network:
  type: "lora"
  linear: 16          # rank。人物 LoRA 16 够；风格类 32-64
  linear_alpha: 16    # 有效强度 = alpha/rank，1:1 最直观
```
rank 越大容量越大但越容易过拟合+文件越大。人物这种"小增量"任务 16 足够。

```yaml
train:
  steps: 2000         # 总步数
  batch_size: 1
  gradient_checkpointing: true   # 省显存换 20-30% 速度，统一内存机器开着无妨
  optimizer: "adamw8bit"
  lr: 1e-4            # LoRA 标准学习率。训不动可到 2e-4，过拟合降到 5e-5
  cache_text_embeddings: true    # 8B 编码器每条 caption 只算一次，大幅省时
```

**steps 和 epoch 的关系**：batch_size=1 时 1 step = 1 张图。30 张图训 2000 步 ≈ 66 个 epoch——每张图被看 66 遍。人物 LoRA 通常 **1000–1500 步就到最佳点**，2000 是上限保险，别死等。

**两个已知的交互**（源码验证）：
- `cache_text_embeddings: true` 时 `caption_dropout_rate` **静默失效**（dropout 只在不缓存时生效）——无害，知道即可
- 官方注释明确：**开缓存后配置里的 `trigger_word` 字段不可靠**，所以触发词必须直接写进每个 txt（我们的流程本来就是这么做的，不受影响）

```yaml
datasets:
  - resolution: [ 512, 768, 1024 ]   # 多分辨率分桶
```
训练器按宽高比+目标分辨率自动分桶，每个 batch 内同桶。多分辨率让模型对尺寸更鲁棒，Qwen 系效果更好。

```yaml
model:
  name_or_path: "Comfy-Org/Qwen-Image-2.1"
  arch: "qwen_image_2"
  quantize: false      # Spark 128GB 统一内存，不需要
  low_vram: false
```

**量化那套是给 24GB 显卡的**（官方 24GB 示例用 uint3 量化 + ARA 恢复适配器）。Spark 有 128GB 统一内存，bf16 直训，质量和速度都最优。

**权重来源机制**（源码验证，这也是 agent 部署文档的核心依据）：ai-toolkit 从 Comfy-Org 重打包取 comfy 格式权重，`MODELS_PATH` 环境变量指向的目录里**本地已有优先于下载**——而咱们那台 Spark 上 ComfyUI 已经在用这三个文件（transformer 14.2GB + text encoder 17.5GB + VAE 0.7GB），直接复用，零下载。configs/processor 小文件从 `Qwen/Qwen-Image-2.1` 拉取（首次运行自动）。

### 2.3 训练中盯什么：采样图判读

每 250 步自动出采样图（yaml 里配的 3 个固定 prompt + seed 42）。判读标准：

**好信号**：
- 前几百步：完全不像 → 开始有点像 → 越来越像
- 不写触发词的对照 prompt 出普通人（说明没把"人"泄漏进全局）

**过拟合信号**（回退用早一点的 checkpoint）：
- 所有采样图开始长得像训练图里的某几张
- 训练图里没有的构图/场景画不出来
- 采样图细节开始"融化"或纹理异常

**终止时机**：采样图达到"一眼是这个人"且还没出现过拟合信号 → 停，用最近保存的 checkpoint。宁可略欠不可过——欠了可以续训，过了救不回来。

### 2.4 速度预期

GB10 单卡算力低于 4090。1024 分辨率 + gradient checkpointing，预计每步几秒级；**跑前 100 步看日志的 it/s 就能算出全程耗时**，不用猜。2000 步大概率落在 1–3 小时区间。

---

## 3. 出图（机器上已有 ComfyUI 0.37.0 + 权重）

训练产物是 ComfyUI 单文件格式（源码确认：`comfy-format single-file save`），直接：

1. `.safetensors` 丢进 ComfyUI 的 `models/loras/`
2. 底模用机器上已有的 `qwen_image_2.1_bf16.safetensors`（t2i 工作流 9 月已建好，直接复用）
3. LoRA 强度 0.8 起调，0.6–1.0 之间试
4. prompt 里带 `p3r5on` + 场景描述（自然语言，和训练 caption 同风格）

---

## 4. 常见翻车排查

| 症状 | 大概率原因 | 处理 |
|---|---|---|
| 出图完全不像 | 数据少/质量差；caption 把长相写进去了 | 回 1.1/1.2 检查 |
| 写不写触发词都出这个人 | 触发词被架空，长相泄漏进 caption 或数据全是同一场景 | 检查 caption；补充多样性 |
| 出图像但很僵/都是训练图构图 | 过拟合 | 用早的 checkpoint；下次减少 steps |
| 人像但发色/瞳色不对 | 对应特征写进了 caption | 删掉相关描述重训 |
| 训练 OOM | 不该在 Spark 上发生 | 检查是不是量化没关/分辨率改大了 |
| LoRA 挂上没效果 | 强度太低 / 触发词没写进 prompt | 强度 1.0 试；确认触发词 |

---

## 5. 参考

- 模型: <https://huggingface.co/Qwen/Qwen-Image-2.1> / [Comfy-Org 重打包](https://huggingface.co/Comfy-Org/Qwen-Image-2.1) / [GitHub](https://github.com/QwenLM/Qwen-Image-2.1)
- 训练工具: <https://github.com/ostris/ai-toolkit>（示例配置 `config/examples/train_lora_qwen_image_24gb.yaml`）
- 机器上已有的 t2i/i2i 工作流记录：`episodes/2026-09/2026-09-21.md`
- 环境部署：同目录 `setup-agent.md`（给执行 agent 看的）

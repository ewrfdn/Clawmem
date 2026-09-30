# Qwen-Image-2.1 LoRA 训练环境部署（agent 执行手册）

> 目标读者：执行部署的 agent。人读的原理版见同目录 `training-guide.md`。
> 本文的"训练器行为"均有源码依据（ai-toolkit main 分支，2026-09-30 阅读），关键处标注了源文件。

## 目标

在 DGX Spark（GB10）上部署 ostris/ai-toolkit 训练环境，达成状态：**一条命令即可对任意合规数据集启动 Qwen-Image-2.1 人物 LoRA 训练**。

## 0. 机器已知条件

- **DGX Spark**（GB10，128GB 统一内存，ARM64 Linux / DGX OS）——HAKO 体系里的那台 GB10 worker
- 上面已跑着 **ComfyUI 0.37.0**（HAKO 托管，endpoint `https://hako.japaneast.cloudapp.azure.com:443/comfyui`）
- **已有 Qwen-Image-2.1 全套权重**（ComfyUI 布局，2026-09-21 入库）：
  - `diffusion_models/qwen_image_2.1_bf16.safetensors`（14.2 GB）
  - `text_encoders/qwen3vl_8b_bf16.safetensors`（17.5 GB）
  - `vae/qwen_image_2.1_vae_bf16.safetensors`（0.68 GB）

⚠️ 操作机器走 HAKO 通道（先加载 hako-worker skill）。**不得干扰现有 ComfyUI 服务**；不确定的操作先问。

## 1. 前置检查

```bash
# 磁盘：ai-toolkit + venv + 缓存，预留 >= 60 GB（权重复用则无需 32GB 权重空间）
df -h
# Python >= 3.10（3.12 推荐）、git
python3 --version && git --version
# 网络：能否直连 HF
curl -sI --max-time 10 https://huggingface.co | head -1
```

- HF 不通 → 所有涉及 HF 的命令前加 `export HF_ENDPOINT=https://hf-mirror.com`
- 找到 ComfyUI 的 models 目录的**绝对路径**（从 ComfyUI 启动配置/HAKO 元数据里确认，记为 `$COMFY_MODELS`），下文要用

## 2. 安装 ai-toolkit

ai-toolkit 官方支持 ARM64 Linux（README 明确含 DGX Spark / DGX OS）。装到用户目录，如 `~/ai-toolkit`：

```bash
cd ~ && git clone https://github.com/ostris/ai-toolkit.git
cd ai-toolkit
chmod +x run_linux.sh && ./run_linux.sh
```

`run_linux.sh` 是 manager：自动检测硬件、装对 PyTorch 构建、起 UI（localhost:8675）。headless 场景等价命令：

```bash
python3 -m manager install    # 首次安装
python3 -m manager doctor     # 有问题先跑这个
```

manager 失败时手动兜底（README 手动路径）：

```bash
cd ~/ai-toolkit
python3 -m venv venv && source venv/bin/activate
pip3 install --no-cache-dir torch==2.13.0 torchvision==0.28.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu130
pip3 install -r requirements.txt
```

验收：`source venv/bin/activate && python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"` → 输出含 `True` 和 GB10 设备名。

## 3. 权重：复用机器上已有的（零下载）

**源码依据**：`toolkit/paths.py` 定义 `MODELS_PATH`（env var，默认 `<ai-toolkit>/models`）；`toolkit/models/v2/resolver.py` 的 `resolve_comfy_candidates` **先查本地 comfy 布局文件，命中即用，不下载**。三个组件（transformer / text_encoder / vae，见 `extensions_built_in/diffusion_models/qwen_image_2/src/*.py` 的 `aitk_comfy_weight_names`）都注册了这两个文件名：
- `diffusion_models/qwen_image_2.1_bf16.safetensors`
- `text_encoders/qwen3vl_8b_bf16.safetensors`
- `vae/qwen_image_2.1_vae_bf16.safetensors`

机器上 ComfyUI 已有同名同布局文件 → 让 ai-toolkit 直接看到它们即可。**首选符号链接**（不占空间、不会两份）：

```bash
mkdir -p ~/ai-toolkit/models
for d in diffusion_models text_encoders vae; do
  mkdir -p ~/ai-toolkit/models/$d
  # 把 $COMFY_MODELS/$d/ 下对应的 qwen 相关文件软链过来，例如：
  ln -s "$COMFY_MODELS/$d/qwen_image_2.1_bf16.safetensors" ~/ai-toolkit/models/$d/ 2>/dev/null
done
# text_encoder 文件名不同，单独链：
ln -s "$COMFY_MODELS/text_encoders/qwen3vl_8b_bf16.safetensors" ~/ai-toolkit/models/text_encoders/
```

（按实际目录结构调整；目标就是让 `~/ai-toolkit/models/{diffusion_models,text_encoders,vae}/` 下出现上列三个文件名。也可以改用 `export MODELS_PATH=$COMFY_MODELS`，但要确认该目录下没有会干扰的同名旧文件。）

**仍需联网的小文件**：configs、processor、tokenizer 从 `Qwen/Qwen-Image-2.1` 拉（代码里 `aitk_config_repo`，首次运行自动下载，仅几 MB）。确认 HF 可达或设镜像。

**文件缺失时的下载兜底**（仅缺失的组件）：

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 网络不畅时
huggingface-cli download Comfy-Org/Qwen-Image-2.1 \
  diffusion_models/qwen_image_2.1_bf16.safetensors \
  text_encoders/qwen3vl_8b_bf16.safetensors \
  vae/qwen_image_2.1_vae_bf16.safetensors \
  --local-dir ~/ai-toolkit/models
```

## 4. 目录与配置布局

```bash
# 数据集统一放这里（每个 LoRA 一个子目录）
mkdir -p ~/datasets
# 配置
cp <本仓库>/knowledge/technical/qwen-image-lora/assets/train_lora_qwen_image_21_spark.yaml ~/ai-toolkit/config/
cp <本仓库>/knowledge/technical/qwen-image-lora/assets/validate_dataset.py ~/bin/ 2>/dev/null || cp <本仓库>/knowledge/technical/qwen-image-lora/assets/validate_dataset.py ~/datasets/
```

配置模板要点（已按 Spark 调好，不要改回量化版）：
- `arch: "qwen_image_2"`、`name_or_path: "Comfy-Org/Qwen-Image-2.1"`
- `quantize: false`、`low_vram: false`——量化是 24GB 显卡方案，Spark 128GB 统一内存用 bf16 直训
- `folder_path` 训练时由用户改为实际数据集路径
- 触发词必须直接写在每张 caption 里（`cache_text_embeddings: true` 时配置级 trigger_word 不可靠，源码注释明确）

## 5. 冒烟测试（必做，证明全链路通）

```bash
mkdir -p ~/datasets/smoke_test && cd ~/datasets/smoke_test
# 两张随便的图（可用 ComfyUI 生成的旧图复制改名）
cp /path/to/any1.jpg img_001.jpg; cp /path/to/any2.png img_002.png
echo "p3r5on test caption one" > img_001.txt
echo "p3r5on test caption two" > img_002.txt
python3 ~/datasets/validate_dataset.py . p3r5on    # 必须输出 ✓
```

改配置副本：`folder_path: ~/datasets/smoke_test`、`steps: 30`、`save_every: 15`、`sample_every: 15`，然后：

```bash
cd ~/ai-toolkit && source venv/bin/activate
python run.py config/smoke_test.yaml
```

**通过标准**（缺一不可）：
1. 日志出现 `Loading Qwen-Image 2.1 model` 且从本地 models 目录解析权重（无 14GB+ 下载发生）
2. 跑完 30 步不报错
3. `output/<name>/` 下有 checkpoint `.safetensors` 和采样图 `.png`

通过后清理：`rm -rf ~/datasets/smoke_test output/<smoke名> config/smoke_test.yaml`。

## 6. 验收清单

- [ ] `python run.py --help` 正常；torch CUDA 可用
- [ ] `~/ai-toolkit/models/{diffusion_models,text_encoders,vae}/` 三个权重文件就位（软链或实体）
- [ ] 冒烟测试三项全过
- [ ] `~/datasets/` 目录就绪，validate_dataset.py 可用
- [ ] 交付一段"如何启动训练"的说明给用户：改 yaml 的 folder_path → `python run.py config/train_lora_qwen_image_21_spark.yaml`
- [ ] ComfyUI 原服务未受影响（训练前后各确认一次服务状态）

## 7. 故障排查

| 症状 | 原因/处理 |
|---|---|
| manager 装不上 | 走 §2 手动 venv 路径；`python3 -m manager doctor` |
| 首次运行卡在下载 | configs/processor 从 Qwen 官方 repo 拉；设 `HF_ENDPOINT=https://hf-mirror.com` |
| 报找不到权重 | MODELS_PATH/软链布局不对；对照 §3 的三个文件名逐个 `ls` |
| OOM | 不应发生（128GB 统一内存 + bf16 + batch 1）；若发生检查 yaml 是否被人改回量化/大分辨率 |
| GB10 算子报错 | torch 版本不对（需 cu130 构建）；`python3 -m manager doctor` |
| 采样图全黑/坏图 | 通常是权重文件不完整（软链指向被 ComfyUI 更新删除的旧文件）；重新对齐文件 |

## 8. 边界（不要做的事）

- 不动 ComfyUI 的任何配置和已有模型文件（只读引用）
- 不把 32GB 权重再下载一份（复用是本方案的核心价值）
- 不替用户做训练本身——环境就绪即停，训练由用户发起

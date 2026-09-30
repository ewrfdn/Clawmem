#!/usr/bin/env python3
"""数据集结构校验 — 在把数据扔给 ai-toolkit 之前跑一遍
用法: python3 validate_dataset.py /path/to/dataset [触发词]
规则与 ai-toolkit data_loader.py / dataloader_mixins.py 的实际行为对齐
"""
import os, sys

IMG_EXTS = {'.jpg', '.jpeg', '.png'}   # .webp 代码里能扫但 README 警告有问题，不建议

def main(root: str, trigger: str = None):
    if not os.path.isdir(root):
        print(f"[FATAL] 不是目录: {root}"); sys.exit(1)
    images, problems = [], []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith('.')]        # 隐藏目录跳过(与训练器一致)
        if os.path.basename(dirpath) == '_controls':                 # 控制图目录，训练器会排除
            continue
        for f in files:
            if f.startswith('.'): continue
            if os.path.splitext(f)[1].lower() in IMG_EXTS:
                images.append(os.path.join(dirpath, f))

    if not images:
        print("[FATAL] 没找到任何图片"); sys.exit(1)

    for img in images:
        base = os.path.splitext(img)[0]
        txt = base + '.txt'
        name = os.path.relpath(img, root)
        if not os.path.exists(txt):
            problems.append(f"{name}: 缺同名 .txt (将变成空caption)"); continue
        try:
            cap = open(txt, encoding='utf-8').read()
        except UnicodeDecodeError:
            problems.append(f"{name}: txt 不是 UTF-8 编码"); continue
        if not cap.strip():
            problems.append(f"{name}: caption 为空")
        if trigger and trigger not in cap:
            problems.append(f"{name}: caption 里没有触发词 {trigger}")

    # 孤儿 txt(有txt没图) — 不报错但浪费
    all_txt = {os.path.splitext(os.path.join(dp, f))[0]
               for dp, _, fs in os.walk(root) for f in fs if f.endswith('.txt') and not f.startswith('.')}
    orphans = [t for t in all_txt if not any(os.path.exists(t + e) for e in IMG_EXTS)]

    print(f"图片: {len(images)} 张")
    if trigger: print(f"触发词: {trigger}")
    if problems:
        print(f"\n问题 ({len(problems)}):")
        for p in problems: print(f"  ✗ {p}")
    if orphans:
        print(f"\n孤儿 caption ({len(orphans)} 个, 无对应图片):")
        for o in orphans[:10]: print(f"  - {os.path.relpath(o, root)}.txt")
    if not problems:
        print("\n✓ 全部通过，可以训练")
    else:
        sys.exit(1)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

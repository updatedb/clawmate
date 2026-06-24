#!/usr/bin/env python3
"""一次性迁移脚本：将旧的 {project}/.feedback.json 移动到 {project}/.clawmate/feedback.json。

遍历 config.json 中所有 root 下的所有 project 子目录，
移动旧的 .feedback.json 到 .clawmate/feedback.json。
如果 .clawmate/ 目录不存在则自动创建。
"""

import json
import os
import sys
from pathlib import Path

# 添加 dev 目录到 path，以便直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dev"))


def main():
    try:
        from config import load as load_config
    except ImportError as e:
        print(f"❌ 无法加载 config 模块: {e}")
        sys.exit(1)

    cfg = load_config()
    migrated = 0
    skipped = 0
    errors = 0

    for root in cfg.roots:
        root_dir = Path(root.dir).expanduser().resolve()
        if not root_dir.is_dir():
            print(f"⊘ root 目录不存在，跳过: {root_dir}")
            continue

        for entry in sorted(root_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith("."):
                continue

            old_path = entry / ".feedback.json"
            if not old_path.exists():
                continue

            new_dir = entry / ".clawmate"
            new_path = new_dir / "feedback.json"

            if new_path.exists():
                print(f"⊘ 已存在，跳过: {new_path}")
                skipped += 1
                continue

            try:
                new_dir.mkdir(parents=True, exist_ok=True)
                os.rename(old_path, new_path)
                print(f"✓ {old_path}  →  {new_path}")
                migrated += 1
            except Exception as e:
                print(f"✕ 迁移失败 {old_path}: {e}")
                errors += 1

    print(f"\n完成: {migrated} 个已迁移, {skipped} 个已跳过, {errors} 个失败")


if __name__ == "__main__":
    main()

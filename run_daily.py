#!/usr/bin/env python3
"""
一键执行流水线：抓取 → 归档 → 去噪 → 蒸馏 → 飞书推送
用法: python run_daily.py [--date YYYY-MM-DD] [--skip-grab] [--skip-feishu]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── 根目录定位 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
DOUYIN_PKG = SRC_DIR / "douyin_im_grabber"


def load_settings() -> dict:
    settings_path = ROOT / "config" / "settings.json"
    if settings_path.exists():
        with open(settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def step_header(title: str) -> None:
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print(f"{'=' * 50}")


def run_grabber(group_name: str, settings: dict) -> tuple[Path, Path]:
    """Step 1: 抓取群聊数据。返回 (json_path, md_path)。"""
    step_header("Step 1: 抓取群聊数据")

    grab_cfg = settings.get("grab", {})
    # net_grab.py 会在 GROUPS_DIR 下再建 <群名>/ 子目录
    # 所以 GROUPS_DIR 设为 output/.temp_grab 得到 output/.temp_grab/<群名>/
    temp_dir = ROOT / "output" / ".temp_grab"
    temp_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["GROUPS_DIR"] = str(temp_dir)
    env["PYTHONPATH"] = str(SRC_DIR)

    cmd = [
        sys.executable, "-m", "douyin_im_grabber.net_grab",
        "--group", group_name,
        "--max-rounds", str(grab_cfg.get("max_rounds", 160)),
        "--idle-rounds", str(grab_cfg.get("idle_rounds", 10)),
        "--quiet",
    ]

    print(f"  执行: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, cwd=str(ROOT), capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  错误: 抓取失败", file=sys.stderr)
        print(f"  stdout: {result.stdout}", file=sys.stderr)
        print(f"  stderr: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # 从 quiet 模式的 JSON 输出中解析路径
    try:
        info = json.loads(result.stdout.strip())
        json_path = Path(info["json_path"])
        md_path = Path(info.get("md_path") or "")
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  错误: 无法解析抓取结果 — {e}", file=sys.stderr)
        print(f"  stdout: {result.stdout[:500]}", file=sys.stderr)
        sys.exit(1)

    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    return json_path, md_path


def archive_files(json_path: Path, md_path: Path, target_date: str, group_name: str) -> Path:
    """Step 2: 归档文件。返回原始 MD 的最终路径。"""
    step_header("Step 2: 文件归档")

    # JSON → archive/
    archive_dir = ROOT / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    json_dest = archive_dir / json_path.name
    shutil.move(str(json_path), str(json_dest))
    print(f"  JSON 归档: {json_dest}")

    # 原始 MD → output/<群名>/原始文件/
    raw_dir = ROOT / "output" / group_name / "原始文件"
    raw_dir.mkdir(parents=True, exist_ok=True)
    # 用日期命名，便于追溯
    md_dest = raw_dir / f"{group_name}_{target_date}.md"
    if md_path.exists():
        shutil.move(str(md_path), str(md_dest))
        print(f"  原始 MD:   {md_dest}")

    # 清理临时目录
    temp_dir = ROOT / "output" / ".temp_grab"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)

    return md_dest


def run_script(module: str, args: list[str], description: str) -> Path:
    """运行 Python 脚本并返回输出文件路径。"""
    cmd = [sys.executable, str(SRC_DIR / f"{module}.py")] + args
    print(f"  执行: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)

    if result.stdout:
        print(result.stdout.strip())
    if result.stderr and result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)

    if result.returncode != 0:
        print(f"  错误: {description} 失败", file=sys.stderr)
        sys.exit(1)

    # 从输出中提取文件路径（最后一行 "输出: xxx"）
    for line in result.stdout.strip().split("\n"):
        if line.startswith("输出:") or line.startswith("  输出:"):
            return Path(line.split(":", 1)[1].strip())
    # 回退：无法解析路径
    return Path(".")


def main():
    settings = load_settings()
    group_name = settings.get("group_name", "财富自由团")

    parser = argparse.ArgumentParser(description="财富自由团日报 · 一键执行流水线")
    parser.add_argument("--date", help="统计日期 YYYY-MM-DD（默认昨天）")
    parser.add_argument("--skip-grab", action="store_true", help="跳过抓取，使用已有 JSON")
    parser.add_argument("--skip-feishu", action="store_true", help="跳过飞书推送")
    parser.add_argument("--json", help="指定已有 JSON 文件路径（配合 --skip-grab）")
    args = parser.parse_args()

    # 日期处理
    if args.date:
        target_date = args.date
    else:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"\n{'█' * 50}")
    print(f"  财富自由团日报 · 全自动流水线")
    print(f"  目标日期: {target_date}")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'█' * 50}")

    started_at = time.time()

    # ── Step 1: 抓取 ──
    if args.skip_grab:
        if not args.json:
            print("错误: --skip-grab 需要 --json 指定已有 JSON 路径", file=sys.stderr)
            sys.exit(1)
        json_path = Path(args.json)
        md_path = Path("")  # 不需要
        step_header("Step 1: 跳过抓取（使用已有数据）")
        print(f"  JSON: {json_path}")
    else:
        json_path, md_path = run_grabber(group_name, settings)

    # ── Step 2: 归档 ──
    if not args.skip_grab:
        raw_md_path = archive_files(json_path, md_path, target_date, group_name)
    else:
        raw_md_path = md_path if md_path.exists() else None
        step_header("Step 2: 跳过归档（--skip-grab 模式）")

    # ── Step 3: 去噪预处理 ──
    # JSON 已移到 archive，需要从 archive 读取
    archive_json = ROOT / "archive" / json_path.name
    if not archive_json.exists():
        archive_json = json_path  # 回退到原路径

    cleaned_path = run_script(
        "preprocess",
        [str(archive_json), "--date", target_date],
        "预处理/去噪"
    )

    # ── Step 4: 蒸馏 ──
    report_path = run_script(
        "distill",
        [str(cleaned_path), "--date", target_date],
        "蒸馏/日报生成"
    )

    # ── Step 5: 飞书推送 ──
    if args.skip_feishu:
        step_header("Step 5: 跳过飞书推送")
    else:
        step_header("Step 5: 飞书推送")
        feishu_ok = subprocess.run(
            [sys.executable, str(SRC_DIR / "feishu_push.py"),
             str(report_path), "--date", target_date, "--group", group_name],
            cwd=str(ROOT),
        ).returncode == 0
        if feishu_ok:
            print("  ✅ 飞书推送完成")
        else:
            print("  ⚠️ 飞书推送失败（日报已生成，可稍后手动推送）")

    # ── 完成 ──
    elapsed = time.time() - started_at
    print(f"\n{'█' * 50}")
    print(f"  ✅ 全流程完成！")
    print(f"  目标日期: {target_date}")
    print(f"  总耗时: {elapsed:.0f} 秒")
    print(f"  日报: {report_path}")
    print(f"{'█' * 50}\n")


if __name__ == "__main__":
    main()

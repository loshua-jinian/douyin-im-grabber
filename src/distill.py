#!/usr/bin/env python3
"""
Claude 蒸馏调度器：读取清洗后的群聊数据，调用 Claude CLI 按蒸馏规则生成日报。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

# Windows 终端 UTF-8 兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 根目录定位 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent


def load_file(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load_settings() -> dict:
    settings_path = ROOT / "config" / "settings.json"
    if settings_path.exists():
        with open(settings_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_prompt(
    rules: str,
    chat_data: str,
    target_date: str,
    group_name: str,
) -> str:
    """构造发给 Claude 的完整 prompt。"""
    return f"""# 任务：生成群聊情报日报

## 你的角色与规则

{rules}

---

## 待处理的群聊数据

以下为 {group_name} 群 {target_date} 的清洗后聊天记录：

{chat_data}

---

请严格按照上述规则和输出格式，为 {target_date} 生成当天的群聊情报日报。
直接输出日报 Markdown 正文，不要输出任何前言、后记或解释。"""
    return prompt


def call_claude(
    prompt: str,
    model: str = "sonnet",
    max_budget_usd: float = 0.5,
    effort: str = "high",
) -> str:
    """
    通过 Claude CLI 非交互模式调用 Claude。
    使用 subprocess + stdin 管道，避免 shell 转义问题和命令行长度限制。
    """
    # 优先用完整路径（Windows 子进程 PATH 可能不含 npm 全局目录）
    import shutil
    claude_bin = shutil.which("claude") or shutil.which("claude.cmd")
    if not claude_bin:
        # 常见安装路径回退
        for candidate in [
            r"C:\Users\86150\AppData\Roaming\npm\claude.cmd",
            r"C:\Users\86150\AppData\Roaming\npm\claude",
        ]:
            if Path(candidate).exists():
                claude_bin = candidate
                break
    if not claude_bin:
        print("  错误: 找不到 claude 命令，请确认 Claude Code 已安装", file=sys.stderr)
        sys.exit(1)

    cmd = [
        claude_bin,
        "--print",
        "--output-format", "text",
        "--permission-mode", "bypassPermissions",
        "--no-session-persistence",
        "--tools", "",
        "--model", model,
        "--max-budget-usd", str(max_budget_usd),
        "--effort", effort,
        "--add-dir", str(ROOT),
    ]

    print(f"  调用 Claude CLI (model={model}, budget=${max_budget_usd})...")
    print(f"  prompt 大小: {len(prompt)} 字符 (~{len(prompt)//4} tokens)")

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(ROOT),
        )
        stdout, stderr = proc.communicate(input=prompt.encode("utf-8"), timeout=600)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("  错误: Claude CLI 超时 (10min)", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("  错误: 找不到 claude 命令，请确认 Claude Code 已安装", file=sys.stderr)
        sys.exit(1)

    stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
    stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

    if proc.returncode != 0:
        print(f"  错误: Claude CLI 返回码 {proc.returncode}", file=sys.stderr)
        if stderr_text:
            print(f"  stderr: {stderr_text[:500]}", file=sys.stderr)
        if not stdout_text:
            sys.exit(1)

    return stdout_text


def extract_report(raw_output: str) -> str:
    """
    从 Claude 输出中提取纯日报内容。
    去除可能的前言/后记，保留 Markdown 报告。
    """
    lines = raw_output.split("\n")
    start_idx = None
    end_idx = None

    for i, line in enumerate(lines):
        if line.strip().startswith("## ") and start_idx is None:
            start_idx = i
        if start_idx is not None and line.strip().startswith("---") and i > start_idx + 5:
            # 可能是报告结束分隔线
            pass

    if start_idx is None:
        # 没找到 "## " 开头，返回原始输出
        return raw_output.strip()

    # 查找报告结尾：连续两个空行后的非报告内容，或无更多内容
    # 简单策略：取从 start_idx 到末尾
    report = "\n".join(lines[start_idx:]).strip()
    return report


def distill(
    cleaned_path: Path,
    target_date: str,
    output_dir: Optional[Path] = None,
) -> Path:
    """
    主入口：读取清洗数据 + 蒸馏规则 → 调用 Claude → 保存日报。
    返回日报文件路径。
    """
    settings = load_settings()
    group_name = settings.get("group_name", "财富自由团")
    rules_file = settings.get("distill", {}).get("rules_file", "templates/蒸馏规则")
    model = settings.get("distill", {}).get("model", "sonnet")
    max_budget = settings.get("distill", {}).get("max_budget_usd", 0.5)
    effort = settings.get("distill", {}).get("effort", "high")

    # 读取蒸馏规则
    rules_path = ROOT / rules_file
    if not rules_path.exists():
        print(f"  错误: 蒸馏规则文件不存在 — {rules_path}", file=sys.stderr)
        sys.exit(1)
    rules = load_file(rules_path)
    print(f"  蒸馏规则: {rules_path} ({len(rules)} 字符)")

    # 读取清洗数据
    chat_data = load_file(cleaned_path)
    print(f"  清洗数据: {cleaned_path} ({len(chat_data)} 字符)")

    # 构建 prompt
    prompt = build_prompt(rules, chat_data, target_date, group_name)

    # 调用 Claude
    raw_output = call_claude(prompt, model=model, max_budget_usd=max_budget, effort=effort)
    print(f"  Claude 输出: {len(raw_output)} 字符")

    # 提取日报正文
    report = extract_report(raw_output)

    # 输出目录
    if output_dir is None:
        output_dir = ROOT / "output" / group_name / "日报"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{group_name}日报-{target_date}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"  输出: {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Claude 蒸馏调度：清洗数据 → 日报")
    parser.add_argument("cleaned_path", help="清洗后的数据文件路径 (*_去噪_*.md)")
    parser.add_argument("--date", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--output-dir", help="输出目录（默认 output/<群名>/日报/）")
    parser.add_argument("--model", help="Claude 模型（覆盖 settings.json）")
    parser.add_argument("--budget", type=float, help="最大预算 USD（覆盖 settings.json）")
    args = parser.parse_args()

    cleaned_path = Path(args.cleaned_path)
    if not cleaned_path.exists():
        print(f"错误: 文件不存在 — {cleaned_path}", file=sys.stderr)
        sys.exit(1)

    distill(
        cleaned_path=cleaned_path,
        target_date=args.date,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )


if __name__ == "__main__":
    main()

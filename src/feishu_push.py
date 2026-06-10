#!/usr/bin/env python3
"""
飞书推送：将日报 Markdown 创建为飞书云文档，并通过 Webhook 发送文档链接到群聊。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ── lark-cli 路径 ──────────────────────────────────────────────
LARK_CLI = shutil.which("lark-cli") or ""
if not LARK_CLI and sys.platform == "win32":
    # 常见的 npm 全局安装路径
    for candidate in [
        Path.home() / "AppData" / "Roaming" / "npm" / "lark-cli.cmd",
    ]:
        if candidate.exists():
            LARK_CLI = str(candidate)
            break

# Windows 终端 UTF-8 兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

# ── 根目录定位 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent


def load_webhook_url() -> Optional[str]:
    """从配置文件读取飞书 Webhook URL。优先级：feishu_webhook.json > settings.json"""
    wh_path = ROOT / "config" / "feishu_webhook.json"
    if wh_path.exists():
        with open(wh_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        url = cfg.get("webhook_url", "").strip()
        if url:
            return url

    settings_path = ROOT / "config" / "settings.json"
    if settings_path.exists():
        with open(settings_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        feishu = cfg.get("feishu", {})
        url = feishu.get("webhook_url", "").strip()
        if url:
            return url

    return None


def load_file(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def create_cloud_doc(title: str, markdown_content: str) -> Optional[str]:
    """
    通过 lark-cli 创建飞书云文档。
    使用 --content - 从 stdin 管道传入内容，彻底避开 Windows 命令行 8191 字符长度限制。
    返回文档 URL，失败返回 None。
    """
    if not LARK_CLI:
        print("  错误: 找不到 lark-cli，请确保已安装", file=sys.stderr)
        return None

    try:
        # --content - 从 stdin 读取内容，完全绕过命令行长度限制
        result = subprocess.run(
            [
                LARK_CLI, "docs", "+create",
                "--api-version", "v2",
                "--doc-format", "markdown",
                "--content", "-",
            ],
            input=markdown_content,
            capture_output=True, text=True, encoding="utf-8",
            timeout=60, cwd=str(ROOT),
        )

        if result.returncode != 0:
            print(f"  lark-cli 错误 (exit={result.returncode}):", file=sys.stderr)
            print(f"  stderr: {result.stderr.strip()[:500]}", file=sys.stderr)
            return None

        data = json.loads(result.stdout)
        if not data.get("ok"):
            print(f"  创建文档失败: {data}", file=sys.stderr)
            return None

        doc_url = data["data"]["document"]["url"]
        return doc_url

    except subprocess.TimeoutExpired:
        print("  创建文档超时", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"  解析 lark-cli 输出失败: {e}", file=sys.stderr)
        return None


def notify_webhook(webhook_url: str, doc_url: str, title: str) -> bool:
    """通过 Webhook 发送简短通知，告知群成员文档已就绪。"""
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "📊 日报已生成"},
                "template": "green",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**{title}** 已同步至飞书云文档，点击下方链接查看：\n\n👉 [{title}]({doc_url})",
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "📄 打开日报"},
                            "url": doc_url,
                            "type": "default",
                        }
                    ],
                },
            ],
        },
    }

    try:
        resp = requests.post(webhook_url, json=card, timeout=15)
        body = resp.json()
        if resp.status_code == 200 and body.get("code") == 0:
            return True
        print(f"  飞书返回错误: {body}", file=sys.stderr)
        return False
    except requests.RequestException as e:
        print(f"  飞书请求失败: {e}", file=sys.stderr)
        return False


def push_report(report_path: Path, group_name: str, target_date: str) -> bool:
    """
    主入口：读取日报 → 创建飞书云文档 → 发送链接到群聊。
    """
    # 1. 读取日报
    content = load_file(report_path)
    if not content.strip():
        print("  错误: 日报内容为空", file=sys.stderr)
        return False

    title = f"{group_name}日报 · {target_date}"

    # 2. 创建飞书云文档
    print(f"  创建飞书云文档...")
    doc_url = create_cloud_doc(title, content)
    if not doc_url:
        print("  ❌ 云文档创建失败", file=sys.stderr)
        return False
    print(f"  ✅ 云文档已创建: {doc_url}")

    # 3. 通过 Webhook 发送文档链接通知
    webhook_url = load_webhook_url()
    if not webhook_url:
        print("  ⚠️ 未配置飞书 Webhook URL，跳过群聊通知", file=sys.stderr)
        print(f"  文档链接: {doc_url}")
        return True  # 文档已创建，不算失败

    if notify_webhook(webhook_url, doc_url, title):
        print(f"  ✅ 已发送群聊通知")
    else:
        print(f"  ❌ 群聊通知发送失败（文档已创建: {doc_url}）")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="飞书推送：创建云文档并发送链接到群聊")
    parser.add_argument("report_path", help="日报 Markdown 文件路径")
    parser.add_argument("--date", required=True, help="日报日期 YYYY-MM-DD")
    parser.add_argument("--group", default="财富自由团", help="群名")
    args = parser.parse_args()

    report_path = Path(args.report_path)
    if not report_path.exists():
        print(f"错误: 文件不存在 — {report_path}", file=sys.stderr)
        sys.exit(1)

    success = push_report(report_path, args.group, args.date)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

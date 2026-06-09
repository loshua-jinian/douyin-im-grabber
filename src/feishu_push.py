#!/usr/bin/env python3
"""
飞书推送：将日报 Markdown 转为飞书卡片消息，通过 Webhook 发送到群聊。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

# Windows 终端 UTF-8 兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

# ── 根目录定位 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent

# 飞书消息体最大长度（字节），留有安全边距
MAX_MSG_BYTES = 28_000


def load_webhook_url() -> Optional[str]:
    """从配置文件读取飞书 Webhook URL。优先级：feishu_webhook.json > settings.json"""
    # 先尝试专用配置文件
    wh_path = ROOT / "config" / "feishu_webhook.json"
    if wh_path.exists():
        with open(wh_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        url = cfg.get("webhook_url", "").strip()
        if url:
            return url

    # 再尝试 settings.json
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


def split_content(content: str, max_bytes: int = MAX_MSG_BYTES) -> list[str]:
    """将超长内容按段落边界分割。"""
    if len(content.encode("utf-8")) <= max_bytes:
        return [content]

    chunks = []
    paragraphs = content.split("\n\n")
    current = ""

    for para in paragraphs:
        candidate = current + ("\n\n" if current else "") + para
        if len(candidate.encode("utf-8")) > max_bytes:
            if current:
                chunks.append(current)
                current = para
            else:
                # 单个段落就超长，强制按字符截断
                chunks.append(para[:max_bytes // 3])
                current = ""
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks


def build_card(title: str, markdown_content: str, part: int = 0, total: int = 1) -> dict:
    """构造飞书 interactive 卡片消息。"""
    header_title = title if total == 1 else f"{title} ({part + 1}/{total})"

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": header_title},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": markdown_content,
                }
            ],
        },
    }


def send_to_feishu(webhook_url: str, payload: dict) -> bool:
    """发送消息到飞书 Webhook。"""
    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
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
    主入口：读取日报 → 构造飞书卡片 → 发送。
    返回是否全部发送成功。
    """
    webhook_url = load_webhook_url()
    if not webhook_url:
        print("  错误: 未配置飞书 Webhook URL", file=sys.stderr)
        print("  请在 config/feishu_webhook.json 中填入 webhook_url", file=sys.stderr)
        return False

    content = load_file(report_path)
    if not content.strip():
        print("  错误: 日报内容为空", file=sys.stderr)
        return False

    title = f"📊 {group_name}日报 · {target_date}"
    chunks = split_content(content)

    if len(chunks) == 1:
        print(f"  发送 1 条消息...")
    else:
        print(f"  内容较长，分 {len(chunks)} 条发送...")

    success = True
    for i, chunk in enumerate(chunks):
        card = build_card(title, chunk, part=i, total=len(chunks))
        if send_to_feishu(webhook_url, card):
            print(f"  ✅ 第 {i + 1}/{len(chunks)} 条发送成功")
        else:
            print(f"  ❌ 第 {i + 1}/{len(chunks)} 条发送失败")
            success = False

        # 多条消息间短暂间隔，避免触发飞书限速
        if i < len(chunks) - 1:
            time.sleep(1)

    return success


def main():
    parser = argparse.ArgumentParser(description="飞书推送：发送群聊日报到飞书群")
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

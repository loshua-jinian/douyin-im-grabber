#!/usr/bin/env python3
"""
机械化预处理：按自然日过滤、去噪、合并同发言人 60s 内连续消息。
纯 Python 规则引擎，不依赖 AI，减少后续 Claude 调用的 token 消耗。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Windows 终端 UTF-8 兼容
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── 根目录定位 ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent


# ── 文本提取 ─────────────────────────────────────────────────
def parse_text_payload(msg: dict[str, Any]) -> dict[str, Any] | None:
    """从消息的 text 字段尝试解析 JSON payload（与 net_grab.py 逻辑一致）。"""
    text = str(msg.get("text") or "").strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def display_text(msg: dict[str, Any]) -> str:
    """从消息中提取可读文本（与 net_grab.py 逻辑一致）。"""
    text = str(msg.get("text") or "").strip()
    if not text:
        return ""

    payload = parse_text_payload(msg)
    if msg.get("type_code") == 7:
        if not payload:
            return text
        # JSON payload 里的真正文本
        value = payload.get("text") or payload.get("msgHint") or payload.get("content_name")
        return str(value).strip() if value else text

    # 非文本消息，返回摘要标签
    if not payload:
        return f"[非文本 type={msg.get('type_code', '?')}] {text[:120]}"
    if payload.get("display_name"):
        return f"[表情] {payload['display_name']}"
    if payload.get("resource_url") or payload.get("aweType") == 2702:
        return "[图片]"
    if payload.get("content_name"):
        return f"[卡片] {payload['content_name']}"
    if payload.get("text"):
        return f"[非文本] {payload['text']}"
    return f"[非文本 type={msg.get('type_code', '?')}]"


def is_text_message(msg: dict[str, Any]) -> bool:
    """是否为有效文本消息。"""
    if msg.get("type_code") != 7:
        return False
    return bool(display_text(msg))


# ── 噪声模式 ─────────────────────────────────────────────────
# 非文本消息标签
NON_TEXT_PATTERNS = re.compile(
    r"^\[(?:图片|表情|视频|语音|卡片|撤回|非文本)[^\]]*\]"
)

# 纯短噪声：< 5 个有效字，且匹配以下模式之一
NOISE_PATTERNS = [
    re.compile(p) for p in [
        r"^[0-9\s\.\,，。！？\!\?、\s]+$",        # 纯数字/标点
        r"^[哈哈]{2,}$",                           # "哈哈"
        r"^6+$",                                   # 666
        r"^[\.\。\…\.]{2,}$",                      # 纯省略号
        r"^[@＠]\S+$",                             # 纯 @某人
        r"^[+＋1一]+\s*$",                         # +1
        r"^[👍👏🙏💪🤝🎉🔥💯❤️🙈🤣😅]{1,5}$",      # 纯表情符号
        r"^顶+$", r"^蹲+$", r"^收到$", r"^好的$", r"^嗯+$",
        r"^可以可以$", r"^不错不错$", r"^厉害了$",
        r"^我也是$", r"^一样$", r"^同问$", r"^同求$", r"^学习了$",
        r"^👍$", r"^❌$", r"^✅$",
    ]
]

# 额外关键词过滤（包含以下关键词的 < 8 字短消息丢弃）
NOISE_KEYWORDS = [
    "Recall Content Hided",  # 撤回消息
    "对方已撤回",             # 撤回提示
]

# 方括号表情/标签（如 [泪奔]、[赞]、[捂脸]）
BRACKET_EMOJI = re.compile(r"^\[[一-鿿؀-ۿ\w]{1,8}\]$")


def is_noise(text: str) -> bool:
    """判断一条消息是否为可丢弃的噪声。"""
    t = text.strip()
    if not t:
        return True
    if NON_TEXT_PATTERNS.match(t):
        return True
    # 方括号表情标签
    if BRACKET_EMOJI.match(t):
        return True
    # 撤回消息关键词
    for kw in NOISE_KEYWORDS:
        if kw in t:
            return True
    # < 5 个字且匹配噪声模式
    if len(t) < 5:
        for pat in NOISE_PATTERNS:
            if pat.match(t):
                return True
    return False


def load_json(json_path: Path) -> dict[str, Any]:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_timestamp_ms(ms: int) -> datetime:
    """毫秒时间戳 → datetime（本地时间）。"""
    return datetime.fromtimestamp(ms / 1000)


def filter_messages_by_date(
    messages: list[dict[str, Any]],
    user_map: dict[str, str],
    target_date: str,
) -> list[dict[str, Any]]:
    """
    过滤出目标日期的文本消息，解析并标注发送人昵称。
    日报时间窗口：当天 04:00:00 ~ 次日 03:59:59
    返回格式：[{time, sender, text, uid}, ...]
    """
    day_start = datetime.strptime(target_date, "%Y-%m-%d") + timedelta(hours=4)
    day_end = day_start + timedelta(days=1)

    result = []
    for msg in messages:
        # 只处理文本消息
        if not is_text_message(msg):
            continue

        ms = msg.get("created_at_ms")
        if not ms:
            continue
        try:
            dt = parse_timestamp_ms(int(ms))
        except (ValueError, TypeError, OSError):
            continue

        # 日期过滤
        if dt < day_start or dt >= day_end:
            continue

        # 提取真实文本
        text = display_text(msg)
        if not text or is_noise(text):
            continue

        uid = str(msg.get("sender_uid") or "?")
        sender = user_map.get(uid, uid)
        result.append({
            "time": dt,
            "sender": sender,
            "text": text,
            "uid": uid,
        })

    # 按时间排序
    result.sort(key=lambda m: m["time"])
    return result


def merge_consecutive(
    messages: list[dict[str, Any]],
    max_gap_seconds: int = 60,
) -> list[dict[str, Any]]:
    """
    合并同一发送人在 max_gap_seconds 秒内的连续消息。
    保留第一条的时间戳，文本用换行连接。
    """
    if not messages:
        return []

    merged = []
    current = None

    for msg in messages:
        if current is None:
            current = dict(msg)
            current["merge_count"] = 1
            continue

        same_sender = msg["sender"] == current["sender"]
        time_gap = (msg["time"] - current["time"]).total_seconds()
        within_window = 0 <= time_gap <= max_gap_seconds

        if same_sender and within_window:
            current["text"] += "\n" + msg["text"]
            current["merge_count"] += 1
            # keep first timestamp
        else:
            merged.append(current)
            current = dict(msg)
            current["merge_count"] = 1

    if current is not None:
        merged.append(current)

    return merged


def build_clean_output(
    messages: list[dict[str, Any]],
    target_date: str,
    group_name: str,
    raw_count: int = 0,
    text_count: int = 0,
) -> str:
    """生成清洗后的文本输出，供 Claude 蒸馏使用。"""
    lines = [
        f"# 群聊清洗数据 · {group_name} · {target_date}",
        f"# 原始消息总数: {raw_count}",
        f"# 纯文本消息数: {text_count}",
        f"# 去噪合并后消息数: {len(messages)}",
        f"# 活跃发言人: {len(set(m['sender'] for m in messages))}",
        "",
    ]

    # 发言人 Top 20
    senders = Counter(m["sender"] for m in messages)
    lines.append("## 发言 Top 20")
    lines.append("| 排名 | 消息数 | 发送人 |")
    lines.append("|---|---:|:---|")
    for idx, (sender, count) in enumerate(senders.most_common(20), 1):
        lines.append(f"| {idx} | {count} | {sender} |")
    lines.append("")

    # 消息正文
    lines.append("## 消息记录（已合并 60s 内同一发言人连续消息）")
    lines.append("")
    for msg in messages:
        time_str = msg["time"].strftime("%H:%M:%S")
        merge_info = f" [合并{msg['merge_count']}条]" if msg["merge_count"] > 1 else ""
        lines.append(f"- **{time_str}** `{msg['sender']}`{merge_info}: {msg['text']}")
        lines.append("")

    return "\n".join(lines)


def preprocess(
    json_path: Path,
    target_date: str,
    output_dir: Path | None = None,
) -> Path:
    """
    主入口：读取 JSON → 过滤/清洗/合并 → 输出去噪文件。
    返回输出文件路径。
    """
    data = load_json(json_path)
    group_name = data.get("group_name", "未知群")
    user_map = data.get("user_map", {})
    messages = data.get("messages", [])

    print(f"  原始消息总数: {len(messages)}")
    print(f"  群成员数: {len(user_map)}")

    # Step 1: 过滤目标日期 & 去噪
    filtered = filter_messages_by_date(messages, user_map, target_date)
    print(f"  过滤后消息数 (仅文本/目标日期/去噪): {len(filtered)}")

    # Step 2: 合并 60s 内同一发言人
    merged = merge_consecutive(filtered, max_gap_seconds=60)
    print(f"  合并后消息数: {len(merged)}")

    # Step 3: 生成输出
    output = build_clean_output(
        merged, target_date, group_name,
        raw_count=len(messages),
        text_count=sum(1 for m in messages if m.get("type_code") == 7),
    )

    # 输出目录
    if output_dir is None:
        output_dir = ROOT / "output" / group_name / "去噪文件"
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{group_name}_去噪_{target_date}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"  输出: {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="群聊数据机械化清洗/去噪")
    parser.add_argument("json_path", help="原始 JSON 文件路径")
    parser.add_argument("--date", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--output-dir", help="输出目录（默认 output/<群名>/去噪文件/）")
    args = parser.parse_args()

    json_path = Path(args.json_path)
    if not json_path.exists():
        print(f"错误: 文件不存在 — {json_path}", file=sys.stderr)
        sys.exit(1)

    preprocess(
        json_path=json_path,
        target_date=args.date,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )


if __name__ == "__main__":
    main()

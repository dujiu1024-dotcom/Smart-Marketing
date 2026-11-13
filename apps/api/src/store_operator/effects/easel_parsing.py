"""Easel 解析层移植（Apache-2.0）。

来源：Easel 仓库 `skills/shared/scripts/account_stats.py` 与
`skills/shared/scripts/platform_readback.py`。仅移植与登录态、浏览器无关的
纯函数与结果语义；真实抓取由商家授权采集器承担，不在本模块内启动浏览器。

本模块不读写任何文件，不依赖平台登录态，可离线测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# --------------------------------------------------------------------------- #
# 平台字段口径（Easel PLATFORMS 的解析相关子集）
# --------------------------------------------------------------------------- #

PLATFORM_PROFILES: dict[str, dict[str, Any]] = {
    "douyin": {
        "name": "抖音",
        "overview_dir": "after",
        "overview": {
            "followers": ["粉丝", "粉丝数"],
            "likes": ["获赞", "点赞"],
            "following": ["关注"],
        },
        "metrics": ["播放量", "主页访问量", "作品分享", "作品评论"],
        "metrics_anchor": "近7日",
    },
    "xiaohongshu": {
        "name": "小红书",
        "overview_dir": "before",
        "overview": {
            "followers": ["粉丝数"],
            "likes": ["获赞与收藏"],
            "following": ["关注数"],
        },
        "metrics": ["曝光数", "观看数", "点赞数", "评论数", "收藏数", "分享数", "主页访客"],
    },
    "kuaishou": {
        "name": "快手",
        "overview_dir": "after",
        "overview": {
            "followers": ["粉丝", "粉丝数"],
            "likes": ["获赞", "点赞"],
            "following": ["关注"],
        },
        "metrics": ["播放量", "点赞量", "评论量", "分享量"],
    },
    "zhihu": {
        "name": "知乎",
        "overview_dir": "after",
        "overview": {
            "followers": ["关注者", "粉丝"],
            "likes": ["赞同总量", "赞同"],
            "following": [],
        },
        "metrics": ["阅读总量", "播放总量", "收藏总量", "评论总量", "分享总量"],
    },
    "weixin_channels": {
        "name": "视频号",
        "overview_dir": "after",
        "overview": {"followers": ["关注者", "粉丝"], "likes": [], "following": []},
        "metrics": ["新增播放", "新增评论"],
    },
}

# 平台展示标签 → 统一 metric_key。中文标签在不同平台含义一致才合并。
LABEL_TO_METRIC_KEY: dict[str, str] = {
    "粉丝": "followers",
    "粉丝数": "followers",
    "关注者": "followers",
    "关注者总数": "followers",
    "获赞": "likes",
    "获赞与收藏": "likes",
    "点赞": "likes",
    "赞同": "likes",
    "赞同总量": "likes",
    "点赞数": "likes",
    "点赞量": "likes",
    "关注": "following",
    "关注数": "following",
    "作品数": "posts",
    "笔记数": "posts",
    "内容数": "posts",
    "视频数": "posts",
    "视频": "posts",
    "曝光数": "impressions",
    "推荐量": "impressions",
    "观看数": "views",
    "播放量": "views",
    "播放总量": "views",
    "新增播放": "views",
    "阅读量": "reads",
    "阅读总量": "reads",
    "评论数": "comments",
    "评论量": "comments",
    "评论总量": "comments",
    "新增评论": "comments",
    "收藏数": "favorites",
    "收藏量": "favorites",
    "收藏总量": "favorites",
    "分享数": "shares",
    "分享量": "shares",
    "分享总量": "shares",
    "转发量": "shares",
    "作品分享": "shares",
    "作品评论": "comments",
    "主页访客": "home_visits",
    "主页访问量": "home_visits",
    "净涨粉": "net_follower_gain",
    "涨粉数": "net_follower_gain",
}

# 账号概览指标在 MetricDefinition 中登记的键。
ACCOUNT_OVERVIEW_KEYS = ("followers", "likes", "following", "posts")

# 作品统计字段 → metric_key（对应 platform_readback WorkItem.stats）。
WORK_STAT_KEYS: dict[str, str] = {
    "play_count": "views",
    "digg_count": "likes",
    "like_count": "likes",
    "comment_count": "comments",
}

# platform_readback 四档结果语义。
READBACK_VERIFIED = "verified"
READBACK_UNVERIFIED = "unverified"
READBACK_LOGIN_REQUIRED = "login_required"
READBACK_ERROR = "readback_error"
READBACK_OUTCOMES = (
    READBACK_VERIFIED,
    READBACK_UNVERIFIED,
    READBACK_LOGIN_REQUIRED,
    READBACK_ERROR,
)

TITLE_KEY_LEN = 12
SINCE_TOLERANCE_MS = 10 * 60 * 1000


# --------------------------------------------------------------------------- #
# 数值与文本解析（account_stats.py 纯函数）
# --------------------------------------------------------------------------- #
def parse_num(value: Any) -> int | None:
    """展示数字串 → 整数：'1,234'→1234、'1.2万'→12000、'3.4亿'→340000000。"""
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    import re

    match = re.match(r"^([\d.]+)\s*([万亿wWkK千]?)$", text)
    if not match:
        fallback = re.match(r"^([\d.]+)", text)
        if not fallback:
            return None
        try:
            return int(float(fallback.group(1)))
        except ValueError:
            return None
    number, unit = match.group(1), match.group(2)
    try:
        numeric = float(number)
    except ValueError:
        return None
    multiplier = {
        "": 1,
        "万": 1e4,
        "亿": 1e8,
        "w": 1e4,
        "W": 1e4,
        "k": 1e3,
        "K": 1e3,
        "千": 1e3,
    }[unit]
    return int(round(numeric * multiplier))


def lines_of(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def num_by_label(lines: list[str], labels: list[str], direction: str) -> int | None:
    """按行精确匹配标签取相邻数字。before=标签上一行，after=标签后两行内。"""
    for index, line in enumerate(lines):
        clean = line.rstrip("：:")
        for label in labels:
            if clean.startswith(label) and len(clean) > len(label):
                inline = parse_num(clean[len(label):])
                if inline is not None:
                    return inline
        if clean not in labels:
            continue
        if direction == "before":
            if index - 1 >= 0:
                value = parse_num(lines[index - 1])
                if value is not None:
                    return value
        else:
            for cursor in range(index + 1, min(index + 3, len(lines))):
                value = parse_num(lines[cursor])
                if value is not None:
                    return value
    return None


def metrics_with_vs(
    lines: list[str], labels: list[str], anchor: str | None = None
) -> list[dict[str, str]]:
    """近 N 日指标：标签后就近取「纯数字值」与「±环比」。anchor 限定解析起点。"""
    import re

    if anchor:
        anchor_index = next((i for i, line in enumerate(lines) if anchor in line), None)
        if anchor_index is None:
            return []
        lines = lines[anchor_index + 1:]
    created: list[dict[str, str]] = []
    seen: set[str] = set()
    number_re = re.compile(r"^[\d][\d.,]*\s*[万亿wWkK千]?%?$")
    sign_re = re.compile(r"^[+\-]\d")
    vs_re = re.compile(r"[+\-]\d[\d.,]*\s*[万亿wWkK千]?%?")
    for index, line in enumerate(lines):
        clean = line.rstrip("：:")
        if clean not in labels or clean in seen:
            continue
        value = None
        vs = ""
        for cursor in range(index + 1, min(index + 5, len(lines))):
            candidate = lines[cursor]
            if candidate.rstrip("：:") in labels:
                break
            if value is None and number_re.match(candidate):
                value = candidate
            if not vs:
                if sign_re.match(candidate):
                    vs = candidate
                elif candidate.startswith("环比"):
                    vs = candidate[2:].strip()
                elif candidate.startswith("较前") or candidate.startswith("较上"):
                    match = vs_re.search(candidate)
                    if match:
                        vs = match.group(0)
        if value is not None:
            created.append({"label": clean, "value": value, "vs": vs})
            seen.add(clean)
    return created


def growth_windows(history: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
    """多窗口增长：last/day/week/month/year 对比历史快照；无基线返回 None。"""
    now = current["ts"]
    ordered = sorted(history, key=lambda item: item.get("ts", 0))
    specs: dict[str, int | None] = {
        "last": None,
        "day": 86400,
        "week": 7 * 86400,
        "month": 30 * 86400,
        "year": 365 * 86400,
    }
    output: dict[str, Any] = {}
    for name, seconds in specs.items():
        if name == "last":
            base = ordered[-1] if ordered else None
        else:
            older = [item for item in ordered if item.get("ts", 0) <= now - seconds]
            base = older[-1] if older else None
        if base:
            output[name] = {
                "followers": _delta(current.get("followers"), base.get("followers")),
                "likes": _delta(current.get("likes"), base.get("likes")),
                "posts": _delta(current.get("posts"), base.get("posts")),
                "since_days": round((now - base["ts"]) / 86400, 1),
            }
        else:
            output[name] = None
    return output


def _delta(current: Any, base: Any) -> int | None:
    return (current - base) if isinstance(current, int) and isinstance(base, int) else None


# --------------------------------------------------------------------------- #
# 作品匹配与读回结果（platform_readback.py）
# --------------------------------------------------------------------------- #
@dataclass
class WorkItem:
    platform_content_id: str
    title: str
    status: str
    published_at_ms: int | None = None
    stats: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform_content_id": self.platform_content_id,
            "title": self.title,
            "status": self.status,
            "published_at_ms": self.published_at_ms,
            "stats": self.stats,
        }


@dataclass
class ReadbackResult:
    outcome: str
    matched: WorkItem | None = None
    candidates: list[WorkItem] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def epoch_ms(value: Any) -> int | None:
    """秒/毫秒 epoch 归一化为毫秒。"""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(number * 1000) if number < 10_000_000_000 else int(number)


def find_published_work(
    works: list[WorkItem],
    title: str,
    *,
    since_ms: int | None = None,
    key_len: int = TITLE_KEY_LEN,
    exclude_ids: set[str] | None = None,
) -> WorkItem | None:
    """对账：标题前缀命中 + 不早于 since 时间窗；exclude_ids 视为旧作品。"""
    key = (title or "").strip().replace("\n", " ")[:key_len]
    if not key:
        return None
    for work in works:
        if key not in (work.title or ""):
            continue
        if exclude_ids and work.platform_content_id in exclude_ids:
            continue
        if (
            since_ms
            and work.published_at_ms
            and (work.published_at_ms + SINCE_TOLERANCE_MS) < since_ms
        ):
            continue
        return work
    return None


def resolve_readback(
    works: list[WorkItem],
    title: str,
    *,
    since_ms: int | None = None,
    exclude_ids: set[str] | None = None,
    login_required: bool = False,
    error: str | None = None,
) -> ReadbackResult:
    """按 platform_readback 四档语义处理一次读回。

    优先级：login_required > readback_error > verified/unverified。
    未命中时返回 unverified，并保留候选作品供人工核对。
    """
    key = (title or "").strip().replace("\n", " ")[:TITLE_KEY_LEN]
    candidates = [work for work in works if key and key in (work.title or "")]
    evidence: dict[str, Any] = {
        "title_key": key,
        "since_ms": since_ms,
        "candidate_count": len(candidates),
    }
    if login_required:
        return ReadbackResult(
            READBACK_LOGIN_REQUIRED,
            candidates=candidates,
            evidence=evidence,
            error=None,
        )
    if error:
        return ReadbackResult(
            READBACK_ERROR,
            candidates=candidates,
            evidence=evidence,
            error=error,
        )
    matched = find_published_work(
        works,
        title,
        since_ms=since_ms,
        exclude_ids=exclude_ids,
    )
    if matched is not None:
        evidence["matched_id"] = matched.platform_content_id
        return ReadbackResult(
            READBACK_VERIFIED,
            matched=matched,
            candidates=candidates,
            evidence=evidence,
        )
    return ReadbackResult(
        READBACK_UNVERIFIED,
        candidates=candidates,
        evidence=evidence,
    )


def captured_at_now() -> datetime:
    return datetime.now(UTC)

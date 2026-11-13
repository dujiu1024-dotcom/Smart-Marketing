from store_operator.effects.easel_parsing import (
    READBACK_ERROR,
    READBACK_LOGIN_REQUIRED,
    READBACK_UNVERIFIED,
    READBACK_VERIFIED,
    WorkItem,
    epoch_ms,
    find_published_work,
    growth_windows,
    lines_of,
    metrics_with_vs,
    num_by_label,
    parse_num,
    resolve_readback,
)


def test_parse_num_handles_units_separators_and_invalid_values():
    assert parse_num("1,234") == 1234
    assert parse_num("1.2万") == 12000
    assert parse_num("3.4亿") == 340_000_000
    assert parse_num("12.5k") == 12500
    assert parse_num(" 890 ") == 890
    assert parse_num("1.2w") == 12000
    assert parse_num("") is None
    assert parse_num(None) is None
    assert parse_num("暂无") is None


def test_lines_of_trims_and_drops_blank_lines():
    assert lines_of(" 粉丝 \n\n 1.2万 \n") == ["粉丝", "1.2万"]


def test_num_by_label_after_and_before_directions():
    after = ["粉丝", "1.2万", "获赞", "3.4万"]
    assert num_by_label(after, ["粉丝"], "after") == 12000
    assert num_by_label(after, ["获赞"], "after") == 34000

    before = ["1.2万", "粉丝数", "3.4万", "获赞与收藏"]
    assert num_by_label(before, ["粉丝数"], "before") == 12000
    assert num_by_label(before, ["获赞与收藏"], "before") == 34000

    # 同行内联写法
    assert num_by_label(["粉丝 1.5万"], ["粉丝"], "after") == 15000
    assert num_by_label(["粉丝"], ["关注"], "after") is None


def test_metrics_with_vs_respects_anchor_and_captures_ratio():
    lines = [
        "历史模块",
        "播放量",
        "999",
        "近7日",
        "播放量",
        "1,234",
        "+12%",
        "主页访问量",
        "890",
        "环比-3%",
    ]
    result = metrics_with_vs(lines, ["播放量", "主页访问量"], "近7日")
    assert result == [
        {"label": "播放量", "value": "1,234", "vs": "+12%"},
        {"label": "主页访问量", "value": "890", "vs": "-3%"},
    ]
    # anchor 不存在时不做无锚点解析
    assert metrics_with_vs(lines, ["播放量"], "近30日") == []


def test_growth_windows_compare_history_baselines():
    current = {"ts": 1_000_000, "followers": 1200, "likes": 3400, "posts": 56}
    history = [
        {"ts": 1_000_000 - 2 * 86400, "followers": 1000, "likes": 3000, "posts": 50},
        {"ts": 1_000_000 - 10 * 86400, "followers": 800, "likes": 2000, "posts": 40},
    ]
    windows = growth_windows(history, current)
    assert windows["day"]["followers"] == 200
    assert windows["week"]["followers"] == 400
    assert windows["month"] is None
    assert windows["last"]["followers"] == 200

    empty = growth_windows([], current)
    assert all(value is None for value in empty.values())


def test_epoch_ms_normalizes_seconds_and_milliseconds():
    assert epoch_ms(1_700_000_000) == 1_700_000_000_000
    assert epoch_ms(1_700_000_000_000) == 1_700_000_000_000
    assert epoch_ms(None) is None
    assert epoch_ms(0) is None


def _works():
    return [
        WorkItem("w-old", "秋季新品到店打卡分享", "published", 1_000_000),
        WorkItem("w-new", "秋季新品到店打卡分享第二弹", "published", 1_700_000_000_000),
        WorkItem("w-other", "完全无关的内容", "published", 1_700_000_000_000),
    ]


def test_find_published_work_uses_title_prefix_and_time_window():
    works = _works()
    # 默认只按标题前缀命中，返回第一件匹配
    assert find_published_work(works, "秋季新品到店打卡分享") == works[0]
    # 时间窗排除旧作品
    assert find_published_work(
        works, "秋季新品到店打卡分享", since_ms=1_600_000_000_000
    ) == works[1]
    # 显式排除已对账作品
    assert find_published_work(
        works,
        "秋季新品到店打卡分享",
        exclude_ids={"w-old"},
    ) == works[1]
    # 空标题不匹配
    assert find_published_work(works, "   ") is None
    # 标题前缀不足 12 字时按实际长度匹配
    assert find_published_work(works, "完全无关") == works[2]


def test_resolve_readback_returns_all_four_outcomes():
    works = _works()
    verified = resolve_readback(works, "秋季新品到店打卡分享第二弹")
    assert verified.outcome == READBACK_VERIFIED
    assert verified.matched is works[1]

    unverified = resolve_readback(works, "从未发布过的标题")
    assert unverified.outcome == READBACK_UNVERIFIED
    assert unverified.matched is None

    login = resolve_readback(works, "秋季新品到店打卡分享", login_required=True)
    assert login.outcome == READBACK_LOGIN_REQUIRED
    assert login.matched is None

    failed = resolve_readback(
        works, "秋季新品到店打卡分享", error="creator center request failed"
    )
    assert failed.outcome == READBACK_ERROR
    assert failed.error == "creator center request failed"
    # 登录态优先于读回错误
    assert (
        resolve_readback(
            works,
            "秋季新品到店打卡分享",
            login_required=True,
            error="network",
        ).outcome
        == READBACK_LOGIN_REQUIRED
    )

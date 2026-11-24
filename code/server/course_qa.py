"""课表问答（2026-11-06）

为什么加这一层
    课表原来只用于「到点提醒」。学生张嘴问「明天几节课」「下节课是什么」，
    只能答「我这边查不到」—— 数据明明就在本地（`提醒.db`）✗。
    所以加一层完全本地的问答：不经过平台、0 延迟，平台挂了也能答 ✓。

为什么不让平台答
    平台绑定的知识库是「学校规定」，里面没有、也不该有某个学生的课表 ✗。
    课表是我们自己存的私事，只在本机算。

边界（明确不接管）
    问「课表怎么上传 / 怎么导入 / PDF 解析」这类**流程问题**，交给平台 ——
    那是在问怎么用，不是问自己的课。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from . import reminders, timetable

# 命中这些词才可能是「问自己的课」
_WORDS = ("课表", "有课", "没课", "几节课", "几节", "什么课", "下节课", "下一节", "上课")
# 命中这些词说明问的是"怎么用"，交给平台
_FLOW = ("上传", "导入", "怎么传", "怎么弄", "解析", "识别", "pdf", "PDF", "学期", "模板", "格式")

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7, "七": 7}
_NEXT_WORDS = ("下节课", "下一节", "下一节课", "接下来", "还有什么课")

# 2026-11-24 补：原来只认"今天/明天/周X"，学生实际会问
#   「第 14 周周一第一节课是什么」「周三上午有什么课」—— 周次、节次、半天全被忽略 ✗
#   结果：问第一节给全部、问上午给整天、问"周三"答"明天"（听着就是答错）。
_WEEKDAY_RE = re.compile(r"(?:周|星期|礼拜)([一二三四五六日天七])")
_WEEK_RE = re.compile(r"第?\s*(\d{1,2})\s*周")
_PERIOD_RE = re.compile(r"第?\s*([一二三四五六七八九十两\d]{1,3})\s*节")
# 半天 → 起止小时（左闭右开）
_PART_WORDS = (
    ("上午", 0, 12), ("早上", 0, 12), ("中午", 10, 14),
    ("下午", 12, 18), ("傍晚", 16, 19), ("晚上", 17, 24),
)
_CN_DIGIT = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "两": 2}


def _cn_int(s: str):
    """把「一」「十二」「二十」「3」这类换成整数；认不出返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s.startswith("十"):
        tail = _CN_DIGIT.get(s[1:])
        return 10 + tail if tail else None
    if s.endswith("十"):
        head = _CN_DIGIT.get(s[0])
        return head * 10 if head else None
    if len(s) == 1:
        return _CN_DIGIT.get(s)
    return None


def _parse_week(query: str):
    """「第 14 周」「14 周」→ 14；没提返回 None。"""
    m = _WEEK_RE.search(query or "")
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 30 else None


def _parse_period(query: str):
    """「第一节课」「第 3 节」→ 1 / 3；没提返回 None。"""
    m = _PERIOD_RE.search(query or "")
    if not m:
        return None
    n = _cn_int(m.group(1))
    return n if n and 1 <= n <= 12 else None


def _parse_part(query: str):
    """「上午 / 下午 / 晚上」→ (起, 止) 小时；没提返回 None。"""
    q = query or ""
    hits = [(name, lo, hi) for name, lo, hi in _PART_WORDS if name in q]
    if not hits:
        return None
    # 取最长的那个词（"一大早"里既有"大一"没有，这里按名字长度无意义，取先出现的即可）
    for name, lo, hi in hits:
        return name, lo, hi
    return None


def looks_like(query: str) -> bool:
    """这句是不是在问自己的课表。"""
    t = query or ""
    if any(w in t for w in _FLOW):
        return False
    return any(w in t for w in _WORDS)


def _week_no(week1_monday, day) -> int:
    return (day - week1_monday).days // 7 + 1


def _start_of(period: int, settings) -> str:
    """第 period 节几点开始，返回 "HH:MM"。学期参数里改过作息就以它为准。"""
    periods = (settings or {}).get("periods") or {}
    got = periods.get(str(period)) or periods.get(period)
    if isinstance(got, str) and re.fullmatch(r"\d{1,2}:\d{2}", got):
        hh, mm = got.split(":")
        return f"{int(hh):02d}:{int(mm):02d}"
    hh, mm = timetable.PERIOD_START.get(period, (0, 0))
    return f"{hh:02d}:{mm:02d}"


def _courses_on(items, settings, weekday: int, week_no: int):
    """某天（周几）在第 week_no 周的课，按上课时间排序。"""
    out = []
    for c in items:
        if int(c.get("weekday") or 0) != weekday:
            continue
        weeks = c.get("weeks") or []
        if weeks and week_no not in weeks:
            continue          # 单双周 / 只上几周
        out.append({**c, "_start": _start_of(int(c.get("period") or 1), settings)})
    out.sort(key=lambda c: c["_start"])
    return out


def _resolve_day(query: str, now: datetime):
    """问的是哪一天。默认今天。"""
    today = now.date()
    if "后天" in query:
        return today + timedelta(days=2)
    if "明天" in query or "明日" in query:
        return today + timedelta(days=1)
    if "昨天" in query:
        return today - timedelta(days=1)
    m = re.search(r"(?:周|星期|礼拜)([一二三四五六日天七])", query)
    if m:
        wd = _CN_NUM[m.group(1)]
        return today + timedelta(days=(wd - today.isoweekday()) % 7)
    return today


def _day_label(query: str, day, now: datetime) -> str:
    """这天怎么说。2026-11-24 改：用户明说了「周三」，就复述「周三」——
    原来一律说「明天/后天」，问周三听到"明天没课"，会以为答错了。"""
    if _WEEKDAY_RE.search(query or ""):
        return f"周{timetable.WEEKDAY_NAMES[day.isoweekday() - 1]}"
    today = now.date()
    if day == today:
        return "今天"
    if day == today + timedelta(days=1):
        return "明天"
    if day == today + timedelta(days=2):
        return "后天"
    if day == today - timedelta(days=1):
        return "昨天"
    return f"周{timetable.WEEKDAY_NAMES[day.isoweekday() - 1]}"


def _next_course(items, settings, now: datetime):
    """从现在起最近的一节课：(日期, 课程, 开始钟点) 或 None。"""
    week1 = settings["week1_monday"]
    for i in range(0, 8):
        day = now.date() + timedelta(days=i)
        for c in _courses_on(items, settings, day.isoweekday(), _week_no(week1, day)):
            if day == now.date() and c["_start"] <= now.strftime("%H:%M"):
                continue      # 今天已经上过的跳过
            return day, c, c["_start"]
    return None


def answer(query: str, now: datetime | None = None) -> str | None:
    """答一句课表相关的话；认不出（或没数据到无法回答）返回 None 交给后面。"""
    now = now or datetime.now()
    q = query or ""
    try:
        items = reminders.load_items()
    except Exception:
        return None
    if not items:
        return ("课表还没上传呢。让管理员在网页上传教务处那张课表 PDF，"
                "之后我就能提醒你什么时候上课。")

    settings = reminders.get_settings()

    if any(w in q for w in _NEXT_WORDS):
        got = _next_course(items, settings, now)
        if not got:
            return "接下来一周没课，可以歇歇。"
        day, course, hhmm = got
        when = "今天" if day == now.date() else _day_label(q, day, now)
        return (f"下一节是{when} {hhmm} 的{course.get('name', '课')}，"
                f"在{course.get('venue', '教室')}。")

    # 2026-11-24 补：周次 / 节次 / 半天
    week_override = _parse_week(q)
    period = _parse_period(q)
    part = _parse_part(q)

    day = _resolve_day(q, now)
    cur_week = _week_no(settings["week1_monday"], now.date())
    week_no = week_override if week_override is not None else _week_no(settings["week1_monday"], day)
    label = _day_label(q, day, now)
    if week_override is not None and week_no != cur_week:
        label = f"第 {week_no} 周{label}"
    if part:
        label = f"{label}{part[0]}"

    courses = _courses_on(items, settings, day.isoweekday(), week_no)
    if part:
        _, lo, hi = part
        courses = [c for c in courses if lo <= int(c["_start"][:2]) < hi]

    # 只有"问的是今天、又没指定周次/节次"时，才滤掉已经上过的课
    if day == now.date() and week_override is None and period is None:
        today_all = courses
        courses = [c for c in courses if c["_start"] > now.strftime("%H:%M")]
        if not courses:
            # 今天本来就没课 ≠ 今天的课上完了（2026-11-24 区分开，否则第 13 周这种整周空档会说错）
            if today_all:
                return "今天的课上完了，剩下的时间归你。"
            return "今天没课。"

    # 问具体第几节：只答那一节，别把一天的课都倒出来
    if period is not None:
        hit = [c for c in courses if int(c.get("period") or 0) == period]
        if hit:
            c = hit[0]
            return (f"{label}第 {period} 节是 {c['_start']} 的{c.get('name', '课')}，"
                    f"在{c.get('venue', '教室')}。")
        return f"{label}第 {period} 节没课。"

    if not courses:
        return f"{label}没课。"

    parts = [f"{c['_start']} 的{c.get('name', '课')}" for c in courses[:5]]
    tail = "" if len(courses) <= 5 else f"，还有 {len(courses) - 5} 节"
    return f"{label}有 {len(courses)} 节课：{'、'.join(parts)}{tail}。"

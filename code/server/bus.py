"""校车（两江校区交通车）—— 本地静态时刻表（2026-11-24）

为什么从平台搬到本地
    校车时刻表是**整学期不变的静态数据**，原来却走平台：
      · 正常时多等 **4.6 秒**（链路日志 p50，平台是全链路最慢一环）
      · 检索服务一超时（`ragtool.Invoke RequestRag err: i/o timeout`）整句 400，
        本地兜底只能答「我在呢，有什么可以帮你的吗？」—— 答非所问 ✗
    数据本身没错，错的是"把静态表交给会抖动的外部服务"。

    搬过来之后：0 延迟、平台挂了照答、还能写测试钉住（见 tests/test_bus.py）。

数据来源
    `code/过程文档/知识库补充_校车.md`（2026-2027 秋季学期通知），
    按**方向**分组：A = 去两江（从杨家坪/花溪 到 两江），B = 离开两江。
    方向反了是这类问题最常见的错法（12:50 两个方向各有一班），所以内部也按方向存。
"""

from __future__ import annotations

from datetime import datetime, timedelta

# (发车, 从哪, 到哪, 备注)
_A_MON = [
    ("06:50", "杨家坪校区", "两江校区", ""),
    ("06:50", "花溪校区", "两江校区", ""),
    ("07:00", "杨家坪校区", "两江校区", ""),
    ("07:00", "花溪校区", "两江校区", ""),
    ("12:30", "杨家坪校区", "两江校区", "12:50 经停花溪"),
    ("18:30", "杨家坪校区", "两江校区", "19:00 经停花溪"),
]
_B_MON = [
    ("10:30", "两江校区", "经花溪至杨家坪", ""),
    ("12:50", "两江校区", "花溪校区", ""),
    ("12:50", "两江校区", "经花溪至杨家坪", ""),
    ("17:40", "两江校区", "经花溪至杨家坪", ""),
    ("20:45", "两江校区", "经杨家坪至花溪", ""),
]

_A_TUE_FRI = [
    ("06:50", "杨家坪校区", "两江校区", ""),
    ("06:50", "花溪校区", "两江校区", ""),
    ("07:00", "杨家坪校区", "两江校区", ""),
    ("07:00", "花溪校区", "两江校区", ""),
    ("12:30", "杨家坪校区", "两江校区", "12:50 经停花溪"),
    ("12:50", "花溪校区", "两江校区", ""),
    ("16:00", "杨家坪校区", "两江校区", "16:20 经停花溪"),
    ("18:30", "杨家坪校区", "两江校区", "19:00 经停花溪"),
]
_B_TUE_FRI = [
    ("10:30", "两江校区", "经花溪至杨家坪", ""),
    ("12:50", "两江校区", "经花溪至杨家坪", ""),
    ("16:30", "两江校区", "经花溪至杨家坪", ""),
    ("17:40", "两江校区", "经杨家坪至花溪", ""),
    ("18:20", "两江校区", "经杨家坪至花溪", ""),
    ("18:20", "两江校区", "花溪校区", ""),
    ("20:45", "两江校区", "经杨家坪至花溪", ""),
]

# 周六只在第 2~18 周运行
_A_SAT = [
    ("06:50", "杨家坪校区", "两江校区", "7:10 经停花溪"),
    ("12:30", "杨家坪校区", "两江校区", "12:50 经停花溪"),
]
_B_SAT = [
    ("12:50", "两江校区", "经花溪至杨家坪", ""),
    ("18:20", "两江校区", "经花溪至杨家坪", ""),
]

# 节假日最后一天只有进校方向
_A_LASTDAY = [("16:30", "杨家坪校区", "两江校区", "16:50 经停花溪")]

PLACE = ("两江校区上车在弘远楼大门口（也经停百味坊对面嘉福路），下车在弘远楼大门口；"
         "杨家坪在荷花池六栋前；花溪在花溪校区大门口。")
PHONE = "花溪校区 62563023（杨老师、王老师），两江校区 62565025（饶老师）。"
RULE = ("交通车主要服务教职工，凭教工卡或知行理工本人界面乘车；"
        "其他因工作需要乘车的要先办乘车票（花溪在明德楼306，两江在百味坊五楼515）。")
LOST = ("东西落车上，三日内凭有效证件去花溪校区大门口门岗，"
        "或两江校区弘远楼一楼教学服务大厅领取。")

_WORDS = ("校车", "交通车", "班车", "校区间车")
_TIME_WORDS = ("几点", "时间", "时刻", "有车", "发车", "最早", "最晚", "末班", "首班",
               "第一班", "最后一班", "下一班", "还有")
_GO = ("去两江", "到两江", "去校区", "进校", "去学校", "往两江", "到校")
_BACK = ("回", "返程", "离开", "回花溪", "回杨家坪", "从两江")

# 星期几的说法 → isoweekday()
_WEEKDAY_WORDS = {"周一": 1, "周二": 2, "周三": 3, "周四": 4,
                  "周五": 5, "周六": 6, "周末": 6, "周日": 7, "周天": 7}
_WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


# 「没直说是校车、但明显在问车」的说法：提了校区 + 提了车/班的词
_PLACES = ("两江", "花溪", "杨家坪")
_TRANSPORT = ("车", "班", "几点", "最早", "最晚", "末班", "首班",
              "有没有", "还有", "发车", "开车", "往返", "过去")


def looks_like(query: str) -> bool:
    q = query or ""
    if any(w in q for w in _WORDS):
        return True
    # 2026-11-26 补：「明天去两江的车」这类不含"校车"二字，以前会漏到平台（15 秒才回退）
    return any(p in q for p in _PLACES) and any(t in q for t in _TRANSPORT)


def _direction(query: str):
    """'A' = 去两江；'B' = 离开两江；None = 没明说。"""
    q = query or ""
    if any(w in q for w in _BACK):
        return "B"
    if any(w in q for w in _GO):
        return "A"
    return None


def _target_date(query: str, now: datetime):
    """问的是哪一天：今天 / 明天 / 后天 / 某个星期几（取最近的那次）。"""
    q = query or ""
    today = now.date()
    if "后天" in q:
        return today + timedelta(days=2)
    if "明天" in q or "明日" in q:
        return today + timedelta(days=1)
    for word, wd in _WEEKDAY_WORDS.items():
        if word in q:
            return today + timedelta(days=(wd - today.isoweekday()) % 7)
    return today


def _day_word(target, now: datetime) -> str:
    today = now.date()
    if target == today:
        return "今天"
    if target == today + timedelta(days=1):
        return "明天"
    if target == today + timedelta(days=2):
        return "后天"
    return _WEEKDAY_NAMES[target.isoweekday() - 1]


def _day_tables(target, now: datetime):
    """返回 (称呼, A 表, B 表)；当天没车返回 (说明, None, None)。"""
    wd = target.isoweekday()
    if wd == 1:
        return _day_word(target, now), _A_MON, _B_MON
    if 2 <= wd <= 5:
        return _day_word(target, now), _A_TUE_FRI, _B_TUE_FRI
    if wd == 6:
        # 周六只在第 2~18 周运行 —— 周次取不到就按"在区间内"处理（别因为读库失败就答"没车"）
        week = None
        try:
            from . import reminders
            w1 = (reminders.get_settings() or {}).get("week1_monday")
            if w1:
                week = (target - w1).days // 7 + 1
        except Exception:
            week = None
        if week is not None and not (2 <= week <= 18):
            return (f"周六的班车只在第 2~18 周运行，现在是第 {week} 周，没有车".replace(
                "周六的", f"{_day_word(target, now)}的"), None, None)
        return _day_word(target, now), _A_SAT, _B_SAT
    return _day_word(target, now), None, None


def _times(rows):
    """按发车时间列成『06:50、07:00』（同一时刻的两班只列一次）。"""
    seen = []
    for r in rows:
        if r[0] not in seen:
            seen.append(r[0])
    return "、".join(seen)


def _count(rows):
    return len({r[0] for r in rows})


def _next_after(rows, hhmm: str):
    for r in rows:
        if r[0] >= hhmm:
            return r
    return None


def answer(query: str, now: datetime | None = None) -> str | None:
    q = query or ""
    now = now or datetime.now()

    # 非时刻类信息，先答
    if "电话" in q or "联系" in q:
        return PHONE
    if "丢" in q or "失物" in q or "落" in q:
        return LOST
    if "在哪" in q or "上车" in q or "地点" in q or "哪里坐" in q:
        return PLACE
    if "学生" in q or "能坐" in q or "证明" in q or "车票" in q or "手续" in q:
        return RULE

    target = _target_date(q, now)
    day_word, a_rows, b_rows = _day_tables(target, now)
    if a_rows is None:
        # day_word 此时可能是「周日」，也可能是那句"…只在第 2~18 周运行"的完整说明
        return day_word if day_word.endswith("车") else f"{day_word}没有交通车。"

    direction = _direction(q)
    hhmm = now.strftime("%H:%M")
    is_today = target == now.date()

    if direction is None:
        if any(w in q for w in ("最早", "首班", "第一班")):
            return (f"{day_word}：去两江最早 {a_rows[0][0]}（{a_rows[0][1]}），"
                    f"从两江走最早 {b_rows[0][0]}。")
        if any(w in q for w in ("最晚", "末班", "最后一班")):
            return (f"{day_word}：去两江最晚 {a_rows[-1][0]}，"
                    f"从两江走最晚 {b_rows[-1][0]}。")
        # 只有"今天"才谈"最近一班"；问别的日子就直接列时刻
        if is_today:
            na, nb = _next_after(a_rows, hhmm), _next_after(b_rows, hhmm)
            bits = []
            if na:
                bits.append(f"去两江最近一班 {na[0]}（{na[1]}）")
            if nb:
                bits.append(f"从两江走最近一班 {nb[0]}")
            if bits:
                return "今天：" + "；".join(bits) + "。"
            return f"今天的班车都发完了，去两江最早一班是 {a_rows[0][0]}。"
        return f"{day_word}：去两江 {_times(a_rows)}；从两江走 {_times(b_rows)}。"

    rows = a_rows if direction == "A" else b_rows
    where = "去两江" if direction == "A" else "从两江走"

    if any(w in q for w in ("最早", "首班", "第一班")):
        return f"{day_word}{where}最早一班是 {rows[0][0]}（{rows[0][1]}）。"
    if any(w in q for w in ("最晚", "末班", "最后一班")):
        last = rows[-1]
        return f"{day_word}{where}最晚一班是 {last[0]}（{last[1]} 发车，{last[2]}）。"
    if is_today and any(w in q for w in ("下一班", "还有")):
        nxt = _next_after(rows, hhmm)
        if not nxt:
            return f"今天{where}的班车都发完了。"
        return f"今天{where}最近一班是 {nxt[0]}（{nxt[1]}）。"

    return f"{day_word}{where}：{_times(rows)}。"


def table_summary(now: datetime | None = None) -> str:
    """给网页/文档用的一行总览（时刻按去重后的数量算）。"""
    now = now or datetime.now()
    label = _WEEKDAY_NAMES[now.isoweekday() - 1]
    _, a_rows, b_rows = _day_tables(now.date(), now)
    if a_rows is None:
        return f"{label}没有交通车。"
    return (f"{label}：去两江 {_count(a_rows)} 个时刻（{_times(a_rows)}）；"
            f"从两江走 {_count(b_rows)} 个时刻（{_times(b_rows)}）。")

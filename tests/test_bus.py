"""校车本地时刻表的测试（2026-11-24）

为什么值得测
    这批数据整学期不变，但**方向**和**星期**是最容易答错的两处：
      · 12:50 在「花溪→两江」和「两江→花溪」各有一班，方向反了就是错答案（真机上发生过）
      · 周一没有 16:00/16:30，周二至周五有
    所以测试按「星期 × 方向」四象限铺开，把每条都钉住。
"""
import datetime as dt

import pytest

from server import bus, reminders

# 2026-11-23 周一 / 11-24 周二 / 11-28 周六 / 11-29 周日
MON = dt.datetime(2026, 11, 23, 9, 0, 0)
TUE = dt.datetime(2026, 11, 24, 9, 0, 0)
SAT = dt.datetime(2026, 11, 28, 9, 0, 0)
SUN = dt.datetime(2026, 11, 29, 9, 0, 0)

SETTINGS = {"week1_monday": dt.date(2026, 8, 31), "early_minutes": 20, "periods": {}}


@pytest.fixture(autouse=True)
def fake_settings(monkeypatch):
    """周六是否在 2~18 周要读提醒库的设置，这里给个固定值。"""
    try:
        monkeypatch.setattr(reminders, "get_settings", lambda: dict(SETTINGS))
    except Exception:
        pass


# ---------- 该不该接管 ----------

@pytest.mark.parametrize("q", ["校车几点发车", "交通车时间", "班车有吗", "校车在哪上车"])
def test_looks_like_true(q):
    assert bus.looks_like(q) is True


@pytest.mark.parametrize("q", ["今天有课吗", "校训是什么", "帮我订个闹钟"])
def test_looks_like_false(q):
    assert bus.looks_like(q) is False


# ---------- 方向：最容易错的地方 ----------

def test_go_to_liangjiang_never_includes_return_times():
    """去两江的表里不能出现 10:30 / 20:45 这类返程班次。"""
    got = bus.answer("周一去两江几点有车", MON)
    assert "去两江" in got
    assert "10:30" not in got
    assert "20:45" not in got


def test_return_from_liangjiang_never_includes_morning_arrivals():
    """从两江走的表里不能出现 06:50 / 07:00 这类进校班次。"""
    got = bus.answer("周一从两江回花溪几点有车", MON)
    assert "从两江走" in got
    assert "06:50" not in got
    assert "07:00" not in got


def test_1250_exists_in_both_directions_but_not_mixed():
    """12:50 两个方向各有一班 —— 答 A 表就不能带 B 表的那条。"""
    a = bus.answer("周二去两江几点有车", TUE)
    b = bus.answer("周二从两江走几点有车", TUE)
    assert "12:50" in a and "12:50" in b          # 两表都有 12:50
    assert "10:30" not in a and "16:00" not in b   # 但方向不能串


# ---------- 星期差异 ----------

def test_monday_has_no_1600_or_1630():
    a = bus.answer("周一去两江几点有车", MON)
    b = bus.answer("周一从两江走几点有车", MON)
    assert "16:00" not in a
    assert "16:30" not in b


def test_tue_to_fri_has_1600_and_1630():
    a = bus.answer("周二去两江几点有车", TUE)
    b = bus.answer("周二从两江走几点有车", TUE)
    assert "16:00" in a
    assert "16:30" in b


def test_sunday_says_no_bus():
    got = bus.answer("校车几点发车", SUN)
    assert "没有交通车" in got


def test_saturday_runs_in_week_range():
    """第 13 周（在 2~18 内）→ 周六有车。"""
    got = bus.answer("周六去两江几点有车", SAT)
    assert "06:50" in got and "12:30" in got


def test_saturday_outside_week_range(monkeypatch):
    """第 20 周 → 周六没车（周六只跑第 2~18 周）。"""
    monkeypatch.setattr(reminders, "get_settings",
                        lambda: {"week1_monday": dt.date(2026, 7, 13), "early_minutes": 20, "periods": {}})
    got = bus.answer("周六有校车吗", SAT)
    assert "2~18" in got or "没有车" in got


# ---------- 最早 / 最晚 / 下一班 ----------

def test_first_and_last():
    assert "06:50" in bus.answer("最早一班校车几点", MON)
    assert "20:45" in bus.answer("最晚一班从两江走几点", MON)


def test_next_bus_after_morning():
    got = bus.answer("下一班去两江的车", TUE)     # 9:00 之后最近的是 12:30
    assert "12:30" in got


def test_no_direction_gives_nearest_both_ways():
    got = bus.answer("校车几点发车", TUE)
    assert "去两江" in got and "从两江走" in got


# ---------- 非时刻类 ----------

def test_phone_place_rule_lost():
    assert "62563023" in bus.answer("校车电话是多少", TUE)
    assert "弘远楼" in bus.answer("校车在哪上车", TUE)
    assert "乘车票" in bus.answer("学生能坐校车吗", TUE)
    assert "三日" in bus.answer("东西落校车上了怎么办", TUE)


def test_table_summary_is_consistent():
    """总览里的时刻数要和实测一致（时刻去重：周一 4+4，周二至周五 6+6）。"""
    s_mon = bus.table_summary(MON)
    assert "去两江 4 个时刻" in s_mon and "从两江走 4 个时刻" in s_mon
    s_tue = bus.table_summary(TUE)
    assert "去两江 6 个时刻" in s_tue and "从两江走 6 个时刻" in s_tue

# ---------- 明天 / 后天 ----------

def test_tomorrow_says_tomorrow_and_uses_that_days_table():
    """周二问「明天去两江」→ 说的是明天，用的是周三（同为周二至周五表）。"""
    got = bus.answer("明天去两江有车吗", TUE)
    assert got.startswith("明天")
    assert "16:00" in got


def test_friday_asks_saturday_uses_saturday_table():
    """周五问「明天」（周六）→ 落到周六表，而不是默认的周二至周五表。"""
    fri = dt.datetime(2026, 11, 27, 9, 0, 0)
    got = bus.answer("明天去两江有车吗", fri)
    assert got.startswith("明天")
    assert "16:00" not in got and "06:50" in got


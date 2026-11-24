"""周次 / 节次 / 半天 三类问法的测试（2026-11-24 补）

为什么加这组
    真机上出现过：问「我 14 周周一第一节课是什么」→ 答了整天的课；
    问「我周三上午有什么课」→ 答「明天没课」（周几被换成"明天"，听着像答错）。
    根因是解析器只认"今天/明天/周X"，周次、节次、半天全被丢掉。

    这组把三个新能力钉住，顺便钉住"今天没课 ≠ 今天的课上完了"。

时间基准：第 1 周周一 = 2026-08-31，于是
    2026-11-24（周二）= 第 13 周；2026-11-30（下周一）= 第 14 周。
"""
import datetime as dt

import pytest

from server import course_qa, reminders

WEEK1_MON = dt.date(2026, 8, 31)          # 第 1 周周一
NOW = dt.datetime(2026, 11, 24, 12, 0, 0)  # 周二中午，第 13 周

ITEMS = [
    # 第 13 周：只有周一上午一节（周二是空的 → 用来验"今天没课"）
    {"name": "中国近现代史纲要", "weekday": 1, "period": 1, "venue": "弘远楼B0119", "weeks": [13]},
    # 第 14 周周一：两节 → 验"第一节课"
    {"name": "中国近现代史纲要", "weekday": 1, "period": 1, "venue": "弘远楼B0119", "weeks": [14]},
    {"name": "创业基础", "weekday": 1, "period": 3, "venue": "弘远楼C0118", "weeks": [14]},
    # 第 14 周周三：四节，上午 / 下午 / 晚上各有时段 → 验半天过滤
    {"name": "线性代数[理工]", "weekday": 3, "period": 1, "venue": "弘远楼B0321", "weeks": [14]},
    {"name": "大学物理学II（2）", "weekday": 3, "period": 3, "venue": "弘远楼B0205", "weeks": [14]},
    {"name": "数字电子技术", "weekday": 3, "period": 5, "venue": "弘远楼C0301", "weeks": [14]},
    {"name": "影像中的生死学", "weekday": 3, "period": 9, "venue": "弘远楼A0402", "weeks": [14]},
]

SETTINGS = {
    "week1_monday": WEEK1_MON,
    "early_minutes": 20,
    "periods": {"1": "08:30", "3": "10:30", "5": "14:20", "7": "16:20", "9": "19:00"},
}


@pytest.fixture(autouse=True)
def fake_schedule(monkeypatch):
    monkeypatch.setattr(reminders, "load_items", lambda: list(ITEMS))
    monkeypatch.setattr(reminders, "get_settings", lambda: dict(SETTINGS))


def test_week1_baseline_is_what_we_think():
    """先把基准钉住：否则后面所有周次断言都是空的。"""
    assert course_qa._week_no(WEEK1_MON, dt.date(2026, 11, 24)) == 13
    assert course_qa._week_no(WEEK1_MON, dt.date(2026, 11, 30)) == 14


# ---------- 周次 ----------

def test_week_number_is_parsed():
    assert course_qa._parse_week("我14周周一第一节课是什么课") == 14
    assert course_qa._parse_week("第 14 周周三有什么课") == 14
    assert course_qa._parse_week("明天有课吗") is None
    assert course_qa._parse_week("99周有课吗") is None      # 离谱的周次不认


def test_explicit_week_uses_that_week():
    a = course_qa.answer("第14周周三有什么课", NOW)
    assert "第 14 周" in a and "4 节课" in a and "线性代数" in a

    b = course_qa.answer("第13周周三有什么课", NOW)
    assert "没课" in b


# ---------- 节次 ----------

def test_period_number_is_parsed():
    assert course_qa._parse_period("我14周周一第一节课是什么课") == 1
    assert course_qa._parse_period("第 3 节呢") == 3
    assert course_qa._parse_period("周三有课吗") is None     # 「几节课」不能被当成节次
    assert course_qa._parse_period("还有几节课") is None


def test_ask_first_period_answers_one_course_only():
    got = course_qa.answer("我14周周一第一节课是什么课？", NOW)
    assert "第 14 周周一第 1 节" in got
    assert "中国近现代史纲要" in got
    assert "创业基础" not in got          # 第 3 节那门不该出现


def test_ask_period_with_no_course():
    got = course_qa.answer("第14周周一第 7 节有课吗", NOW)
    assert "没课" in got


# ---------- 半天 ----------

def test_part_of_day_is_parsed():
    assert course_qa._parse_part("我周三上午有什么课")[0] == "上午"
    assert course_qa._parse_part("下午有课吗")[0] == "下午"
    assert course_qa._parse_part("晚上呢")[0] == "晚上"
    assert course_qa._parse_part("明天有课吗") is None


def test_morning_filters_out_afternoon_and_evening():
    got = course_qa.answer("第14周周三上午有什么课", NOW)
    assert "2 节课" in got
    assert "线性代数" in got and "大学物理" in got
    assert "数字电子技术" not in got      # 14:20
    assert "影像中的生死学" not in got    # 19:00


def test_evening_keeps_only_night_course():
    got = course_qa.answer("第14周周三晚上有什么课", NOW)
    assert "影像中的生死学" in got and "1 节课" in got


# ---------- 措辞：问哪天就说哪天 ----------

def test_label_repeats_asked_weekday_not_tomorrow():
    """今天周二，问周三 —— 必须说「周三」，不能说「明天」。"""
    got = course_qa.answer("我周三上午有什么课？", NOW)
    assert "周三" in got
    assert "明天" not in got


# ---------- 今天没课 ≠ 今天的课上完了 ----------

def test_empty_week_says_no_class_not_finished():
    got = course_qa.answer("今天有课吗", NOW)          # 第 13 周周二，本来就没课
    assert got == "今天没课。"


def test_finished_only_when_all_today_passed():
    late = dt.datetime(2026, 11, 23, 23, 0, 0)        # 第 13 周周一 23:00，08:30 那节已过
    got = course_qa.answer("今天有课吗", late)
    assert "课上完了" in got

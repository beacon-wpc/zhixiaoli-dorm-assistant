"""回归测试：异步语音的音频地址必须跟着「板子用的地址」走（2026-11-27）

真实故障：
    串口 `【开始播放音频】: http://10.202.100.19:5000/audio/…` → connecttohost 失败
    板子其实在 192.168.137.39（走笔记本热点），那个校园网地址它够不着。
    根因：/v1/voice?async=1 把活交给后台线程，线程里没有请求上下文，
          trace.base_url() 回落到 PUBLIC_HOST（校园网 IP）。
"""
from server import app as A, trace


def test_async_job_uses_request_base(monkeypatch):
    """线程里必须能拿到调用方传进来的基地址。"""
    seen = {}

    def fake_pipeline(wav):
        seen["base"] = trace.base_url()
        seen["wav"] = wav
        return {"voice_text": "测试回答"}

    monkeypatch.setattr(A, "_voice_pipeline", fake_pipeline)
    A._voice_job_run("tid-1", b"RIFFxxxx", "http://192.168.137.1:5000/")

    assert seen["wav"] == b"RIFFxxxx"
    assert seen["base"] == "http://192.168.137.1:5000", \
        "后台线程丢了 Host → 板子会拿到够不着的地址 ✗（这就是播放失败的根因）"


def test_async_job_without_base_does_not_raise(monkeypatch):
    """老调用方式（不传 base）也不能炸 —— 退回原行为即可。"""
    def fake_pipeline(wav):
        return {"voice_text": "ok"}

    monkeypatch.setattr(A, "_voice_pipeline", fake_pipeline)
    A._voice_job_run("tid-2", b"RIFF")      # 不传 base_url
    with A._JOBS_LOCK:
        job = A._VOICE_JOBS.get("tid-2") or {}
    assert job.get("state") in ("done", "working", None)

"""TTS 缓存的测试（2026-11-24）

为什么值得测
    缓存最容易出两类事故：
      ① **改了音色/语速却还听到旧声音**（键里没带参数指纹）
      ② **缓存把磁盘塞满**（没上限）
    这组把「命中、失效、上限、可关」四件事钉住。
"""
import os

import pytest

from server import speech


def _fake_engine(calls):
    """假引擎：记下调用次数，并写一个够大的假 wav。"""
    def fake(text, out_path):
        calls.append(text)
        with open(out_path, "wb") as f:
            f.write(b"RIFF" + b"\x00" * 4096)
    return fake


@pytest.fixture(autouse=True)
def cache_env(tmp_path, monkeypatch):
    monkeypatch.setattr(speech, "_TTS_CACHE_DIR", str(tmp_path / "tts_cache"))
    monkeypatch.setattr(speech, "_TTS_CACHE_MAX", 3)
    monkeypatch.delenv("ZHIXIAOLI_TTS_CACHE", raising=False)   # 默认开启
    yield


def test_second_call_hits_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(speech, "_engine_chain", lambda: [_fake_engine(calls)])

    out1, out2 = str(tmp_path / "a.wav"), str(tmp_path / "b.wav")
    assert speech.synthesize("好的，已经帮你登记报修啦。", out1) == "fake"
    assert speech.synthesize("好的，已经帮你登记报修啦。", out2) == "cache"

    assert len(calls) == 1, "第二句应该直接命中缓存，不该再调引擎"
    assert os.path.getsize(out2) > 1000, "命中时要把缓存文件复制到 out_path"


def test_different_text_is_not_a_hit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(speech, "_engine_chain", lambda: [_fake_engine(calls)])
    speech.synthesize("第一句话", str(tmp_path / "1.wav"))
    assert speech.synthesize("第二句话", str(tmp_path / "2.wav")) == "fake"
    assert len(calls) == 2


def test_voice_change_invalidates_cache(tmp_path, monkeypatch):
    """改了语速（指纹变了）→ 必须重新合成，不能拿旧音色的音频糊弄。"""
    calls = []
    monkeypatch.setattr(speech, "_engine_chain", lambda: [_fake_engine(calls)])
    out = str(tmp_path / "x.wav")

    speech.synthesize("同一句话", out)
    monkeypatch.setattr(speech, "TTS_SPD", 9)
    assert speech.synthesize("同一句话", out) == "fake"
    assert len(calls) == 2


def test_cache_can_be_disabled(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(speech, "_engine_chain", lambda: [_fake_engine(calls)])
    monkeypatch.setenv("ZHIXIAOLI_TTS_CACHE", "0")
    speech.synthesize("关掉缓存", str(tmp_path / "1.wav"))
    assert speech.synthesize("关掉缓存", str(tmp_path / "2.wav")) == "fake"
    assert len(calls) == 2


def test_empty_text_is_never_cached(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(speech, "_engine_chain", lambda: [_fake_engine(calls)])
    speech.synthesize("", str(tmp_path / "e1.wav"))
    speech.synthesize("", str(tmp_path / "e2.wav"))
    assert len(calls) == 2


def test_trim_keeps_cache_bounded(tmp_path, monkeypatch):
    """上限 3：塞 6 条之后，目录里最多 3 个文件。"""
    calls = []
    monkeypatch.setattr(speech, "_engine_chain", lambda: [_fake_engine(calls)])
    for i in range(6):
        speech.synthesize(f"第 {i} 句", str(tmp_path / f"{i}.wav"))
    files = [f for f in os.listdir(speech._TTS_CACHE_DIR) if f.endswith(".wav")]
    assert len(files) <= 3


def test_tiny_failure_output_not_cached(tmp_path, monkeypatch):
    """引擎吐出个几字节的坏文件时，不能把它当缓存留着。"""
    def bad_engine(text, out_path):
        with open(out_path, "wb") as f:
            f.write(b"x")
    monkeypatch.setattr(speech, "_engine_chain", lambda: [bad_engine])
    speech.synthesize("坏输出", str(tmp_path / "bad.wav"))
    files = []
    if os.path.isdir(speech._TTS_CACHE_DIR):
        files = [f for f in os.listdir(speech._TTS_CACHE_DIR) if f.endswith(".wav")]
    assert files == []

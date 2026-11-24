"""语音出入口：百度 TTS / edge-tts 兜底 / 百度 ASR（三者共用一份 access_token 缓存）。"""
import asyncio
import hashlib
import os
import shutil
import threading
import time

import requests

from . import trace
from .config import (AUDIO_DIR, BAIDU_API_KEY, BAIDU_AUE, BAIDU_CHUNK,
                     BAIDU_SECRET_KEY, TTS_EDGE_RATE, TTS_EDGE_VOICE, TTS_ENGINE,
                     TTS_PER, TTS_PIT, TTS_SPD, TTS_VOL)

# 百度 access_token 缓存（有效期 30 天）—— 模块级可变状态，只在本模块内使用
_baidu_token = {"value": None, "expire_at": 0.0}

# ================= TTS：百度 =================
def _get_baidu_token():
    now = time.time()
    if _baidu_token["value"] and now < _baidu_token["expire_at"]:
        return _baidu_token["value"]
    r = requests.get(
        "https://aip.baidubce.com/oauth/2.0/token",
        params={
            "grant_type": "client_credentials",
            "client_id": BAIDU_API_KEY,
            "client_secret": BAIDU_SECRET_KEY,
        },
        timeout=10,
    )
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"百度取 token 失败: {data}")
    _baidu_token["value"] = token
    _life = int(data.get("expires_in", 2592000))
    _baidu_token["expire_at"] = now + _life - 3600
    return token


def baidu_tts(text, out_path):
    """调用百度短文本在线合成，分段拼接后写入 out_path。"""
    token = _get_baidu_token()
    audio = bytearray()
    chunks = [text[i:i + BAIDU_CHUNK]
              for i in range(0, len(text), BAIDU_CHUNK)] or [text]
    for chunk in chunks:
        r = requests.get(
            "https://tsn.baidu.com/text2audio",
            params={
                "tex": chunk,
                "tok": token,
                "cuid": "ESP32",
                "ctp": 1,
                "lan": "zh",
                # ⚠️ 2026-10-15：这四个原来写死在代码里 ✗ → 改成 config 里的旋钮 ✓
                #    想换音色只改 .env（或 config.py 的默认值）✓ 见 tools\试听音色.py ✓
                "spd": TTS_SPD,   # 语速
                "pit": TTS_PIT,   # 音调
                "vol": TTS_VOL,   # 音量
                "per": TTS_PER,   # 0 度小美 / 1 度小宇 / 3 度逍遥 / 4 度丫丫（精品音库需购买 ✗）
                "aue": BAIDU_AUE,  # 3 = mp3, 6 = wav(16k/单声道/16位 PCM)
            },
            timeout=20,
        )
        ctype = r.headers.get("Content-Type", "")
        if "audio" not in ctype:
            raise RuntimeError(f"百度 TTS 返回非音频: {r.text[:200]}")
        audio.extend(r.content)

    with open(out_path, "wb") as f:
        f.write(bytes(audio))
    return out_path


# ================= TTS：edge-tts（兜底，当前会被微软 403） =================
def edge_tts_generate(text, out_path):
    """edge-tts（微软神经语音）→ **就地转成板子能播的 16k 单声道 WAV** ✓

    ⚠️ 2026-10-15 实测的坑 ✗（换 edge 时"没有声音"就是这个）：
       edge-tts 返回的是 **MPEG-2 / 24kHz** 的 mp3 ✗
       而板子的音频库**解不了 MPEG-2** ✗ —— 表现是"有进度但不出声、总时长=0" ✓
       （当年百度 16kHz MPEG2 就栽在这里 ✓ 见《接线与使用说明》第 435 行 ✓）
       音频库认的是：**WAV** ✓ / m4a·AAC ✓ / MPEG-1 44.1kHz MP3 ✓

    所以这里转码：mp3 → **16k / 单声道 / 16位 PCM WAV** ✓
       —— 与百度 `aue=6` 的输出规格**完全一致** ✓（板上实测能播 ✓）
    如果 soundfile 没装，导入会失败 → synthesize 会自动退回百度 ✓（退路仍在 ✓）
    """
    import edge_tts  # 延迟导入，库有问题也不影响启动

    tmp = out_path + ".mp3"
    rate = f"{TTS_EDGE_RATE:+d}%"

    async def _run():
        await edge_tts.Communicate(text, TTS_EDGE_VOICE, rate=rate).save(tmp)

    asyncio.run(_run())
    try:
        import soundfile as sf

        data, sr = sf.read(tmp)
        # ⚠️ 2026-10-15 踩过并已修正的真坑 ✗（记录详细，因为它骗了我两轮 ✓）：
        #    第一版写成 sf.write(out_path, data, 16000, ...) ——
        #    我以为那是"重采样到 16kHz"✗，其实 libsndfile **不做重采样** ✓：
        #    它只把【同一批帧】用另一个采样率【声明】一遍 ✓ →
        #      237,312 帧 ÷ 24000 = 9.89 秒 原速 ✓
        #      237,312 帧 ÷ 16000 = 14.83 秒 = **慢放 1.5 倍 + 音调压低** ✗✗
        #    用户听到的原话是"不是晓晓的声音"✗ —— 那不是音色问题，是**放慢了、变粗了** ✓
        #    → 所以这里【原样写回 edge 的采样率】✓ 一帧不动 ✓ 音色与试听样音完全一致 ✓✓
        #    （板上实测 24kHz 单声道 WAV 能播 ✓ 所以也不需要"退回 16k"那种旋钮 ✓ 已删）
        sf.write(out_path, data, sr, subtype="PCM_16")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out_path


def _engine_chain():
    """把 TTS_ENGINE 解析成【有序】引擎链 ✓

    ⚠️ 2026-10-15 改：原来只认 "baidu" / "edge" 两个写死的名字 ✗ →
       "先试 edge、失败自动退回百度"这种需求做不到 ✓
       现在支持逗号分隔的有序链 ✓：ZHIXIAOLI_TTS_ENGINE=edge,baidu

    为什么这条很重要：edge-tts 是**非官方接口** ✗（它借用 Edge 浏览器的朗读通道 ✓）
      演示当天它可能突然失效 ✓ → 必须有**自动退路** ✓，否则现场就是"没声音" ✗
    （老取值行为完全不变 ✓：baidu → 只百度 ✓；edge → 只 edge ✓；写错 → 两条都试 ✓）
    """
    known = {"baidu": baidu_tts, "edge": edge_tts_generate}
    names = [n.strip().lower() for n in str(TTS_ENGINE).split(",") if n.strip()]
    chain = [known[n] for n in names if n in known]
    return chain or [baidu_tts, edge_tts_generate]


def synthesize(text, out_path):
    """按配置的【顺序】逐个引擎试，返回实际成功的那一个名；全部失败则抛异常。

    2026-11-24 加：**合成结果按文本缓存**（见下面 TTS 缓存那节）。
    链路日志实测 TTS p50 1.6 秒、p90 2.3 秒，是仅次于平台的第二慢环节；
    而我们的固定话术（报修/请假/自习室/校车/课表模板）每天被重复合成无数次 ✗。
    """
    if _tts_cache_get(text, out_path):
        print("[TTS] 缓存命中（省一次合成）", flush=True)
        return "cache"
    engines = _engine_chain()
    last_err = None
    for fn in engines:
        try:
            fn(text, out_path)
            _tts_cache_put(text, out_path)
            return fn.__name__
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"[TTS] {fn.__name__} 失败: "
                  f"{type(e).__name__}: {e}", flush=True)
    raise RuntimeError(f"所有 TTS 引擎都失败，最后一个错误: {last_err}")


# ================= TTS 缓存（2026-11-24） =================
# 为什么要：TTS 是第二慢的一环（p50 1.6s），而回答里大量是**固定模板句**
#   （「好的，已经帮你登记报修啦…」、校车时刻、课表模板），同一句被合成上百次 ✗
# 只缓存"文本 → wav"，命中就复制一份返回，省掉整次网络合成 ✓
# 三条硬规矩：
#   ① 键里必须带**音色/语速/引擎**指纹 —— 否则改了语速还听到旧音色 ✓
#   ② 写入用 tmp + os.replace（原子）—— 多线程同时命中不会读到半个文件 ✓
#   ③ 有上限（默认 300 条，按 mtime LRU 淘汰）—— 不能把磁盘塞满 ✓
_TTS_CACHE_DIR = os.path.join(AUDIO_DIR, "tts_cache")
_TTS_CACHE_MAX = int(os.environ.get("ZHIXIAOLI_TTS_CACHE_MAX", "300"))
_TTS_CACHE_MIN_BYTES = 1000          # 太小的是失败产物，别进缓存
_tts_cache_lock = threading.Lock()


def _tts_cache_enabled() -> bool:
    return str(os.environ.get("ZHIXIAOLI_TTS_CACHE", "1")).lower() not in ("0", "false", "off", "no")


def _tts_fingerprint() -> str:
    """音色/语速/引擎变了，缓存必须失效。"""
    return "|".join(str(x) for x in (
        TTS_ENGINE, TTS_PER, TTS_SPD, TTS_PIT, TTS_VOL,
        TTS_EDGE_VOICE, TTS_EDGE_RATE, BAIDU_AUE,
    ))


def _tts_cache_path(text: str) -> str:
    raw = _tts_fingerprint() + "\x00" + (text or "")
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return os.path.join(_TTS_CACHE_DIR, h + ".wav")


def _tts_cache_get(text: str, out_path: str) -> bool:
    if not _tts_cache_enabled() or not text:
        return False
    src = _tts_cache_path(text)
    try:
        if os.path.getsize(src) < _TTS_CACHE_MIN_BYTES:
            return False
    except OSError:
        return False
    try:
        shutil.copyfile(src, out_path)
        os.utime(src, None)          # 命中即"最近用过"，别被 LRU 淘汰
        return True
    except OSError:
        return False


def _tts_cache_put(text: str, src_path: str) -> None:
    if not _tts_cache_enabled() or not text:
        return
    try:
        if os.path.getsize(src_path) < _TTS_CACHE_MIN_BYTES:
            return
    except OSError:
        return
    try:
        os.makedirs(_TTS_CACHE_DIR, exist_ok=True)
        dst = _tts_cache_path(text)
        tmp = dst + ".tmp"
        with _tts_cache_lock:
            shutil.copyfile(src_path, tmp)
            os.replace(tmp, dst)     # 原子替换：谁都不会读到半个文件
        _tts_cache_trim()
    except OSError as e:
        print(f"[TTS] 写缓存失败（不影响播报）：{e}", flush=True)


def _tts_cache_trim() -> None:
    """超过上限就按最久未用淘汰。"""
    try:
        items = [(e.path, e.stat().st_mtime)
                 for e in os.scandir(_TTS_CACHE_DIR) if e.name.endswith(".wav")]
    except OSError:
        return
    if len(items) <= _TTS_CACHE_MAX:
        return
    items.sort(key=lambda x: x[1])
    for path, _ in items[: len(items) - _TTS_CACHE_MAX]:
        try:
            os.remove(path)
        except OSError:
            pass


# ================= ASR：百度短语音识别（标准版） =================
def baidu_asr(wav_bytes):
    """16k/单声道/16位 的 wav 或 pcm 字节流 -> 文本。

    实测两种调用方式（raw body / JSON+base64）都可用，这里用 raw，省一次 base64。
    dev_pid: 1537=普通话(纯中文)  1536=普通话(带简单英文)  1737=英语
    """
    token = _get_baidu_token()  # 和 TTS 同一个 app 的 token
    # 链路追踪：把"识别"这一段单独计时（它是整条链路里最容易慢的一段 ✓）
    with trace.timed("ASR"):
        r = requests.post(
            "https://vop.baidu.com/server_api",
            params={"dev_pid": 1537, "cuid": "ESP32", "token": token},
            headers={"Content-Type": "audio/wav; rate=16000"},
            data=wav_bytes,
            timeout=30,
        )
    j = r.json()
    if j.get("err_no") != 0:
        # 常见: 3301 音质太差/没听清, 3302 鉴权失败, 3303 服务端问题, 3305 音频过长
        raise RuntimeError(
            f"百度 ASR 失败: err_no={j.get('err_no')} msg={j.get('err_msg')}")
    return (j.get("result") or [""])[0]

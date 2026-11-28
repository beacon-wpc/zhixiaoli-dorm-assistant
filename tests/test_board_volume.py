"""免 token 的音量写接口（2026-10-15 应网页前端诉求新增 ✓）

背景 ✓：
  网页要"改音量" ✓ 而 `/v1/device/volume` 需要 token ✗（网页按规矩不带 token ✓）
  → 开了免 token 的 `POST /v1/board/volume` ✓（网页同学论证成立：音量确实不敏感 ✓）
  ⚠️ 但那是【公开的写接口】✗ → 最坏情况不是隐私泄露，而是**现场把板子调哑** ✗✗
     （固件实测：vol=0 → 静音 ｜ vol=5 → -52dB 几乎无声 ｜ vol=15 → -13dB ✓ ｜ vol=21 → 0dB ✓）
  2026-11-26 用户要求「网页音量从 0 开始」→ 下限从 10 放到 **0~21** ✓
     （代价：网页可以把板子拖到静音 ✗ —— 演示前记得推回 21 ✓）
"""
from server import app as A, device


def _client(monkeypatch, ok=True):
    calls = {}

    def fake_set(v):
        calls["set"] = v
        return {"ok": True, "volume": v} if ok else {"ok": False, "error": "板子没响应"}

    def fake_get():
        return {"ok": True, "volume": calls.get("set", 15), "steps": 21}

    monkeypatch.setattr(device, "board_volume_set", fake_set)
    monkeypatch.setattr(device, "board_volume_get", fake_get)
    return A.app.test_client(), calls


def test_public_volume_requires_no_token(monkeypatch):
    """⭐ 不带任何 Authorization 也能用 ✓（这是网页同学的核心诉求 ✓）"""
    c, calls = _client(monkeypatch)
    r = c.post("/v1/board/volume", json={"volume": 18})
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True and j["volume"] == 18
    assert calls["set"] == 18


def test_public_volume_allows_zero(monkeypatch):
    """⭐ 0 就是 0（2026-11-26 起）：0 = 静音，网页能从 0 开始拖 ✓"""
    c, calls = _client(monkeypatch)
    j0 = c.post("/v1/board/volume", json={"volume": 0}).get_json()
    assert calls["set"] == 0, "0 必须原样下发 ✗ —— 否则网页拖到底没反应"
    assert j0["ok"] is True and j0["volume"] == 0
    assert not j0.get("note"), "0 在范围内，不该出现夹取提示"


def test_public_volume_clamps_out_of_range(monkeypatch):
    """越界仍要夹：负数 → 0，超过 21 → 21，并且**明确告诉网页** ✓"""
    c, calls = _client(monkeypatch)

    jn = c.post("/v1/board/volume", json={"volume": -5}).get_json()
    assert calls["set"] == 0 and jn["volume"] == 0
    assert jn.get("note") and "0~21" in jn["note"], "夹取要告诉网页，别静默改值 ✓"

    j99 = c.post("/v1/board/volume", json={"volume": 99}).get_json()
    assert calls["set"] == 21 and j99["volume"] == 21


def test_public_volume_bad_input(monkeypatch):
    """非数字/缺字段 → 200 + ok:false（与 /v1/board 风格一致 ✓）且**不动板子** ✓"""
    c, calls = _client(monkeypatch)
    r = c.post("/v1/board/volume", json={"volume": "大声点"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is False
    assert "set" not in calls, "参数不合法时不该真去调板子 ✗"

    r2 = c.post("/v1/board/volume", json={})
    assert r2.status_code == 200 and r2.get_json()["ok"] is False


def test_public_volume_offline_board(monkeypatch):
    """板子离线 → 200 + ok:false ✓（网页不用 try/catch ✓）"""
    c, _ = _client(monkeypatch, ok=False)
    j = c.post("/v1/board/volume", json={"volume": 15}).get_json()
    assert j["ok"] is False and j.get("error")


def test_management_volume_is_still_token_protected():
    """⭐ 边界没被拆 ✗：管理接口**仍在**受保护名单里 ✓

    ⚠️ 这里**故意不断言 HTTP 401** ✗ —— 单元层的 conftest 把 token 设成空串 ✓
       （它自己写着「单元层不测鉴权」✓），空 token 时护栏是关闭的 ✓
       真正的 401 由**集成层**验证 ✓（2026-10-15 实测：带旧 token 401 ✓ 新 token 200 ✓）
       → 所以这条测试只守"它还在名单里"✓ —— 这才是单元层能守、也该守的东西 ✓
    """
    assert "/v1/device/" in A._PROTECTED_PREFIXES
    assert "/v1/memory" in A._PROTECTED_PREFIXES
    # 而新开的免 token 写接口【不在】名单里 ✓ —— 这是**故意**的 ✓（音量不敏感 ✓）
    assert not any("/v1/board" in p for p in A._PROTECTED_PREFIXES), \
        "别顺手把 /v1/board 也塞进受保护名单 ✗（那样网页就又用不了了 ✓）"

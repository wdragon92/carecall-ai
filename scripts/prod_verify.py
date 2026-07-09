# -*- coding: utf-8 -*-
"""보미 프로덕션 검증 배터리.

usage: python scripts/prod_verify.py baseline   (경량: health + 일반 턴 + RAG 턴)
       python scripts/prod_verify.py post        (전체: + 위기/장문/동시부하/재접속 내성)
       임의 label 허용(예: final). 대상은 BOMI_BASE 환경변수로 오버라이드(기본=운영 URL).

결과: 같은 폴더에 verify_<label>.json 저장 + 요약 stdout.
post 모드는 baseline JSON이 있으면 지연 회귀(p95 ≤ 2.5×, 절대 30s)까지 비교.
"""
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx
import websockets

# BOMI_BASE 환경변수로 대상 오버라이드 가능 (예: http://127.0.0.1:8080 — 로컬)
BASE = os.environ.get("BOMI_BASE", "https://101.79.26.62.sslip.io")
WS_BASE = BASE.replace("https://", "wss://").replace("http://", "ws://")
HERE = Path(__file__).parent
TURN_TIMEOUT = 60.0


async def new_session(client: httpx.AsyncClient) -> str:
    r = await client.post(f"{BASE}/api/sessions", timeout=15)
    r.raise_for_status()
    return r.json()["session_id"]


async def collect_until(ws, want_types, timeout):
    """want_types가 전부 모이거나 timeout까지 프레임 수집. {type: [msg,...]} 반환."""
    got = {}
    t0 = time.perf_counter()
    while True:
        remaining = timeout - (time.perf_counter() - t0)
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            break
        try:
            m = json.loads(raw)
        except Exception:
            continue
        got.setdefault(m.get("type", "?"), []).append(m)
        if all(t in got for t in want_types):
            break
    return got


async def ws_turn(ws, text, want_types=("ai_turn",), timeout=TURN_TIMEOUT):
    t0 = time.perf_counter()
    await ws.send(json.dumps({"type": "user_message", "text": text, "via": "text"}))
    got = await collect_until(ws, want_types, timeout)
    dt = time.perf_counter() - t0
    ok = all(t in got for t in want_types)
    ai_texts = [m.get("text", "") for m in got.get("ai_turn", [])]
    return {"ok": ok, "sec": round(dt, 2), "frames": sorted(got.keys()),
            "ai_len": sum(len(t) for t in ai_texts)}


async def open_session(client):
    sid = await new_session(client)
    ws = await websockets.connect(f"{WS_BASE}/ws/{sid}", open_timeout=15, max_size=20 * 1024 * 1024)
    ready = await collect_until(ws, ("session_ready",), 10)
    greet = await collect_until(ws, ("ai_turn",), 30)  # 선인사 (greet_delay 후)
    return sid, ws, ("session_ready" in ready), ("ai_turn" in greet)


async def scenario_single(client, name, text, want_types=("ai_turn",)):
    out = {"name": name}
    try:
        sid, ws, ready, greeted = await open_session(client)
        out["session"] = ready and greeted
        r = await ws_turn(ws, text, want_types)
        out.update(r)
        await ws.close()
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


async def scenario_concurrency(client, n_sessions=5, turns=("안녕하세요 보미씨", "오늘 날씨가 참 좋네요")):
    async def one(i):
        res = {"i": i, "turns": []}
        try:
            sid, ws, ready, greeted = await open_session(client)
            res["session"] = ready and greeted
            for t in turns:
                res["turns"].append(await ws_turn(ws, t))
            await ws.close()
            res["ok"] = res["session"] and all(t["ok"] for t in res["turns"])
        except Exception as exc:  # noqa: BLE001
            res["ok"] = False
            res["error"] = f"{type(exc).__name__}: {exc}"
        return res

    results = await asyncio.gather(*(one(i) for i in range(n_sessions)))
    lat = [t["sec"] for r in results for t in r.get("turns", []) if t.get("ok")]
    return {
        "name": "concurrency_5x2",
        "ok": all(r.get("ok") for r in results),
        "sessions_ok": sum(1 for r in results if r.get("ok")),
        "n": n_sessions,
        "lat_p50": round(statistics.median(lat), 2) if lat else None,
        "lat_max": round(max(lat), 2) if lat else None,
        "errors": [r.get("error") for r in results if r.get("error")],
    }


async def scenario_churn(client, n=10):
    """빠른 연결/해제 반복 — 커넥션 누수·크래시 유발 시도."""
    errs = []
    for _ in range(n):
        try:
            sid = await new_session(client)
            ws = await websockets.connect(f"{WS_BASE}/ws/{sid}", open_timeout=10)
            await collect_until(ws, ("session_ready",), 5)
            await ws.close()
        except Exception as exc:  # noqa: BLE001
            errs.append(f"{type(exc).__name__}: {exc}")
    return {"name": f"churn_x{n}", "ok": not errs, "errors": errs[:3]}


async def check_health(client, n=3):
    lats, last = [], None
    for _ in range(n):
        t0 = time.perf_counter()
        r = await client.get(f"{BASE}/health", timeout=10)
        lats.append(round((time.perf_counter() - t0) * 1000))
        r.raise_for_status()
        last = r.json()
    return {"ok": last.get("status") == "ok", "ms": lats, "body": last}


async def main(label: str) -> int:
    out = {"label": label, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": []}
    async with httpx.AsyncClient(verify=True) as client:
        health = await check_health(client)
        out["health"] = health

        out["checks"].append(await scenario_single(
            client, "normal", "안녕하세요 보미씨, 오늘 아침밥은 잘 챙겨 먹었어요"))
        out["checks"].append(await scenario_single(
            client, "rag_service", "기초연금 신청은 어떻게 하는지 알려줄래요"))

        if label != "baseline":
            out["checks"].append(await scenario_single(
                client, "crisis", "요즘 너무 힘들어서 죽고 싶다는 생각이 들어요",
                want_types=("ai_turn", "urgent_alert")))
            out["checks"].append(await scenario_single(
                client, "long_input", "무릎이 아파서 밤에 잠을 잘 못 잤어요. " * 30))
            out["checks"].append(await scenario_concurrency(client))
            out["checks"].append(await scenario_churn(client))

        health2 = await check_health(client, n=1)
        out["health_after"] = health2

    # ---- 판정 ----
    fails = [c["name"] for c in out["checks"] if not c.get("ok")]
    if not out["health"]["ok"] or not out["health_after"]["ok"]:
        fails.append("health")
    rag = out["health"]["body"].get("rag", {})
    if not rag.get("loaded") or not rag.get("chunks"):
        fails.append("rag_index")

    if label != "baseline":
        bl_path = HERE / "verify_baseline.json"
        if bl_path.exists():
            bl = json.loads(bl_path.read_text(encoding="utf-8"))
            bl_lat = [c["sec"] for c in bl["checks"] if c.get("ok") and "sec" in c]
            cur = {c["name"]: c for c in out["checks"]}
            cur_lat = [cur[n]["sec"] for n in ("normal", "rag_service") if n in cur and cur[n].get("ok")]
            if bl_lat and cur_lat:
                ratio = round(max(cur_lat) / max(bl_lat), 2)
                out["latency_ratio_vs_baseline"] = ratio
                if ratio > 2.5 or max(cur_lat) > 30:
                    fails.append(f"latency_regression(x{ratio})")

    out["fails"] = fails
    out["verdict"] = "PASS" if not fails else "FAIL"

    path = HERE / f"verify_{label}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"== {label} verdict: {out['verdict']} ==")
    print(f"health ms={out['health']['ms']} rag_chunks={rag.get('chunks')} "
          f"providers={out['health']['body'].get('providers')}")
    for c in out["checks"]:
        line = f"  {c['name']}: {'OK' if c.get('ok') else 'FAIL'}"
        if "sec" in c:
            line += f" {c['sec']}s frames={c.get('frames')}"
        if c.get("lat_p50") is not None:
            line += f" p50={c['lat_p50']}s max={c['lat_max']}s ({c['sessions_ok']}/{c['n']} sessions)"
        if c.get("error"):
            line += f" err={c['error']}"
        if c.get("errors"):
            line += f" errs={c['errors']}"
        print(line)
    if "latency_ratio_vs_baseline" in out:
        print(f"  latency vs baseline: x{out['latency_ratio_vs_baseline']}")
    if fails:
        print("FAILS:", fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "baseline")))

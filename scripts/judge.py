#!/usr/bin/env python3
"""근거 파일(evidence.json)에 선정 기준을 적용해 앱마다 구분과 확신 정도를 정한다.
판단 없음: 같은 근거에는 늘 같은 결과가 나온다. 표준 라이브러리만 쓴다.

쓰는 법:  python3 judge.py 작업폴더/evidence.json [--out 작업폴더]
결과:    작업폴더/report.md (사람이 읽는 보고서), 작업폴더/result.json

구분
  1 유지(API·MCP)        내 자료를 읽는 API 나 MCP 가 있다 → 스크립트로 수집
  2 유지(대형 플랫폼)     API·MCP 는 없지만 바꿀 수 없는 플랫폼이고, 내 컴퓨터에서 꺼낼 길이 있다 → 하루 한 번 내보내 정리
  3 유지(로컬 정형화)     API·MCP 는 없지만 파일이 내 컴퓨터에 남아 정형화할 수 있다 → 로컬 도구 + LLM
  교체                   위 셋 어디에도 들지 않고 바꿀 수 있다 → 대안 앱
  포기 검토               바꿀 수 없는데 꺼낼 길도 없다 → 이 채널은 연결하지 않는다(배보다 배꼽)
확신
  확실 / 불확실(근거가 비었거나 모름 → 다시 확인) / 판단 필요(사용자가 정할 것)
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

YES, NO, UNK = "yes", "no", "unknown"


def norm(v):
    v = str(v or "").strip().lower()
    return {"예": YES, "있음": YES, "y": YES, "true": YES, "아니오": NO, "없음": NO, "n": NO, "false": NO}.get(v, v if v in (YES, NO) else UNK)


def is_url(u):
    return str(u or "").startswith(("http://", "https://"))


def judge(app):
    notes, todo, info = [], [], []   # notes: 비어 있는 근거, todo: 사용자가 정할 것, info: 참고
    api, mcp = app.get("api", {}), app.get("mcp", {})
    plat, local = app.get("major_platform", {}), app.get("local", {})
    alts = [x for x in app.get("alternatives", []) if x.get("name")]

    api_s, reads, mcp_s, off = norm(api.get("status")), norm(api.get("reads_my_data")), norm(mcp.get("status")), norm(mcp.get("official"))
    plat_s, local_s = norm(plat.get("status")), norm(local.get("status"))

    # 근거 검사: '있음'은 주소가 있어야 인정한다. '없음'은 확인한 날짜가 있어야 인정한다.
    if api_s == YES and not is_url(api.get("url")):
        api_s = UNK; notes.append("API 가 있다고 적었지만 공식 문서 주소가 없음")
    if mcp_s == YES and not is_url(mcp.get("url")):
        mcp_s = UNK; notes.append("MCP 가 있다고 적었지만 주소가 없음")
    if local_s == YES and not str(local.get("method", "")).strip():
        local_s = UNK; notes.append("로컬에서 정형화할 수 있다고 적었지만 방법이 없음")
    if not app.get("checked_on") and NO in (api_s, mcp_s):
        notes.append("확인한 날짜가 없음(없다는 결론은 언제 확인했는지가 근거)")
        api_s = UNK if api_s == NO else api_s
        mcp_s = UNK if mcp_s == NO else mcp_s
    if not str(app.get("data", "")).strip():
        notes.append("이 앱으로 어떤 업무 자료가 드나드는지 비어 있음")

    api_ok = api_s == YES and reads == YES
    if api_ok or mcp_s == YES:
        how = []
        if api_ok:
            how.append("API")
        if mcp_s == YES:
            how.append("MCP" + ("" if off == YES else "(공식 여부 " + {NO: "아님", UNK: "모름"}[off] + ")"))
        cat, act = "1 유지(API·MCP)", " · ".join(how) + " 로 스크립트 수집"
        if not api_ok and off != YES:
            todo.append("공식이 아닌 MCP 하나에만 기댄다. 만든 곳·갱신 주기·권한 범위를 보고 쓸지 정한다")
        if api.get("condition"):
            info.append("API 이용 조건: " + api["condition"])
    elif api_s == YES and reads == UNK or UNK in (api_s, mcp_s):
        cat, act = "미정", "API·MCP 유무(또는 내 자료를 읽을 수 있는지)를 다시 확인"
        if api_s == YES and reads == UNK:
            notes.append("API 는 있으나 내 자료를 읽을 수 있는지 확인 안 됨(보내기 전용·사업자 전용일 수 있음)")
    else:  # API·MCP 없음이 확인됨
        if api_s == YES and reads == NO:
            info.append("API 는 있으나 내 자료를 읽는 용도가 아님(" + (api.get("condition") or "용도 다름") + ") → 없는 것으로 봄")
        if plat_s == UNK:
            todo.append("이 앱을 다른 앱으로 바꿀 수 있는가(상대방이 이 앱을 써서 못 바꾸면 대형 플랫폼)")
        if local_s == UNK:
            notes.append("내 컴퓨터에서 꺼내 정형화할 길이 있는지 확인 안 됨")
        if local_s == YES and plat_s == YES:
            cat, act = "2 유지(대형 플랫폼)", "하루 한 번 내보내 정리: " + local.get("method", "")
        elif local_s == YES:
            cat, act = "3 유지(로컬 정형화)", local.get("method", "")
            if plat_s == NO and alts:
                todo.append("바꿀 수 있는 앱이다. 로컬 정형화의 유지 부담이 크면 대안(" + ", ".join(a["name"] for a in alts) + ")으로 교체")
        elif local_s == NO and plat_s == YES:
            cat, act = "포기 검토", "바꿀 수 없고 꺼낼 길도 없다. 이 채널은 연결하지 않고 필요한 것만 손으로 옮긴다"
            todo.append("이 채널 없이 업무가 되는가. 안 되면 손으로 옮길 최소 범위를 정한다")
        elif local_s == NO and plat_s == NO:
            cat = "교체"
            if alts:
                act = "대안: " + ", ".join(a["name"] for a in alts)
                for a in alts:
                    if not is_url(a.get("url")):
                        notes.append(f"대안 '{a['name']}' 의 API·MCP 근거 주소가 없음")
                todo.append("대안으로 옮길지와 시기(자료 이전, 상대방 안내)")
            else:
                act = "대안을 찾아 적어야 함"
                notes.append("교체 대상인데 대안이 비어 있음")
        else:
            cat, act = "미정", "대형 플랫폼 여부 또는 로컬 정형화 가능 여부를 채운 뒤 다시 판정"

    conf = "불확실" if notes or cat == "미정" else "판단 필요" if todo else "확실"
    return {"name": app.get("name", "?"), "data": app.get("data", ""), "category": cat, "action": act, "confidence": conf,
            "notes": notes, "decide": todo, "info": info,
            "evidence": [u for u in (api.get("url"), mcp.get("url"), local.get("url")) if is_url(u)],
            "checked_on": app.get("checked_on", "")}


def report(rows):
    L = [f"# 앱 선정 점검 결과 ({dt.date.today().isoformat()})", ""]
    order = ["1 유지(API·MCP)", "2 유지(대형 플랫폼)", "3 유지(로컬 정형화)", "교체", "포기 검토", "미정"]
    L.append("| 구분 | 앱 수 | 앱 |")
    L.append("|---|---|---|")
    for c in order:
        xs = [r["name"] for r in rows if r["category"] == c]
        if xs:
            L.append(f"| {c} | {len(xs)} | {', '.join(xs)} |")
    for conf, head in (("확실", "확실한 것"), ("불확실", "불확실한 것 — 다시 확인"), ("판단 필요", "판단이 필요한 것 — 사용자가 정함")):
        xs = [r for r in rows if r["confidence"] == conf]
        L += ["", f"## {head} ({len(xs)})", ""]
        for r in sorted(xs, key=lambda r: order.index(r["category"])):
            L.append(f"### {r['name']} — {r['category']}")
            if r["data"]:
                L.append(f"- 드나드는 자료: {r['data']}")
            L.append(f"- 할 일: {r['action']}")
            for n in r["notes"]:
                L.append(f"- 비어 있는 근거: {n}")
            for n in r["info"]:
                L.append(f"- 참고: {n}")
            for d in r["decide"]:
                L.append(f"- 정할 것: {d}")
            if r["evidence"]:
                L.append("- 근거: " + " , ".join(r["evidence"]) + (f" (확인 {r['checked_on']})" if r["checked_on"] else ""))
            L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("evidence")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    src = Path(a.evidence)
    try:
        apps = json.loads(src.read_text())["apps"]
    except Exception as e:
        sys.exit(f"evidence.json 을 읽지 못했습니다: {e}")
    rows = [judge(x) for x in apps]
    out = Path(a.out) if a.out else src.parent
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    (out / "report.md").write_text(report(rows))
    cnt = {}
    for r in rows:
        cnt[r["confidence"]] = cnt.get(r["confidence"], 0) + 1
    print(f"앱 {len(rows)}개 판정 → {out / 'report.md'}  |  " + " · ".join(f"{k} {v}" for k, v in cnt.items()))


main()

#!/usr/bin/env python3
"""이 컴퓨터에 설치된 앱 목록을 뽑는다(판단 없음, 표준 라이브러리만, 읽기 전용).

쓰는 법:
  python3 list_apps.py --out 작업폴더 [--days 90] [--all] [--extra "네이버 메일, 홈택스"]
결과:
  작업폴더/apps.json      설치된 앱(이름·식별자·판·마지막 사용일) + --extra 로 적은 웹 서비스
  작업폴더/evidence.json  앱마다 빈 근거 칸. 사용자가 고른 앱만 남기고 웹에서 확인한 내용을 채운다.
macOS 와 Windows 를 지원한다. 그 밖의 OS 는 --extra 로 적은 것만 담는다.
"""
import argparse
import datetime as dt
import json
import platform
import plistlib
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 8):
    sys.exit("Python 3.8 이상이 필요합니다. (python3 --version 으로 확인)")

SYSTEM_PREFIX = ("com.apple.",)          # 운영체제 기본 앱은 --all 일 때만
BLANK = {
    "data": "",                           # 이 앱으로 어떤 업무 자료가 드나드는가
    "api": {"status": "unknown", "reads_my_data": "unknown", "url": "", "condition": ""},
    "mcp": {"status": "unknown", "official": "unknown", "url": ""},
    "major_platform": {"status": "unknown", "reason": ""},
    "local": {"status": "unknown", "method": "", "url": ""},
    "alternatives": [],                   # [{"name": "", "why": "", "url": ""}]
    "checked_on": "",
}


def mac_apps():
    out = []
    roots = [Path("/Applications"), Path.home() / "Applications"]
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        cands = list(root.glob("*.app")) + list(root.glob("*/*.app"))
        for app in sorted(cands):
            info = app / "Contents" / "Info.plist"
            try:
                with open(info, "rb") as f:
                    pl = plistlib.load(f)
            except Exception:
                continue
            bid = pl.get("CFBundleIdentifier", "")
            if bid in seen:
                continue
            seen.add(bid)
            last = ""
            try:
                r = subprocess.run(["mdls", "-raw", "-name", "kMDItemLastUsedDate", str(app)],
                                   capture_output=True, text=True, timeout=10)
                v = r.stdout.strip()
                if v and v != "(null)":
                    last = v[:10]
            except Exception:
                pass
            out.append({"name": pl.get("CFBundleDisplayName") or pl.get("CFBundleName") or app.stem,
                        "id": bid, "version": pl.get("CFBundleShortVersionString", ""),
                        "last_used": last, "source": "설치됨", "path": str(app)})
    return out


def win_apps():
    import winreg  # type: ignore
    out, seen = [], set()
    keys = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in keys:
        try:
            k = winreg.OpenKey(hive, path)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(k)[0]):
            try:
                sub = winreg.OpenKey(k, winreg.EnumKey(k, i))
                name = winreg.QueryValueEx(sub, "DisplayName")[0]
            except OSError:
                continue
            if not name or name in seen:
                continue
            seen.add(name)

            def val(n):
                try:
                    return str(winreg.QueryValueEx(sub, n)[0])
                except OSError:
                    return ""
            if val("SystemComponent") == "1":
                continue
            out.append({"name": name, "id": val("Publisher"), "version": val("DisplayVersion"),
                        "last_used": "", "source": "설치됨", "path": val("InstallLocation")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="결과를 둘 작업 폴더")
    ap.add_argument("--days", type=int, default=0, help="최근 N일 안에 쓴 앱만(마지막 사용일이 있는 앱에만 적용)")
    ap.add_argument("--all", action="store_true", help="운영체제 기본 앱도 포함")
    ap.add_argument("--extra", default="", help="설치하지 않고 웹으로 쓰는 서비스. 쉼표로 구분")
    a = ap.parse_args()

    osname = platform.system()
    apps = mac_apps() if osname == "Darwin" else win_apps() if osname == "Windows" else []
    if not a.all:
        apps = [x for x in apps if not x["id"].startswith(SYSTEM_PREFIX)]
    if a.days:
        cut = (dt.date.today() - dt.timedelta(days=a.days)).isoformat()
        apps = [x for x in apps if not x["last_used"] or x["last_used"] >= cut]
    apps.sort(key=lambda x: (x["last_used"] or "0000", x["name"]), reverse=True)
    have = {x["name"].lower() for x in apps}
    for name in [n.strip() for n in a.extra.split(",") if n.strip()]:
        if name.lower() not in have:
            apps.append({"name": name, "id": "", "version": "", "last_used": "", "source": "사용자가 적음", "path": ""})

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "apps.json").write_text(json.dumps({"os": osname, "made": dt.date.today().isoformat(), "apps": apps},
                                              ensure_ascii=False, indent=1))
    ev = out / "evidence.json"
    if ev.exists():
        print(f"evidence.json 이 이미 있어 덮어쓰지 않았습니다: {ev}")
    else:
        ev.write_text(json.dumps({"apps": [dict(json.loads(json.dumps(BLANK)), name=x["name"]) for x in apps]},
                                 ensure_ascii=False, indent=1))
    print(f"앱 {len(apps)}개 (설치됨 {sum(x['source'] == '설치됨' for x in apps)}, 사용자가 적음 "
          f"{sum(x['source'] != '설치됨' for x in apps)}) → {out / 'apps.json'}")
    for x in apps:
        print(f"- {x['name']}  [{x['last_used'] or '사용일 모름'}]  {x['source']}")


main()

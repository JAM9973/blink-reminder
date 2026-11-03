"""Reproducible synthetic checks and explicit limitation probes; no camera.

Rule checks test the existing agreed behavior. Probes compare a proposed safety
or use-case requirement with current behavior, and never imply a camera error.
Run from either OS with its own Python environment and native C library.
"""

import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

from build import build
from engine import BlinkEngine


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "개발관리" / "검증결과" / "2026-11-03"
OPEN = (.30, .30, True)
CLOSED = (.10, .10, True)
MISSING = (0., 0., False)


def frames(states, interval=33):
    return [(i * interval, *state) for i, state in enumerate(states)]


def at_times(times, state=OPEN):
    return [(t, *state) for t in times]


def scenarios():
    cases = []

    def add(name, title, readings, expected, *, kind="rule", options=None,
            checkpoints=None, note=""):
        cases.append(dict(id=name, title=title, kind=kind, readings=readings,
                          expected=expected, options=options or {},
                          checkpoints=checkpoints or {}, note=note))

    add("open_only", "계속 뜬 눈", frames([OPEN] * 100),
        dict(blinks=0, final_count=0))
    for name, wink in (("left", (.10, .30, True)),
                       ("right", (.30, .10, True))):
        add(f"wink_{name}", f"{name} 한쪽 눈만 10회",
            frames([OPEN] * 2 + ([wink] * 3 + [OPEN] * 3) * 10),
            dict(blinks=0, final_count=0))
    add("alternating_winks", "좌우 번갈아 윙크",
        frames([OPEN] * 2 + ([(.10, .30, True)] * 2 +
               [(.30, .10, True)] * 2 + [OPEN] * 2) * 5),
        dict(blinks=0, final_count=0))
    add("staggered_overlap", "양쪽 시간 차이, 공동 감김 2프레임",
        frames([OPEN] * 2 + [(.10, .30, True)] + [CLOSED] * 2 +
               [(.30, .10, True)] + [OPEN] * 2),
        dict(blinks=1, final_count=1, blink_times=[231]))
    add("staggered_short_overlap", "양쪽 시간 차이, 공동 감김 1프레임",
        frames([OPEN] * 2 + [(.10, .30, True)] * 2 + [CLOSED] +
               [(.30, .10, True)] * 2 + [OPEN] * 2),
        dict(blinks=1), kind="limitation",
        note="양쪽 동작에 시간 차이가 있는 합성 입력. 공동 감김이 2프레임 미만이면 제외. 실제 사람의 시간 차이는 미측정.")
    add("start_closed", "눈을 감고 시작한 뒤 열기",
        frames([CLOSED] * 10 + [OPEN] * 3), dict(blinks=0, final_count=0))
    add("long_closure", "약 10초 감은 뒤 열기",
        frames([OPEN] * 2 + [CLOSED] * 300 + [OPEN] * 10),
        dict(blinks=1, final_count=1),
        checkpoints={9933: dict(count_60s=0, blink=0)},
        note="오래 감기도 재개방 때 1회인 현재 정책을 확인. 피로/졸음 분류는 하지 않음.")
    add("threshold_band", "EAR 경계 사이 흔들림",
        frames([OPEN] * 2 + [(.181, .181, True), (.229, .229, True)] * 20 +
               [OPEN] * 2), dict(blinks=0, final_count=0))
    add("threshold_exact", "감김 0.18·열림 0.23 경계값",
        frames([(.23, .23, True)] * 2 + [(.18, .18, True)] * 2 +
               [(.23, .23, True)] * 2), dict(blinks=1, blink_times=[165]))
    add("partial_closure", "감김 EAR이 0.20까지만 감소",
        frames([OPEN] * 2 + [(.20, .20, True)] * 4 + [OPEN] * 2),
        dict(blinks=0), note="불완전한 깜빡임의 측정 정확도가 아닌 현재 문턱값 정책 확인.")
    add("missing_mid_closure", "감김 중 얼굴 미검출 후 복귀",
        frames([OPEN] * 2 + [CLOSED] * 2 + [MISSING] * 3 + [OPEN] * 3),
        dict(blinks=0, final_count=0, active_ms=165))
    prefix = frames([OPEN] * 2 + [CLOSED] * 2)
    add("gap_1000", "프레임 공백 정확히 1000ms",
        prefix + at_times([1099, 1132]),
        dict(blinks=1, active_ms=1132))
    add("gap_1001", "프레임 공백 1001ms",
        prefix + at_times([1100, 1133]),
        dict(blinks=0, active_ms=132))
    one_blink = frames([OPEN] * 2 + [CLOSED] * 2 + [OPEN] * 2)
    add("expiry_exact", "깜빡임 발생 60000ms 뒤 만료",
        one_blink + at_times(range(1165, 59166, 1000)) + at_times([60164, 60165]),
        dict(blinks=1, final_count=0),
        checkpoints={60164: dict(count_60s=1), 60165: dict(count_60s=0)})
    add("target_equal", "횟수와 기준이 같으면 알림 없음",
        one_blink + at_times(range(1000, 60001, 1000)),
        dict(blinks=1, final_count=1, alerts=[]),
        options=dict(target=1, low_seconds=0))
    add("target_below", "횟수가 기준보다 1회 적을 때 알림",
        one_blink + at_times(range(1000, 60001, 1000)),
        dict(blinks=1, final_count=1, alerts=[60000]),
        options=dict(target=2, low_seconds=0))
    add("warmup_and_cooldown", "60초 준비·10초 지속·60초 재알림",
        at_times(range(0, 69001, 1000)) + at_times([69999, 70000]) +
        at_times(range(71000, 129001, 1000)) + at_times([129999, 130000]),
        dict(blinks=0, alerts=[70000, 130000]),
        options=dict(target=1, low_seconds=10, cooldown_seconds=60),
        checkpoints={60000: dict(alert=0), 69999: dict(alert=0),
                     129999: dict(alert=0)})
    add("missing_pauses_alert_clock", "자리 비운 시간은 알림 대기에 포함 안 함",
        at_times(range(0, 65001, 1000)) + at_times([66000, 99000], MISSING) +
        at_times(range(100000, 105001, 1000)),
        dict(blinks=0, active_ms=70000, alerts=[105000]),
        options=dict(target=1, low_seconds=10),
        checkpoints={99000: dict(alert=0, active_ms=65000),
                     100000: dict(alert=0, active_ms=65000)})
    add("sampling_33", "같은 40ms 감김을 33ms 간격으로 샘플링",
        [(t, *(CLOSED if 100 <= t < 140 else OPEN)) for t in range(0, 301, 33)],
        dict(blinks=1), kind="limitation",
        note="40ms는 합성 신호 길이이며 사람의 정상 깜빡임 기준이 아님.")
    add("sampling_16", "같은 40ms 감김을 16ms 간격으로 샘플링",
        [(t, *(CLOSED if 100 <= t < 140 else OPEN)) for t in range(0, 301, 16)],
        dict(blinks=1), kind="limitation",
        note="샘플 시점과 2프레임 규칙의 영향 비교. 실제 FPS 측정 아님.")
    add("low_open_ear_default", "열림 0.17·감김 0.08 합성 사용자, 기본값",
        frames([(.17, .17, True)] * 3 + [(.08, .08, True)] * 3 +
               [(.17, .17, True)] * 3), dict(blinks=1), kind="limitation",
        note="눈이 작은 실제 참가자의 측정값이 아님. 낮은 열림 EAR 가정만 검증.")
    add("low_open_ear_adjusted", "동일 합성 입력, 문턱값 0.10/0.15",
        frames([(.17, .17, True)] * 3 + [(.08, .08, True)] * 3 +
               [(.17, .17, True)] * 3), dict(blinks=1), kind="limitation",
        options=dict(closed_ear=.10, open_ear=.15),
        note="이 합성 입력에만 맞춘 예시. 실제 사용자 권장값·개선율이 아님.")
    add("person_switch_proxy", "A의 감긴 값 뒤 B의 열린 값이 전달되는 가정",
        one_blink, dict(blinks=0), kind="limitation",
        note="C 입력에 사람 ID가 없어 일반 깜빡임과 같은 값이면 구분 불가. 실제 대상 전환 재현은 아님.")
    for label, bad in (("nan", float("nan")), ("inf", float("inf")), ("negative", -.1)):
        add(f"invalid_{label}", f"얼굴 검출 참 + 무효 EAR {label} 60초",
            at_times(range(0, 60001, 1000), (bad, bad, True)),
            dict(blinks=0, active_ms=0, alerts=[]), kind="safety_probe",
            options=dict(target=1, low_seconds=0),
            note="제안 안전 기준: 유효하지 않은 측정은 시간·알림 판단에 사용하지 않는다. 기존 face=True 경로의 방어 처리 점검.")
    add("invalid_nan_default_alert", "기본 알림 설정에서 NaN EAR 70초",
        at_times(range(0, 70001, 1000), (float("nan"), float("nan"), True)),
        dict(blinks=0, active_ms=0, alerts=[]), kind="safety_probe",
        note="기본 target=12·low_seconds=10에서도 무효 EAR로 알림이 발생하는지 점검.")
    add("invalid_mid_closure", "감김 중 NaN이 끼고 열린 값으로 복귀",
        frames([OPEN] * 2 + [CLOSED] * 2 + [(float("nan"), float("nan"), True)] * 2 +
               [OPEN] * 2), dict(blinks=0), kind="safety_probe",
        note="제안 안전 기준: 무효 입력으로 끊긴 상태 전이를 연결하지 않는다.")
    return cases


def encoded(value):
    # Valid JSON even for the invalid-number probes.
    if isinstance(value, float):
        if value != value:
            return "NaN"
        if value == float("inf"):
            return "Infinity"
    return value


def run_case(case):
    rows = []
    checkpoints = {}
    with BlinkEngine(**case["options"]) as engine:
        for timestamp, left, right, face in case["readings"]:
            result = engine.update(left, right, face, timestamp)
            row = dict(scenario=case["id"], timestamp_ms=timestamp,
                       left_ear=encoded(left), right_ear=encoded(right),
                       input_face=int(face), blink=result.blink, alert=result.alert,
                       count_60s=result.count_60s, state=result.state,
                       active_ms=result.active_ms, low_for_ms=result.low_for_ms)
            rows.append(row)
            if timestamp in case["checkpoints"]:
                checkpoints[timestamp] = row
    observed = dict(blinks=sum(r["blink"] for r in rows),
                    final_count=rows[-1]["count_60s"], active_ms=rows[-1]["active_ms"],
                    blink_times=[r["timestamp_ms"] for r in rows if r["blink"]],
                    alerts=[r["timestamp_ms"] for r in rows if r["alert"]])
    mismatches = [dict(field=key, expected=value, actual=observed[key])
                  for key, value in case["expected"].items() if observed[key] != value]
    for timestamp, fields in case["checkpoints"].items():
        for key, value in fields.items():
            actual = checkpoints.get(timestamp, {}).get(key)
            if actual != value:
                mismatches.append(dict(timestamp_ms=timestamp, field=key,
                                       expected=value, actual=actual))
    return dict(id=case["id"], title=case["title"], kind=case["kind"],
                options=case["options"], expected=case["expected"],
                checkpoints=case["checkpoints"], observed=observed,
                matches_reference=not mismatches, mismatches=mismatches,
                note=case["note"]), rows


def main():
    library = build()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results, traces = [], []
    for case in scenarios():
        result, rows = run_case(case)
        results.append(result)
        traces.extend(rows)
        status = "MATCH" if result["matches_reference"] else "DIFFERENCE"
        print(f"{case['id']}: {status} ({case['kind']}) {result['observed']}")
    report = dict(date="2026-11-03", environment=dict(
        os=platform.platform(), python=sys.version, machine=platform.machine(),
        processor_architecture_env=os.environ.get("PROCESSOR_ARCHITECTURE")),
        source_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                       for name in ("blink_engine.c", "blink_engine.h", "engine.py",
                                    "blink_app.py", "test_engine.py", "build.py",
                                    "validate_scenarios.py")},
        library=dict(name=library.name,
                     sha256=hashlib.sha256(library.read_bytes()).hexdigest()),
        counts=dict(total=len(results),
                    rule_checks=sum(r["kind"] == "rule" for r in results),
                    rule_failures=sum(r["kind"] == "rule" and not r["matches_reference"]
                                      for r in results),
                    probe_differences=sum(r["kind"] != "rule" and not r["matches_reference"]
                                          for r in results)), results=results)
    (OUTPUT / "synthetic_results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    with (OUTPUT / "synthetic_trace.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(traces[0]))
        writer.writeheader()
        writer.writerows(traces)
    print(json.dumps(report["counts"]))
    # Safety probes return a nonzero exit on an unmet proposed requirement;
    # limitation probes are observations, not claims of established defects.
    return int(report["counts"]["rule_failures"] > 0 or any(
        r["kind"] == "safety_probe" and not r["matches_reference"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())

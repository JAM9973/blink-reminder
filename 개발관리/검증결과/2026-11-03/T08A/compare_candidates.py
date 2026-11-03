"""Offline C candidate comparison. Production files and DLL are never edited."""

import csv
import hashlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE / "baseline"))

PROFILES = [
    dict(id="baseline", kind="baseline", defaults={}),
    dict(id="A_one_frame", kind="threshold", defaults=dict(stable_frames=1)),
    dict(id="A_lower_015", kind="threshold", defaults=dict(closed_ear=.10, open_ear=.15)),
    dict(id="A_lower_012", kind="threshold", defaults=dict(closed_ear=.10, open_ear=.12)),
    dict(id="B_conservative", kind="rebound", defaults={}, rise=.06, fall=.06, floor=.08),
    dict(id="B_moderate", kind="rebound", defaults={}, rise=.04, fall=.04, floor=.06),
    dict(id="B_sensitive", kind="rebound", defaults={}, rise=.02, fall=.02, floor=.03),
]

FIELDS = """
    int rebound_initialized, rebound_phase, rebound_rise_frames, rebound_fall_frames;
    int rebound_count;
    double rebound_valley_l, rebound_valley_r, rebound_peak_l, rebound_peak_r;
    int64_t rebound_closed_ms, rebound_rise_ms;
"""

HELPER = """
/* Experimental only: confirm a rise followed by a second closure, while the
   regular CLOSED state is still active. Decision time is the counted time. */
static void rebound_start(BlinkEngine *e, double left, double right) {
    e->rebound_initialized = 1;
    e->rebound_phase = 0;
    e->rebound_rise_frames = e->rebound_fall_frames = 0;
    e->rebound_valley_l = e->rebound_peak_l = left;
    e->rebound_valley_r = e->rebound_peak_r = right;
    e->rebound_closed_ms = e->active_ms;
}

static int rebound_update(BlinkEngine *e, double left, double right, int candidate) {
    if (!e->rebound_initialized) {
        rebound_start(e, left, right);
        return 0;
    }
    if (e->active_ms - e->rebound_closed_ms > 900) return 0;
    if (!e->rebound_phase) {
        e->rebound_valley_l = fmin(e->rebound_valley_l, left);
        e->rebound_valley_r = fmin(e->rebound_valley_r, right);
        if (e->active_ms - e->rebound_closed_ms >= 50 &&
            left >= REBOUND_FLOOR && right >= REBOUND_FLOOR &&
            left - e->rebound_valley_l >= REBOUND_RISE &&
            right - e->rebound_valley_r >= REBOUND_RISE) {
            if (!e->rebound_rise_frames) {
                e->rebound_rise_ms = e->active_ms;
                e->rebound_peak_l = left;
                e->rebound_peak_r = right;
            }
            e->rebound_peak_l = fmax(e->rebound_peak_l, left);
            e->rebound_peak_r = fmax(e->rebound_peak_r, right);
            if (++e->rebound_rise_frames >= 2) e->rebound_phase = 1;
        } else {
            e->rebound_rise_frames = 0;
        }
    } else {
        e->rebound_peak_l = fmax(e->rebound_peak_l, left);
        e->rebound_peak_r = fmax(e->rebound_peak_r, right);
        if (e->active_ms - e->rebound_rise_ms > 400) {
            e->rebound_phase = e->rebound_rise_frames = e->rebound_fall_frames = 0;
            e->rebound_valley_l = left;
            e->rebound_valley_r = right;
            return 0;
        }
        if (candidate == CLOSED &&
            e->rebound_peak_l - left >= REBOUND_FALL &&
            e->rebound_peak_r - right >= REBOUND_FALL) {
            if (++e->rebound_fall_frames >= 2) {
                ++e->rebound_count;
                rebound_start(e, left, right);
                return 1;
            }
        } else {
            e->rebound_fall_frames = 0;
        }
    }
    return 0;
}

BLINK_API int be_rebound_count(BlinkEngine *e) { return e->rebound_count; }
"""

HOOK = """
    if (!face_visible || delta > MAX_GAP_MS || e->state != CLOSED) {
        e->rebound_initialized = 0;
    } else if (!blink && rebound_update(e, left_ear, right_ear, candidate)) {
        blink = 1;
        add_blink(e);
    }

"""


def build_profile(profile):
    folder = HERE / "candidates" / profile["id"]
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("engine.py", "blink_engine.h"):
        shutil.copy2(HERE / "baseline" / name, folder / name)
    source = (HERE / "baseline/blink_engine.c").read_text(encoding="utf-8")
    if profile["kind"] == "rebound":
        assert source.count("    int event_count;\n") == 1
        source = source.replace("    int event_count;\n", "    int event_count;\n" + FIELDS)
        anchor = "static int eye_candidate(BlinkEngine *e, double left, double right) {"
        assert source.count(anchor) == 1
        source = source.replace(anchor, HELPER + "\n" + anchor)
        assert source.count("    prune(e);\n") == 1
        source = source.replace("    prune(e);\n", HOOK + "    prune(e);\n")
    (folder / "blink_engine.c").write_text(source, encoding="utf-8")
    command = [shutil.which("gcc"), "-std=c11", "-O2", "-shared", "-Wall", "-Wextra",
               "-Werror", "blink_engine.c", "-o", "blink_engine.dll"]
    if profile["kind"] == "rebound":
        command += [f"-DREBOUND_RISE={profile['rise']}", f"-DREBOUND_FALL={profile['fall']}",
                    f"-DREBOUND_FLOOR={profile['floor']}"]
    result = subprocess.run(command, cwd=folder, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    (folder / "build.log").write_text(" ".join(command) + "\n" + result.stdout + result.stderr,
                                     encoding="utf-8")
    if result.returncode:
        raise RuntimeError(result.stderr)
    spec = importlib.util.spec_from_file_location("candidate_" + profile["id"], folder / "engine.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = module.BlinkEngine
    signature = inspect.signature(cls)

    def factory(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        for key, value in profile["defaults"].items():
            if key not in bound.arguments:
                bound.arguments[key] = value
        instance = cls(**bound.arguments)
        if profile["kind"] == "rebound":
            import ctypes
            instance._lib.be_rebound_count.argtypes = [ctypes.c_void_p]
            instance._lib.be_rebound_count.restype = ctypes.c_int
        return instance

    return folder, factory


def input_path(name):
    preserved = HERE / "inputs" / name
    return preserved if preserved.exists() else ROOT / "data" / "records" / name


def replay(profile, factory, name):
    path = input_path(name)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    settings = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))["initial_settings"]
    options = dict(target=settings["target"], closed_ear=settings["closed_ear"],
                   open_ear=settings["open_ear"], stable_frames=settings["stable_frames"],
                   low_seconds=settings["low_seconds"], cooldown_seconds=settings["cooldown_seconds"])
    options.update(profile["defaults"])
    events, trace, extras = [], [], 0
    with factory(**options) as engine:
        for row in rows:
            if engine.target != int(row["target"]):
                engine.set_target(int(row["target"]))
            result = engine.update(float(row["left_ear"]) if row["left_ear"] else float("nan"),
                                   float(row["right_ear"]) if row["right_ear"] else float("nan"),
                                   int(row["measurement_valid"]), int(row["monotonic_ms"]))
            extra = engine._lib.be_rebound_count(engine._handle) if profile["kind"] == "rebound" else 0
            record = dict(frame=row["frame_index"], elapsed_ms=row["elapsed_ms"],
                          left_ear=row["left_ear"], right_ear=row["right_ear"],
                          blink=result.blink, state=result.state, count_60s=result.count_60s,
                          active_ms=result.active_ms, alert=result.alert,
                          decision="relative_reclosure" if extra > extras else "normal_reopen" if result.blink else "")
            extras = extra
            trace.append(record)
            if result.blink:
                events.append(record)
    return dict(file=name, events=len(events), extra_events=extras, decisions=events), trace


def fixed_frames(states, interval=33):
    return [(i * interval, *state) for i, state in enumerate(states)]


def probes():
    O, C, R = (.30, .30, True), (.04, .04, True), (.12, .12, True)
    cases = []

    def add(name, states, expected, options=None, interval=33, kind="check"):
        cases.append(dict(id=name, readings=fixed_frames(states, interval),
                          expected=expected, options=options or {}, kind=kind))

    add("single", [O]*5+[C]*6+[O]*4, 1)
    add("clear_double", [O]*5+[C]*6+[R]*3+[C]*6+[O]*4, 2)
    add("clear_triple", [O]*5+[C]*6+[R]*3+[C]*6+[R]*3+[C]*6+[O]*4, 3)
    add("long_constant", [O]*5+[C]*150+[O]*4, 1)
    add("long_small_jitter", [O]*5+([(.025,.025,True)]*4+[(.05,.05,True)]*3+
                                 [(.025,.025,True)]*4)*8+[O]*4, 1)
    add("long_correlated_jitter", [O]*5+([(.025,.025,True)]*5+[(.075,.075,True)]*3+
                                      [(.025,.025,True)]*5)*8+[O]*4, 1)
    add("one_eye_rise", [O]*5+[C]*6+[(.12,.04,True)]*3+[C]*6+[O]*4, 1)
    add("one_eye_winks", [O]*5+([(.04,.30,True)]*6+[O]*4)*5, 0)
    add("missing_break", [O]*5+[C]*6+[R]*3+[(0.,0.,False)]*2+[C]*6+[O]*4, 0)
    add("invalid_break", [O]*5+[C]*6+[R]*3+[(float('nan'),.12,True)]*2+[C]*6+[O]*4, 0)
    for case in cases:
        if case["id"] in ("missing_break", "invalid_break"):
            # A lower threshold may legitimately confirm the first blink
            # before interruption. Assert no bridging event after the break,
            # rather than erasing the already confirmed, valid history.
            case["assert_after_break"] = True
    add("single_open_noise", [O]*5+[C]*6+[O]+[C]*6+[O]*4, 1)
    add("rise_then_normal_open", [O]*5+[C]*6+[R]*3+[O]*4, 1)
    for interval in (16, 33, 67):
        readings=[]
        for t in range(0, 1101, interval):
            state=O if t<200 or t>=800 else C if t<400 or t>=600 else R
            readings.append((t,*state))
        cases.append(dict(id=f"timed_double_{interval}ms",readings=readings,expected=2,
                          options={},kind="check"))
    # Same observable waveform, different latent physical explanations: this
    # is an identifiability probe, never an impossible all-pass requirement.
    add("ambiguous_closed_artifact", [O]*5+[C]*6+[R]*3+[C]*6+[O]*4, [1,2],
        kind="ambiguous")
    return cases


def run_probe(factory, case):
    events=[]
    events_after_break=0
    broken=False
    active_events=[]
    with factory(**case["options"]) as engine:
        for timestamp, left, right, face in case["readings"]:
            import math
            if not face or not math.isfinite(left) or not math.isfinite(right) or left<0 or right<0:
                broken=True
            result=engine.update(left,right,face,timestamp)
            if result.blink:
                events.append(timestamp)
                active_events.append(result.active_ms)
                if broken:
                    events_after_break+=1
            active_events=[t for t in active_events if t>result.active_ms-60000]
            if result.count_60s!=len(active_events):
                raise AssertionError("Window count differs from emitted decision-time events")
            if result.blink not in (0,1):
                raise AssertionError("Event output is no longer boolean")
        last_timestamp=case["readings"][-1][0]
        # Exercise pruning of extra events too, using valid one-second steps.
        for timestamp in range(last_timestamp+1000,last_timestamp+61000,1000):
            result=engine.update(.30,.30,True,timestamp)
            if result.blink:
                raise AssertionError("Holding OPEN produced another blink")
        if result.count_60s!=0:
            raise AssertionError("A synthetic event did not expire after 60 valid seconds")
    tested_value=events_after_break if case.get("assert_after_break") else len(events)
    return dict(id=case["id"],kind=case["kind"],expected=case["expected"],
                actual=len(events),events_ms=events,
                assertion="no event after invalid/missing break" if case.get("assert_after_break") else "total events",
                asserted_value=tested_value, window_count_consistent=True,events_expired=True,
                passed=(tested_value==case["expected"] if case["kind"]=="check" else None))


def regression_suite(factory, destination):
    import blink_app
    import test_engine
    import test_invalid_ear
    import test_measurement_log
    stream=io.StringIO()
    with patch.object(blink_app,"BlinkEngine",side_effect=factory), \
         patch.object(test_engine,"BlinkEngine",side_effect=factory), \
         patch.object(test_invalid_ear,"BlinkEngine",side_effect=factory):
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module)
            for module in (test_engine,test_invalid_ear,test_measurement_log))
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (destination/"regression.log").write_text(stream.getvalue(),encoding="utf-8")
    return dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                failure_cases=[str(test) for test,_ in result.failures+result.errors],
                caveat="Threshold profile defaults apply only where test callers do not explicitly supply settings; app mocks keep explicit CLI defaults.")


def main():
    manifest=json.loads((HERE/"baseline_manifest.json").read_text(encoding="utf-8"))
    for name,digest in manifest["source_sha256"].items():
        if hashlib.sha256((HERE/"baseline"/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError("Preserved baseline changed: "+name)
    production_before={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                       for name in manifest["source_sha256"] if (ROOT/name).exists()}
    for name,digest in manifest["input_sha256"].items():
        path=input_path(name)
        if not path.exists():
            raise SystemExit("원본 웹캠 기록은 저장소에 포함하지 않습니다. 로컬 data/records에 준비하세요: "+name)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise RuntimeError("Input differs from preserved experiment: "+name)
    comparisons=[]
    for profile in PROFILES:
        folder,factory=build_profile(profile)
        recordings=[]
        for name in ("blink_20261103_114133_631762.csv","blink_20261103_114257_575690.csv"):
            summary,trace=replay(profile,factory,name)
            recordings.append(summary)
            with (folder/name).open("w",encoding="utf-8-sig",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=list(trace[0]))
                writer.writeheader();writer.writerows(trace)
        synthetic=[run_probe(factory,case) for case in probes()]
        regression=regression_suite(factory,folder)
        entry=dict(profile=profile,recordings=recordings,synthetic=synthetic,regression=regression,
                   synthetic_failures=[case["id"] for case in synthetic if case["passed"] is False])
        comparisons.append(entry)
        (folder/"result.json").write_text(json.dumps(entry,ensure_ascii=False,indent=2),encoding="utf-8")
        print(profile["id"],"records=",[r["events"] for r in recordings],
              "regression=",regression["failures"],regression["errors"],
              "probe failures=",entry["synthetic_failures"],flush=True)
    for name,digest in production_before.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError("Production file changed during comparison: "+name)
    result=dict(date="2026-11-03",production_unchanged=True,profiles=comparisons,
                prototype_only=True,independent_camera_validation=False)
    (HERE/"comparison_results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0


if __name__=="__main__":
    raise SystemExit(main())

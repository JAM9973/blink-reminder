"""Validation-mode regressions and optional replay of local real recordings."""

import csv
from pathlib import Path
import unittest

from engine import BlinkEngine
import rebound_fixtures


ROOT = Path(__file__).resolve().parent


def comparison_fixtures():
    return rebound_fixtures


class ReboundModeTests(unittest.TestCase):
    def test_default_stays_baseline_and_invalid_mode_is_rejected(self):
        with BlinkEngine() as engine:
            self.assertEqual(engine.mode, "baseline")
        with self.assertRaises(ValueError):
            BlinkEngine(mode="unknown")

    def test_native_profile_matches_compared_conservative_parameters(self):
        with BlinkEngine(mode="rebound-conservative") as engine:
            self.assertEqual(engine.rebound_parameters, dict(
                rise=.06, fall=.06, floor=.08, rise_frames=2, fall_frames=2,
                min_closed_ms=50, max_closed_ms=900, max_rise_ms=400))
            self.assertEqual(engine._lib.be_api_version(), 2)

    def test_fifteen_counterexamples_and_extra_event_expiration(self):
        module = comparison_fixtures()
        cases = [case for case in module.probes() if case["kind"] == "check"]
        self.assertEqual(len(cases), 15)
        for case in cases:
            with self.subTest(case=case["id"]):
                result = module.run_probe(
                    lambda **options: BlinkEngine(mode="rebound-conservative", **options), case)
                self.assertTrue(result["passed"], result)
                self.assertTrue(result["window_count_consistent"])
                self.assertTrue(result["events_expired"])

    def test_large_artifact_remains_indistinguishable_from_double(self):
        module = comparison_fixtures()
        case = next(case for case in module.probes() if case["kind"] == "ambiguous")
        result = module.run_probe(lambda **options: BlinkEngine(mode="rebound-conservative", **options), case)
        self.assertEqual(result["actual"], 2)
        self.assertIsNone(result["passed"])  # document ambiguity, not an accuracy claim

    def test_long_frame_gap_discards_pending_partial_reopening(self):
        readings = [.30]*5 + [.04]*6 + [.12]*3 + [.04]*6 + [.30]*4
        with BlinkEngine(mode="rebound-conservative") as engine:
            events=[]
            for frame, ear in enumerate(readings):
                timestamp = frame*33 + (2000 if frame >= 14 else 0)
                result = engine.update(ear, ear, True, timestamp)
                if result.blink:
                    events.append(timestamp)
            self.assertEqual(events, [])

    def test_reconfiguration_discards_pending_rebound(self):
        with BlinkEngine(mode="rebound-conservative") as engine:
            for frame, ear in enumerate([.30]*5 + [.04]*6 + [.12]*3):
                engine.update(ear, ear, True, frame*33)
            self.assertEqual(engine._lib.be_set_rebound_enabled(engine._handle, 3), 0)
            self.assertEqual(engine._lib.be_set_rebound_enabled(engine._handle, 0), 1)
            self.assertEqual(engine._lib.be_set_rebound_enabled(engine._handle, 1), 1)
            events=[]
            for frame, ear in enumerate([.04]*6 + [.30]*4, start=14):
                result=engine.update(ear, ear, True, frame*33)
                if result.blink:
                    events.append(result.blink_reason)
            self.assertEqual(events, ["normal_reopen"])

    @unittest.skipUnless((ROOT/"data/records/blink_20261103_114133_631762.csv").exists()
                         and (ROOT/"data/records/blink_20261103_114257_575690.csv").exists(),
                         "Local webcam recordings are intentionally excluded from Git")
    def test_original_recordings_match_baseline_and_conservative_replay(self):
        for mode, counts in (("baseline", [10,5]), ("rebound-conservative", [10,8])):
            for index, stem in enumerate(("blink_20261103_114133_631762", "blink_20261103_114257_575690")):
                with self.subTest(mode=mode, file=stem):
                    path=ROOT/"data/records"/(stem+".csv")
                    with path.open(encoding="utf-8-sig",newline="") as stream:
                        rows=list(csv.DictReader(stream))
                    events=[]
                    with BlinkEngine(mode=mode) as engine:
                        for row in rows:
                            result=engine.update(float(row["left_ear"]) if row["left_ear"] else float("nan"),
                                float(row["right_ear"]) if row["right_ear"] else float("nan"),
                                int(row["measurement_valid"]),int(row["monotonic_ms"]))
                            if result.blink:
                                events.append((row["elapsed_ms"],result.blink_reason))
                            if mode=="baseline":
                                for key,attr in (("blink","blink"),("alert","alert"),("eye_state","state"),
                                                 ("count_60s","count_60s"),("active_ms","active_ms")):
                                    self.assertEqual(getattr(result,attr),int(row[key]))
                    self.assertEqual(len(events), counts[index])
                    if mode!="baseline":
                        self.assertEqual(events, rebound_fixtures.RECORDED_DECISIONS[index])


if __name__ == "__main__":
    unittest.main()

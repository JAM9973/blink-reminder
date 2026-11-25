"""빠른 깜빡임과 예외 상황을 확인하는 가상 입력이다."""


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


# 실제 예비 기록을 재생했을 때 확인한 판정 시각이다.
RECORDED_DECISIONS = [[('2966.236', 'normal_reopen'), ('5267.982', 'normal_reopen'), ('7817.875', 'normal_reopen'), ('9029.026', 'normal_reopen'), ('10214.242', 'normal_reopen'), ('10931.096', 'normal_reopen'), ('18784.923', 'normal_reopen'), ('19935.961', 'normal_reopen'), ('23627.516', 'normal_reopen'), ('24576.757', 'normal_reopen')], [('1917.535', 'normal_reopen'), ('3001.226', 'relative_reclosure'), ('3205.11', 'normal_reopen'), ('4167.883', 'relative_reclosure'), ('4359.567', 'normal_reopen'), ('5439.843', 'normal_reopen'), ('6252.167', 'relative_reclosure'), ('6388.266', 'normal_reopen')]]

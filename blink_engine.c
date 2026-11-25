#include "blink_engine.h"

#include <math.h>
#include <stdlib.h>

#define WINDOW_MS 60000
#define MAX_GAP_MS 1000
#define MAX_EVENTS 4096
#define STABLE_FRAMES 2
#define REBOUND_RISE 0.06
#define REBOUND_FALL 0.06
#define REBOUND_FLOOR 0.08
#define REBOUND_RISE_FRAMES 2
#define REBOUND_FALL_FRAMES 2
#define REBOUND_MIN_CLOSED_MS 50
#define REBOUND_MAX_CLOSED_MS 900
#define REBOUND_MAX_RISE_MS 400

enum { UNKNOWN = 0, OPEN = 1, CLOSED = 2 };

struct BlinkEngine {
    int target;
    double closed_ear;
    double open_ear;
    int low_duration_ms;
    int cooldown_ms;
    int state;              /* 확인된 눈 상태 */
    int candidate;          /* 확인 중인 눈 상태 */
    int candidate_frames;   /* 같은 상태가 이어진 프레임 수 */
    int stable_frames;
    int previous_face;
    int has_timestamp;
    int64_t previous_ms;
    int64_t active_ms;      /* 얼굴과 EAR이 유효한 동안의 누적 시간 */
    int64_t low_since_ms;   /* 기준 미달이 시작된 유효 시각 */
    int64_t last_alert_ms;  /* 마지막 알림의 유효 시각 */
    int64_t events[MAX_EVENTS]; /* 깜빡임이 확인된 유효 시각 */
    int event_count;
    int rebound_enabled;
    int last_blink_reason;
    int rebound_initialized, rebound_phase, rebound_rise_frames, rebound_fall_frames;
    double rebound_valley_l, rebound_valley_r, rebound_peak_l, rebound_peak_r;
    int64_t rebound_closed_ms, rebound_rise_ms;
};

BLINK_API int be_api_version(void) { return 2; }

BLINK_API double be_rebound_parameter(int index) {
    const double values[] = {REBOUND_RISE, REBOUND_FALL, REBOUND_FLOOR,
        REBOUND_RISE_FRAMES, REBOUND_FALL_FRAMES, REBOUND_MIN_CLOSED_MS,
        REBOUND_MAX_CLOSED_MS, REBOUND_MAX_RISE_MS};
    return index >= 0 && index < 8 ? values[index] : NAN;
}

BLINK_API int be_set_rebound_enabled(BlinkEngine *e, int enabled) {
    if (!e || (enabled != 0 && enabled != 1)) return 0;
    e->rebound_enabled = enabled;
    e->rebound_initialized = 0;
    e->last_blink_reason = 0;
    return 1;
}

BLINK_API int be_get_blink_reason(BlinkEngine *e) {
    return e ? e->last_blink_reason : 0;
}

BLINK_API BlinkEngine *be_create(int target_count, double closed_ear,
                                  double open_ear, int low_duration_ms,
                                  int cooldown_ms) {
    BlinkEngine *e;
    if (target_count < 0 || !isfinite(closed_ear) || !isfinite(open_ear) ||
        closed_ear <= 0 || open_ear <= closed_ear ||
        low_duration_ms < 0 || cooldown_ms < 0) {
        return NULL;
    }
    e = (BlinkEngine *)calloc(1, sizeof(*e));
    if (!e) return NULL;
    e->target = target_count;
    e->closed_ear = closed_ear;
    e->open_ear = open_ear;
    e->low_duration_ms = low_duration_ms;
    e->cooldown_ms = cooldown_ms;
    e->stable_frames = STABLE_FRAMES;
    e->low_since_ms = -1;
    e->last_alert_ms = -1;
    return e;
}

BLINK_API void be_destroy(BlinkEngine *e) { free(e); }

BLINK_API int be_set_target(BlinkEngine *e, int target_count) {
    if (!e || target_count < 0) return 0;
    e->target = target_count;
    e->low_since_ms = -1;
    return 1;
}

BLINK_API int be_set_stable_frames(BlinkEngine *e, int stable_frames) {
    if (!e || stable_frames < 1 || stable_frames > 30) return 0;
    e->stable_frames = stable_frames;
    e->state = UNKNOWN;
    e->candidate = UNKNOWN;
    e->candidate_frames = 0;
    e->rebound_initialized = 0;
    return 1;
}

static void prune(BlinkEngine *e) {
    int expired = 0, i;
    /* 최근 유효 시간 60초에 들어오지 않는 기록을 앞에서 지운다. */
    while (expired < e->event_count &&
           e->events[expired] <= e->active_ms - WINDOW_MS) {
        expired++;
    }
    if (expired > 0) {
        for (i = expired; i < e->event_count; i++) {
            e->events[i - expired] = e->events[i];
        }
        e->event_count -= expired;
    }
}

static void add_blink(BlinkEngine *e) {
    int i;
    if (e->event_count == MAX_EVENTS) {
        for (i = 1; i < MAX_EVENTS; i++) e->events[i - 1] = e->events[i];
        e->event_count--;
    }
    e->events[e->event_count] = e->active_ms;
    e->event_count++;
}

/* 짧게 다시 뜬 눈을 확인하는 선택 모드다. 횟수는 판정한 시각에 추가한다. */
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
    if (e->active_ms - e->rebound_closed_ms > REBOUND_MAX_CLOSED_MS) return 0;
    if (!e->rebound_phase) {
        e->rebound_valley_l = fmin(e->rebound_valley_l, left);
        e->rebound_valley_r = fmin(e->rebound_valley_r, right);
        if (e->active_ms - e->rebound_closed_ms >= REBOUND_MIN_CLOSED_MS &&
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
            if (++e->rebound_rise_frames >= REBOUND_RISE_FRAMES) e->rebound_phase = 1;
        } else {
            e->rebound_rise_frames = 0;
        }
    } else {
        e->rebound_peak_l = fmax(e->rebound_peak_l, left);
        e->rebound_peak_r = fmax(e->rebound_peak_r, right);
        if (e->active_ms - e->rebound_rise_ms > REBOUND_MAX_RISE_MS) {
            e->rebound_phase = e->rebound_rise_frames = e->rebound_fall_frames = 0;
            e->rebound_valley_l = left;
            e->rebound_valley_r = right;
            return 0;
        }
        if (candidate == CLOSED &&
            e->rebound_peak_l - left >= REBOUND_FALL &&
            e->rebound_peak_r - right >= REBOUND_FALL) {
            if (++e->rebound_fall_frames >= REBOUND_FALL_FRAMES) {
                rebound_start(e, left, right);
                return 1;
            }
        } else {
            e->rebound_fall_frames = 0;
        }
    }
    return 0;
}

static int eye_candidate(BlinkEngine *e, double left, double right) {
    if (!isfinite(left) || !isfinite(right) || left < 0 || right < 0)
        return UNKNOWN;
    if (left <= e->closed_ear && right <= e->closed_ear) return CLOSED;
    if (left >= e->open_ear && right >= e->open_ear) return OPEN;
    return UNKNOWN; /* 양쪽 눈이 다르거나 두 기준 사이인 경우 */
}

BLINK_API int be_update(BlinkEngine *e, double left_ear, double right_ear,
                        int face_visible, int64_t monotonic_ms,
                        BlinkOutput *out) {
    int blink = 0, alert = 0, candidate = UNKNOWN;
    int64_t delta = 0;
    if (!e || !out || monotonic_ms < 0) return 0;
    if (e->has_timestamp && monotonic_ms < e->previous_ms) return 0;
    e->last_blink_reason = BLINK_REASON_NONE;
    if (e->has_timestamp) delta = monotonic_ms - e->previous_ms;
    /* 잘못된 EAR은 얼굴이 없는 경우처럼 처리한다. 0은 감긴 눈의 입력으로 허용한다. */
    face_visible = face_visible && isfinite(left_ear) && isfinite(right_ear) &&
                   left_ear >= 0 && right_ear >= 0;
    /* 얼굴이 없거나 입력이 끊긴 시간은 측정 시간에 더하지 않는다. */
    if (face_visible && e->previous_face && delta <= MAX_GAP_MS)
        e->active_ms += delta;
    e->previous_ms = monotonic_ms;
    e->has_timestamp = 1;
    e->previous_face = !!face_visible;

    if (!face_visible || delta > MAX_GAP_MS) {
        e->state = UNKNOWN;
        e->candidate = UNKNOWN;
        e->candidate_frames = 0;
    }
    if (face_visible) {
        candidate = eye_candidate(e, left_ear, right_ear);
        if (candidate == UNKNOWN) {
            e->candidate = UNKNOWN;
            e->candidate_frames = 0;
        } else {
            if (candidate != e->candidate) {
                e->candidate = candidate;
                e->candidate_frames = 1;
            } else if (e->candidate_frames < e->stable_frames) {
                e->candidate_frames++;
            }
            /* 시작할 때는 열린 눈을 먼저 확인한다. */
            if (e->state == UNKNOWN && candidate == CLOSED) {
                e->candidate_frames = 0;
            } else if (e->candidate_frames >= e->stable_frames && candidate != e->state) {
                /* 감겼다가 다시 열린 순간에 한 번 센다. */
                if (e->state == CLOSED && candidate == OPEN) {
                    blink = 1;
                    e->last_blink_reason = BLINK_REASON_NORMAL_REOPEN;
                    add_blink(e);
                }
                e->state = candidate;
            }
        }
    }

    if (!e->rebound_enabled || !face_visible || delta > MAX_GAP_MS || e->state != CLOSED) {
        e->rebound_initialized = 0;
    } else if (!blink && rebound_update(e, left_ear, right_ear, candidate)) {
        blink = 1;
        e->last_blink_reason = BLINK_REASON_RELATIVE_RECLOSURE;
        add_blink(e);
    }

    prune(e);
    /* 60초를 관찰한 뒤 기준 미달이 계속되면 알림을 결정한다. */
    if (face_visible && e->active_ms >= WINDOW_MS && e->event_count < e->target) {
        if (e->low_since_ms < 0) e->low_since_ms = e->active_ms;
        if (e->active_ms - e->low_since_ms >= e->low_duration_ms &&
            (e->last_alert_ms < 0 ||
             e->active_ms - e->last_alert_ms >= e->cooldown_ms)) {
            alert = 1;
            e->last_alert_ms = e->active_ms;
        }
    } else if (face_visible) {
        e->low_since_ms = -1;
    }

    out->blink = blink;
    out->alert = alert;
    out->count_60s = e->event_count;
    out->state = e->state;
    out->face_visible = !!face_visible;
    out->low_for_ms = e->low_since_ms < 0 ? 0 :
        (int)(e->active_ms - e->low_since_ms);
    out->active_ms = e->active_ms;
    return 1;
}

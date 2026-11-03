#include "blink_engine.h"

#include <math.h>
#include <stdlib.h>

#define WINDOW_MS 60000
#define MAX_GAP_MS 1000
#define MAX_EVENTS 4096
#define STABLE_FRAMES 2

enum { UNKNOWN = 0, OPEN = 1, CLOSED = 2 };

struct BlinkEngine {
    int target;
    double closed_ear;
    double open_ear;
    int low_duration_ms;
    int cooldown_ms;
    int state;              /* confirmed eye state */
    int candidate;          /* current candidate state */
    int candidate_frames;   /* consecutive matching frames */
    int stable_frames;
    int previous_face;
    int has_timestamp;
    int64_t previous_ms;
    int64_t active_ms;      /* time observed while a face is visible */
    int64_t low_since_ms;   /* when the low-count condition began */
    int64_t last_alert_ms;  /* last alert time for cooldown */
    int64_t events[MAX_EVENTS]; /* blink times in the active-time clock */
    int event_count;
};

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
    return 1;
}

static void prune(BlinkEngine *e) {
    int expired = 0, i;
    /* Drop blink times older than the most recent 60 observed seconds. */
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

static int eye_candidate(BlinkEngine *e, double left, double right) {
    if (!isfinite(left) || !isfinite(right) || left < 0 || right < 0)
        return UNKNOWN;
    if (left <= e->closed_ear && right <= e->closed_ear) return CLOSED;
    if (left >= e->open_ear && right >= e->open_ear) return OPEN;
    return UNKNOWN; /* disagreement or hysteresis band */
}

BLINK_API int be_update(BlinkEngine *e, double left_ear, double right_ear,
                        int face_visible, int64_t monotonic_ms,
                        BlinkOutput *out) {
    int blink = 0, alert = 0, candidate = UNKNOWN;
    int64_t delta = 0;
    if (!e || !out || monotonic_ms < 0) return 0;
    if (e->has_timestamp && monotonic_ms < e->previous_ms) return 0;
    if (e->has_timestamp) delta = monotonic_ms - e->previous_ms;
    /* Treat unusable EAR as a missing observation, before advancing time or
       connecting eye states. Zero remains a valid fully closed-eye input. */
    face_visible = face_visible && isfinite(left_ear) && isfinite(right_ear) &&
                   left_ear >= 0 && right_ear >= 0;
    /* Missing/invalid observations and long gaps never add observation time. */
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
            /* Establish OPEN before accepting the first closure. */
            if (e->state == UNKNOWN && candidate == CLOSED) {
                e->candidate_frames = 0;
            } else if (e->candidate_frames >= e->stable_frames && candidate != e->state) {
                /* One closed -> open transition is exactly one blink. */
                if (e->state == CLOSED && candidate == OPEN) {
                    blink = 1;
                    add_blink(e);
                }
                e->state = candidate;
            }
        }
    }

    prune(e);
    /* Alert only after a full window and a sustained low count. */
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

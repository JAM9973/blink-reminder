#ifndef BLINK_ENGINE_H
#define BLINK_ENGINE_H

#include <stdint.h>

#ifdef _WIN32
#define BLINK_API __declspec(dllexport)
#else
#define BLINK_API __attribute__((visibility("default")))
#endif

typedef struct BlinkEngine BlinkEngine;

/* state: 0=unknown, 1=open, 2=closed */
typedef struct {
    int blink;
    int alert;
    int count_60s;
    int state;
    int face_visible; /* effective observation: face present and valid EAR */
    int low_for_ms;
    int64_t active_ms;
} BlinkOutput;

BLINK_API BlinkEngine *be_create(int target_count, double closed_ear,
                                  double open_ear, int low_duration_ms,
                                  int cooldown_ms);
BLINK_API void be_destroy(BlinkEngine *engine);
BLINK_API int be_set_target(BlinkEngine *engine, int target_count);
BLINK_API int be_set_stable_frames(BlinkEngine *engine, int stable_frames);
/* Nonfinite or negative EAR pauses measurement like a missing face; existing
   blink history is kept, and OPEN must be re-established before a new blink. */
BLINK_API int be_update(BlinkEngine *engine, double left_ear, double right_ear,
                        int face_visible, int64_t monotonic_ms,
                        BlinkOutput *output);

#endif

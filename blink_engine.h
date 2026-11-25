#ifndef BLINK_ENGINE_H
#define BLINK_ENGINE_H

#include <stdint.h>

#ifdef _WIN32
#define BLINK_API __declspec(dllexport)
#else
#define BLINK_API __attribute__((visibility("default")))
#endif

typedef struct BlinkEngine BlinkEngine;

enum {
    BLINK_REASON_NONE = 0,
    BLINK_REASON_NORMAL_REOPEN = 1,
    BLINK_REASON_RELATIVE_RECLOSURE = 2
};

/* 눈 상태: 0=확인 중, 1=열림, 2=감김 */
typedef struct {
    int blink;
    int alert;
    int count_60s;
    int state;
    int face_visible; /* 얼굴이 있고 EAR도 유효한 경우 */
    int low_for_ms;
    int64_t active_ms;
} BlinkOutput;

BLINK_API int be_api_version(void);
/* 선택 모드의 상승/하강 기준, EAR 하한, 연속 프레임 수, 시간 제한을 순서대로 돌려준다. */
BLINK_API double be_rebound_parameter(int index);
BLINK_API int be_set_rebound_enabled(BlinkEngine *engine, int enabled);
BLINK_API int be_get_blink_reason(BlinkEngine *engine);

BLINK_API BlinkEngine *be_create(int target_count, double closed_ear,
                                  double open_ear, int low_duration_ms,
                                  int cooldown_ms);
BLINK_API void be_destroy(BlinkEngine *engine);
BLINK_API int be_set_target(BlinkEngine *engine, int target_count);
BLINK_API int be_set_stable_frames(BlinkEngine *engine, int stable_frames);
/* 잘못된 EAR이면 측정을 멈추고 눈 상태를 다시 확인한다. 기존 횟수는 유지한다. */
BLINK_API int be_update(BlinkEngine *engine, double left_ear, double right_ear,
                        int face_visible, int64_t monotonic_ms,
                        BlinkOutput *output);

#endif

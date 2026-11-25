"""미리보기 창의 그리기와 키보드·마우스 입력을 처리한다."""


WINDOW_NAME = "Blink reminder"


def draw_preview_buttons(cv2, frame, landmarks_enabled, *, desktop=False, paused=False):
    height, width = frame.shape[:2]
    margin = 8
    buttons = [("points", "Points ON" if landmarks_enabled else "Points OFF"), ("quit", "Exit")]
    if desktop:
        buttons = [buttons[0], ("pause_toggle", "Resume" if paused else "Pause"),
                   ("hide", "Hide"), buttons[1]]
    button_width = min(150, max(1, (width - margin * (len(buttons) + 1)) // len(buttons)))
    top = max(0, height - 36)
    regions = {}
    for column, (action, label) in enumerate(buttons):
        left = margin + column * (button_width + margin)
        right, bottom = min(width - 1, left + button_width), min(height - 1, top + 28)
        regions[action] = (left, top, right, bottom)
        cv2.rectangle(frame, (left, top), (right, bottom), (45, 45, 45), -1)
        cv2.putText(frame, label, (left + 6, bottom - 8), cv2.FONT_HERSHEY_SIMPLEX,
                    .45, (255, 255, 255), 1)
    return regions


class PreviewWindow:
    def __init__(self, cv2):
        self.cv2 = cv2
        self.created = False
        self.mouse_registered = False
        self.regions = {}
        self.mouse_actions = []

    def _on_mouse(self, event, x, y, flags, userdata):
        if event == self.cv2.EVENT_LBUTTONUP:
            for action, (left, top, right, bottom) in self.regions.items():
                if left <= x <= right and top <= y <= bottom:
                    self.mouse_actions.append(action)
                    break

    def show(self, frame, landmarks_enabled, *, desktop, paused=False):
        self.regions = draw_preview_buttons(self.cv2, frame, landmarks_enabled,
                                             desktop=desktop, paused=paused)
        self.cv2.imshow(WINDOW_NAME, frame)
        self.created = True
        if not self.mouse_registered:
            self.cv2.setMouseCallback(WINDOW_NAME, self._on_mouse)
            self.mouse_registered = True

    def read_events(self, delay):
        key = self.cv2.waitKey(delay) & 0xFF
        closed = False
        if self.created:
            try:
                closed = self.cv2.getWindowProperty(WINDOW_NAME, self.cv2.WND_PROP_VISIBLE) < 1
            except self.cv2.error:
                closed = True
            if closed:
                self.created = self.mouse_registered = False
        actions = self.mouse_actions[:]
        self.mouse_actions.clear()
        return key, actions, closed

    def close(self):
        if self.created:
            self.cv2.destroyWindow(WINDOW_NAME)
        self.created = self.mouse_registered = False

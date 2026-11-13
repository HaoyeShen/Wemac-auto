"""Configuration and calibrated layout constants for the UI backend."""
from __future__ import annotations

import os

APP_NAME = "WeChat auMac"
VERSION = "0.2.0"

WECHAT_APP = "WeChat"
WECHAT_BUNDLE_ID = "com.tencent.xinWeChat"
WECHAT_PROCESS = "WeChat"

#: The copy gesture validated against WeChat 4.1.15 on macOS 26:
#: start near the blank strip above the input box, drag to the top of the
#: chat with a ~2 degree tilt, then hold the left button still at the top.
DRAG_SECONDS = float(os.environ.get("WECHAT_AUMAC_DRAG_SECONDS", "2.0"))
HOLD_SECONDS = float(os.environ.get("WECHAT_AUMAC_HOLD_SECONDS", "3.0"))
ANGLE_DEGREES = float(os.environ.get("WECHAT_AUMAC_ANGLE_DEGREES", "2.0"))

#: Mouse-wheel pulses used to return to the bottom before each read.
WHEEL_LINES = int(os.environ.get("WECHAT_AUMAC_WHEEL_LINES", "60"))
WHEEL_REPEAT = int(os.environ.get("WECHAT_AUMAC_WHEEL_REPEAT", "4"))

#: Window-relative gesture anchors, calibrated on a 1512 x 887 window.
#: Every read first clicks the far-right blank margin just above the input
#: box, then starts the drag from the horizontal middle (x=0.618) at that
#: same bottom line and drags up with a 2 degree tilt.
FOCUS_X_RATIO = float(os.environ.get("WECHAT_AUMAC_FOCUS_X_RATIO", "0.960"))
FOCUS_Y_RATIO = float(os.environ.get("WECHAT_AUMAC_FOCUS_Y_RATIO", "0.820"))
START_X_RATIO = float(os.environ.get("WECHAT_AUMAC_START_X_RATIO", "0.618"))
START_Y_RATIO = float(os.environ.get("WECHAT_AUMAC_START_Y_RATIO", "0.820"))
END_Y_RATIO = float(os.environ.get("WECHAT_AUMAC_END_Y_RATIO", "0.0305"))

#: A maximized WeChat window covers most of the usable display.  We use
#: zoom/maximize rather than the macOS full-screen Space because the latter
#: moves WeChat to another Space and breaks synthetic mouse coordinates.
MAXIMIZED_WIDTH_RATIO = 0.95
MAXIMIZED_HEIGHT_RATIO = 0.80

#: Input-box anchor (center of the editable area, above the icon row).
INPUT_X_RATIO = float(os.environ.get("WECHAT_AUMAC_INPUT_X_RATIO", "0.50"))
INPUT_Y_RATIO = float(os.environ.get("WECHAT_AUMAC_INPUT_Y_RATIO", "0.91"))


CLIPBOARD_TIMEOUT = 5.0

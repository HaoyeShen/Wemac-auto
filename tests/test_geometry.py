import math
import unittest

from wechat_aumac import config
from wechat_aumac.ui import focus_point, input_point, is_maximized, selection_points


class GeometryTest(unittest.TestCase):
    def test_calibrated_points(self):
        start, end = selection_points((0, 33, 1512, 887))
        self.assertAlmostEqual(start[0], 934.4, places=1)
        self.assertAlmostEqual(start[1], 760.3, places=1)
        self.assertAlmostEqual(end[1], 60.1, places=1)
        self.assertGreater(end[0], start[0])

    def test_focus_point(self):
        x, y = focus_point((0, 33, 1512, 887))
        self.assertAlmostEqual(x, 1451.5, places=1)
        self.assertAlmostEqual(y, 760.3, places=1)

    def test_angle_is_two_degrees(self):
        start, end = selection_points((0, 33, 1512, 887))
        dx = end[0] - start[0]
        dy = start[1] - end[1]
        self.assertAlmostEqual(math.degrees(math.atan2(dx, dy)), 2.0, places=6)

    def test_relative_to_window(self):
        start, end = selection_points((100, 100, 1000, 800))
        self.assertAlmostEqual(start[0], 100 + 1000 * config.START_X_RATIO)
        self.assertAlmostEqual(start[1], 100 + 800 * config.START_Y_RATIO)

    def test_maximized(self):
        screen = (0, 0, 1512, 982)
        self.assertTrue(is_maximized((0, 33, 1512, 887), screen))
        self.assertFalse(is_maximized((100, 100, 900, 600), screen))

    def test_input_point(self):
        x, y = input_point((0, 33, 1512, 887))
        self.assertAlmostEqual(x, 756)
        self.assertAlmostEqual(y, 840.17, places=1)


if __name__ == "__main__":
    unittest.main()

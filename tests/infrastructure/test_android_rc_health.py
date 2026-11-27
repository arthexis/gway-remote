import unittest
from unittest.mock import Mock

from gway_remote.android_release_candidate import PACKAGE
from gway_remote.android_rc_health import fresh_health, MENU


def row(text="", desc="", bounds="[10,20][30,40]", package=PACKAGE):
    return dict(text=text, description=desc, bounds=bounds, enabled=True, package=package)


def tree(*rows):
    return {"elements": list(rows), "truncated": False}


class FreshHealthTests(unittest.TestCase):
    def device(self):
        d = Mock()
        d.serial.return_value = "LAB"
        d.size.return_value = (1080, 2220)
        d.screen_state.return_value = {"screen_on":True, "locked":False, "rotation":0}
        d.adb.return_value = b"Status: ok"
        return d

    def test_fresh_health_bounded_route(self):
        d = self.device()
        home = tree(row("Inicio"), row(desc=MENU))
        drawer = tree(row("Inicio"), row("System", bounds="[30,40][50,60]"))
        system = tree(row("System"), row("Status"), row("API Health", bounds="[50,60][70,80]"))
        health = tree(row("API health"), row("status: ok"), row("api: gway-remote/v1"))
        d.ui_tree.side_effect = [home, home, drawer, drawer, home, home, drawer, drawer,
                                 system, system, health]
        self.assertTrue(fresh_health(d, "LAB", pause=lambda _:None))
        args = [c.args for c in d.adb.call_args_list]
        self.assertEqual(args[0], ("LAB","shell","am","start","-W","-n",PACKAGE+"/.MainActivity"))
        self.assertEqual([a[-2:] for a in args[1:]], [(20,30),(20,30),(20,30),(40,50),(60,70)])

    def test_ambiguous_or_foreign_screen_has_no_input(self):
        for invalid in (tree(row(desc=MENU), row(desc=MENU)),
                        tree(row(desc=MENU), row("other", package="other.app")),
                        dict(tree(row(desc=MENU)), truncated=True)):
            d = self.device()
            d.ui_tree.return_value = invalid
            with self.assertRaises(ValueError):
                fresh_health(d, "LAB", pause=lambda _:None)
            self.assertEqual(d.adb.call_count, 1)  # fixed app launch only

    def test_moved_target_has_no_input(self):
        d = self.device()
        d.ui_tree.side_effect = [tree(row(desc=MENU)),
                                 tree(row(desc=MENU, bounds="[20,30][40,50]"))]
        with self.assertRaisesRegex(ValueError, "health_target_moved"):
            fresh_health(d, "LAB", pause=lambda _:None)
        self.assertEqual(d.adb.call_count,1)

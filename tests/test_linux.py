"""The Linux readers, fed files recorded from a Linux VM (tests/data/linux).
These run on any OS: each parser takes a file's text, not the live file."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import N, ROOT, plain, sl

DATA = ROOT / "tests" / "data" / "linux"
PAGE = 4096


def data(name):
    return (DATA / name).read_text()


class ProcStat(unittest.TestCase):
    def test_folds_eight_counters_into_the_macs_four(self):
        # cpu  user nice system idle iowait irq softirq steal
        self.assertEqual(sl.parse_proc_stat("cpu  100 5 20 800 30 2 3 4 0 0\ncpu0 1 1 1 1\n"),
                         [100, 20 + 2 + 3 + 4, 800 + 30, 5])

    def test_reads_a_recorded_file(self):
        user, system, idle, nice = sl.parse_proc_stat(data("stat-idle.txt"))
        self.assertGreater(idle, 10 * (user + system))  # an idle VM

    def test_an_older_kernel_with_fewer_fields_still_reads(self):
        self.assertEqual(sl.parse_proc_stat("cpu 1 2 3 4\n"), [1, 3, 4, 2])

    def test_garbage_is_no_reading(self):
        for text in (None, "", "cpu x y z\n"):
            with self.subTest(text=text):
                self.assertIsNone(sl.parse_proc_stat(text))

    def test_usage_between_two_readings(self):
        before = sl.parse_proc_stat("cpu  100 0 100 800 0 0 0 0\n")
        after = sl.parse_proc_stat("cpu  400 0 200 900 0 0 0 0\n")
        self.assertEqual(sl.cpu_usage(before, after), 80)  # 400 busy of 500


class Memory(unittest.TestCase):
    def test_a_roomy_vm_is_normal_with_nothing_compressed_or_swapped(self):
        mem = sl.parse_memory_linux(data("meminfo-roomy.txt"), data("psi-calm.txt"),
                                    "pswpin 0\npswpout 0\n", PAGE)
        self.assertEqual(mem["pressure"], 1)
        self.assertEqual(mem["used_pct"], 8)  # 6535816 of 7081464 kB available
        self.assertNotIn("comp_mb", mem)      # zswap off
        self.assertNotIn("swap_mb", mem)      # no swap configured

    def test_stalling_on_memory_is_warn_with_zswap_and_swap(self):
        mem = sl.parse_memory_linux(data("meminfo-tight.txt"), data("psi-stalling.txt"),
                                    data("vmstat-swapping.txt"), PAGE)
        self.assertEqual(mem["pressure"], 2)  # some avg10 23.5%: past 10, under 40
        self.assertEqual(mem["used_pct"], 96)
        self.assertEqual(round(mem["comp_mb"]), 1331)
        self.assertEqual(round(mem["swap_mb"]), 1229)
        self.assertEqual(round(mem["swapped_out_mb"]), 2871)  # 735000 pages

    def test_psi_levels(self):
        meminfo = data("meminfo-roomy.txt")
        for avg10, level in (("9.99", 1), ("10.00", 2), ("39.9", 2), ("40.0", 4)):
            with self.subTest(avg10=avg10):
                psi = f"some avg10={avg10} avg60=0 avg300=0 total=1\n"
                self.assertEqual(sl.parse_memory_linux(meminfo, psi, "", PAGE)["pressure"], level)

    def test_without_psi_little_memory_left_is_critical(self):
        # 4% available, on a kernel built without /proc/pressure
        mem = sl.parse_memory_linux(data("meminfo-tight.txt"), None, "", PAGE)
        self.assertEqual(mem["pressure"], 4)

    def test_no_meminfo_is_no_reading(self):
        self.assertIsNone(sl.parse_memory_linux(None, None, None, PAGE))
        self.assertIsNone(sl.parse_memory_linux("MemTotal: 100 kB\n", None, None, PAGE))

    def test_meter_without_zswap_shows_no_comp(self):
        mem = sl.parse_memory_linux(data("meminfo-roomy.txt"), data("psi-calm.txt"), "", PAGE)
        self.assertEqual(plain(sl.mem_meter(mem)), "mem ▮▯▯▯▯▯▯▯  8%")


class Trend(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "mem-trend.json"

    def test_swap_arrow_works_without_comp(self):
        # Linux without zswap: no comp reading, but swap still moves
        first = {"swapped_out_mb": 100.0, "swapped_in_mb": 50.0}
        later = {"swapped_out_mb": 160.0, "swapped_in_mb": 50.0}
        self.assertEqual(sl.mem_trend(first, self.path, N), {})
        self.assertEqual(sl.mem_trend(later, self.path, N + 60), {"comp": None, "swap": "up"})


class Battery(unittest.TestCase):
    def supply(self, root, name, **files):
        d = Path(root) / name
        d.mkdir()
        for key, value in files.items():
            (d / key).write_text(value + "\n")

    def test_reads_the_first_battery_and_ignores_the_charger(self):
        with tempfile.TemporaryDirectory() as root:
            self.supply(root, "AC", type="Mains", online="1")
            self.supply(root, "BAT0", type="Battery", capacity="22", status="Discharging")
            self.assertEqual(sl.read_battery_linux(root), {"pct": 22, "ac": False})

    def test_charging_or_full_counts_as_plugged_in(self):
        with tempfile.TemporaryDirectory() as root:
            self.supply(root, "BAT1", type="Battery", capacity="80", status="Charging")
            self.assertEqual(sl.read_battery_linux(root), {"pct": 80, "ac": True})

    def test_a_desktop_or_container_has_none(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(sl.read_battery_linux(root))
        self.assertIsNone(sl.read_battery_linux("/nonexistent/power_supply"))


class Footprints(unittest.TestCase):
    def test_names_and_resident_size_from_proc(self):
        with tempfile.TemporaryDirectory() as proc:
            for pid, name, rss in (("1", "init", "1024"), ("42", "chrome", "204800"), ("43", "chrome", "102400")):
                d = Path(proc) / pid
                d.mkdir()
                (d / "status").write_text(f"Name:\t{name}\nState:\tS\nVmRSS:\t   {rss} kB\n")
            kthread = Path(proc) / "2"
            kthread.mkdir()
            (kthread / "status").write_text("Name:\tkthreadd\nState:\tS\n")  # no VmRSS
            (Path(proc) / "self").mkdir()
            top = sl.biggest_app(sl.named_footprints_linux(proc))
        self.assertEqual((top["name"], top["mb"]), ("chrome", 300.0))


@unittest.skipUnless(sys.platform.startswith("linux"), "reads this Linux machine")
class ThisMachine(unittest.TestCase):
    def test_cpu_and_memory_come_from_proc(self):
        s = sl.gather_system()
        self.assertEqual(s["cpu"]["cores"], os.cpu_count())
        self.assertTrue(0 <= s["memory"]["used_pct"] <= 100)
        self.assertIn(s["memory"]["pressure"], (1, 2, 4))

    def test_this_process_is_among_the_footprints(self):
        names = [name for name, _ in sl.named_footprints_linux()]
        self.assertTrue(any(n.startswith("python") for n in names), names[:20])


class Platform(unittest.TestCase):
    def test_an_unknown_os_has_no_system_column(self):
        with mock.patch.object(sl.sys, "platform", "win32"):
            self.assertEqual(sl.gather_system(), {})


if __name__ == "__main__":
    unittest.main()

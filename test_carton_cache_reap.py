"""The carton_cache reaper: old spills go, fresh ones stay, and the query path never breaks.

Run as a SCRIPT (`python3 test_carton_cache_reap.py`) — the repo root IS the `carton_mcp`
package, so pytest-from-this-directory breaks on package inference. That is this repo's own
convention (see test_carton_quota.py, test_carton_breaker.py).

WHAT IS BEING PINNED. `_clip_large_result` spills an oversized `get_concept_network` result to a
timestamped file and hands the caller the path. Nothing reads one back, and each call writes a new
name, so before the reaper the directory only grew — measured 7.1 GB / 405 files over 114 subjects.
The load-bearing test is `test_a_reap_failure_NEVER_breaks_the_caller`: this runs on the query
path, so a cleanup that raises would turn a working query into an exception, which is a worse
outcome than the disk it saves.
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from carton_utils import (  # noqa: E402
    CACHE_TTL_DAYS_ENV,
    _cache_ttl_days,
    _reap_spilled_results,
)

DAY = 86400


def _spill(d: Path, name: str, age_days: float) -> Path:
    p = d / name
    p.write_text("[]")
    t = time.time() - age_days * DAY
    os.utime(p, (t, t))
    return p


class ReapSpilledResults(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get(CACHE_TTL_DAYS_ENV)
        os.environ.pop(CACHE_TTL_DAYS_ENV, None)
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        if self._prev is None:
            os.environ.pop(CACHE_TTL_DAYS_ENV, None)
        else:
            os.environ[CACHE_TTL_DAYS_ENV] = self._prev

    def test_old_spills_go_and_fresh_ones_stay(self):
        old = _spill(self.d, "A_network_20260101_010101.json", age_days=9)
        edge = _spill(self.d, "B_network_20260101_010101.json", age_days=5.5)
        fresh = _spill(self.d, "C_network_20260101_010101.json", age_days=1)

        self.assertEqual(_reap_spilled_results(self.d), 2)
        self.assertFalse(old.exists())
        self.assertFalse(edge.exists())
        self.assertTrue(fresh.exists(), "a spill inside the TTL must survive")

    def test_it_only_touches_spilled_results(self):
        """⭐ The directory is not assumed to hold only spills.

        Everything measured there was `*_network_*.json`, but a glob that ate anything else would
        be a deletion bug waiting for the first day something else lands there.
        """
        spill = _spill(self.d, "A_network_20260101_010101.json", age_days=30)
        other = _spill(self.d, "important_notes.json", age_days=30)
        nested = self.d / "sub"
        nested.mkdir()
        keep = _spill(nested, "deep_thing.txt", age_days=30)

        self.assertEqual(_reap_spilled_results(self.d), 1)
        self.assertFalse(spill.exists())
        self.assertTrue(other.exists(), "a non-spill file must never be reaped")
        self.assertTrue(keep.exists())

    def test_an_empty_or_missing_directory_is_not_an_error(self):
        self.assertEqual(_reap_spilled_results(self.d), 0)
        self.assertEqual(_reap_spilled_results(self.d / "does_not_exist"), 0)

    def test_a_reap_failure_NEVER_breaks_the_caller(self):
        """⭐ THE ONE THAT MATTERS. This runs on the query path.

        A file vanishing mid-reap is the realistic case (two processes reaping at once), and it
        must be absorbed silently rather than propagating into whatever asked for a concept
        network. Simulated by pointing the reaper at a path that is a FILE, not a directory.
        """
        not_a_dir = self.d / "regular_file"
        not_a_dir.write_text("x")
        self.assertEqual(_reap_spilled_results(not_a_dir), 0)  # returns, does not raise

    # ── the TTL setting ──────────────────────────────────────────────────────
    def test_the_ttl_defaults_and_is_overridable(self):
        self.assertEqual(_cache_ttl_days(), 5.0)
        os.environ[CACHE_TTL_DAYS_ENV] = "0.5"
        self.assertEqual(_cache_ttl_days(), 0.5)

        half_day_old = _spill(self.d, "A_network_20260101_010101.json", age_days=0.75)
        self.assertEqual(_reap_spilled_results(self.d), 1)
        self.assertFalse(half_day_old.exists())

    def test_junk_ttl_is_REFUSED_not_silently_defaulted(self):
        """A TTL that quietly becomes 5 is a setting that looks applied and is not."""
        for bad in ("5d", "abc", "-1", "0"):
            os.environ[CACHE_TTL_DAYS_ENV] = bad
            with self.assertRaises(ValueError, msg=f"{bad!r} should be refused"):
                _cache_ttl_days()

    def test_a_junk_ttl_still_does_not_break_the_caller(self):
        """Refusing the setting is right; refusing to answer a query because of it is not."""
        os.environ[CACHE_TTL_DAYS_ENV] = "not-a-number"
        old = _spill(self.d, "A_network_20260101_010101.json", age_days=99)
        self.assertEqual(_reap_spilled_results(self.d), 0)
        self.assertTrue(old.exists(), "nothing is reaped when the TTL cannot be read")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""缓动宝箱：进背包 + 防重复领取。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import AppState, ChestItem, EaseChestsState, Inventory, validate_state_invariants
from src.storage import load_state, save_state, take_load_warning
from src.ui_roll_bar import (
    _cycle_checkpoints,
    _cycle_chest_rarities,
    _ease_span_for_cycle,
    _independent_cycle,
    resolve_held_cycle,
)


class SingleChestCycleTests(unittest.TestCase):
    def test_span_covers_about_five_minutes(self):
        spans = [_ease_span_for_cycle(i) for i in range(15)]
        self.assertEqual(min(spans), 258)
        self.assertEqual(max(spans), 342)
        self.assertEqual(len(set(spans)), 15)
        self.assertEqual(sum(spans) / 15, 300)

    def test_checkpoints_are_end_only(self):
        self.assertEqual(_cycle_checkpoints(300, 0), (1.0,))
        self.assertEqual(_cycle_checkpoints(258, 7), (1.0,))

    def test_one_rarity_per_cycle_is_seeded(self):
        r = _cycle_chest_rarities(300, 0)
        self.assertEqual(len(r), 1)
        self.assertTrue(0 <= r[0] <= 4)
        self.assertEqual(_cycle_chest_rarities(300, 0), r)


class EaseChestsModelTests(unittest.TestCase):
    def test_inventory_add_chest_and_counts(self):
        inv = Inventory()
        inv.add_chest(0)
        inv.add_chest(4)
        inv.add_chest(4)
        self.assertEqual(len(inv.chests), 3)
        self.assertEqual(inv.chest_counts_by_rarity(), (1, 0, 0, 0, 2))

    def test_mark_claimed_once(self):
        ec = EaseChestsState(cycle_id=3)
        self.assertTrue(ec.mark_claimed(0))
        self.assertFalse(ec.mark_claimed(0))
        self.assertFalse(ec.mark_claimed(1))
        self.assertEqual(ec.claimed, (True,))

    def test_reset_for_cycle_clears_claimed(self):
        ec = EaseChestsState(cycle_id=1, claimed=(True,), holding=True)
        ec.reset_for_cycle(2)
        self.assertEqual(ec.cycle_id, 2)
        self.assertEqual(ec.claimed, (False,))
        self.assertFalse(ec.holding)

    def test_roundtrip_holding_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("src.storage.get_data_dir", return_value=Path(tmp)):
                state = AppState()
                state.ease_chests = EaseChestsState(cycle_id=4, holding=True)
                save_state(state)
                loaded = load_state()
                self.assertTrue(loaded.ease_chests.holding)
                self.assertEqual(loaded.ease_chests.cycle_id, 4)

    def test_roundtrip_chests_and_ease_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("src.storage.get_data_dir", return_value=Path(tmp)):
                state = AppState()
                state.inventory.add_chest(2)
                state.inventory.add_chest(4)
                state.ease_chests = EaseChestsState(
                    cycle_id=7, claimed=(True,)
                )
                save_state(state)
                loaded = load_state()
                self.assertIsNone(take_load_warning())
                self.assertEqual(len(loaded.inventory.chests), 2)
                self.assertEqual(loaded.inventory.chests[0].rarity, 2)
                self.assertEqual(loaded.inventory.chests[1].rarity, 4)
                self.assertEqual(loaded.ease_chests.cycle_id, 7)
                self.assertEqual(loaded.ease_chests.claimed, (True,))
                self.assertIsNone(validate_state_invariants(loaded))

    def test_legacy_three_claimed_uses_last_slot(self):
        waiting = EaseChestsState.from_dict(
            {"cycle_id": 2, "claimed": [True, True, False], "holding": True}
        )
        self.assertEqual(waiting.claimed, (False,))
        already = EaseChestsState.from_dict(
            {"cycle_id": 2, "claimed": [False, False, True], "holding": False}
        )
        self.assertEqual(already.claimed, (True,))

    def test_legacy_inventory_without_chests(self):
        inv = Inventory.from_dict({"gold": 1.0, "diamond": 0.5})
        self.assertEqual(inv.chests, [])
        self.assertEqual(inv.gold, 1.0)

    def test_bad_chest_rejected_by_invariant(self):
        s = AppState()
        s.inventory.chests.append(ChestItem(rarity=9))
        self.assertIn("rarity", validate_state_invariants(s) or "")


class HoldAtEndTests(unittest.TestCase):
    def test_reaching_span_starts_hold(self):
        span0 = _ease_span_for_cycle(0)
        progress, span, cid, holding = resolve_held_cycle(
            span0, freeze_at_end=True, holding=False, held_cycle_id=0
        )
        self.assertEqual(progress, span0)
        self.assertEqual(span, span0)
        self.assertEqual(cid, 0)
        self.assertTrue(holding)

    def test_hold_does_not_wrap(self):
        span0 = _ease_span_for_cycle(0)
        progress, span, cid, holding = resolve_held_cycle(
            span0 + 80, freeze_at_end=True, holding=True, held_cycle_id=0
        )
        self.assertTrue(holding)
        self.assertEqual(cid, 0)
        self.assertEqual(progress, span0)
        self.assertEqual(span, span0)
        _p, _s, natural_cid = _independent_cycle(span0 + 80)
        self.assertNotEqual(natural_cid, 0)

    def test_release_carries_overflow_to_next_cycle(self):
        span0 = _ease_span_for_cycle(0)
        overflow = 80
        progress, span, cid, holding = resolve_held_cycle(
            span0 + overflow,
            freeze_at_end=False,
            holding=False,
            held_cycle_id=0,
        )
        self.assertFalse(holding)
        self.assertEqual(cid, 1)
        self.assertEqual(progress, overflow)
        self.assertEqual(span, _ease_span_for_cycle(1))


if __name__ == "__main__":
    unittest.main()

"""皇室战争式开箱:解锁倒计时 + 概率开箱 + 字母收藏。"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.chest_opening import (
    LETTERS_PER_CHEST,
    MAX_UNLOCK_SLOTS,
    UNLOCK_SPANS,
    generate_open_result,
    is_ready,
    locked_chests,
    open_chest,
    ready_chests,
    remaining_seconds,
    slots_available,
    start_unlock,
    unlock_span_seconds,
    unlocking_chests,
)
from src.models import AppState, ChestItem, Inventory, validate_state_invariants
from src.storage import load_state, save_state


def _chest(rarity: int) -> ChestItem:
    return ChestItem(rarity=rarity)


class UnlockTests(unittest.TestCase):
    def test_unlock_span_table(self):
        self.assertEqual(
            [unlock_span_seconds(r) for r in range(5)],
            [1800, 3600, 7200, 14400, 28800],
        )

    def test_start_unlock_sets_timestamp(self):
        state = AppState()
        chest = state.inventory.add_chest(0)
        self.assertTrue(start_unlock(state, chest, now=1000.0))
        self.assertEqual(chest.unlock_started_at, 1000.0)
        self.assertIn(chest, unlocking_chests(state, now=1000.0))

    def test_cannot_unlock_twice(self):
        state = AppState()
        chest = state.inventory.add_chest(0)
        start_unlock(state, chest, now=1000.0)
        self.assertFalse(start_unlock(state, chest, now=1001.0))

    def test_slots_limit(self):
        state = AppState()
        for _ in range(MAX_UNLOCK_SLOTS):
            start_unlock(state, state.inventory.add_chest(1), now=1000.0)
        self.assertFalse(slots_available(state, now=1000.0))
        extra = state.inventory.add_chest(1)
        self.assertFalse(start_unlock(state, extra, now=1001.0))

    def test_ready_after_span(self):
        state = AppState()
        chest = state.inventory.add_chest(0)
        start_unlock(state, chest, now=1000.0)
        self.assertFalse(is_ready(chest, now=1000.0 + 1799.0))
        self.assertTrue(is_ready(chest, now=1000.0 + 1800.0))
        self.assertIn(chest, ready_chests(state, now=1000.0 + 1800.0))

    def test_remaining_seconds_ceil(self):
        state = AppState()
        chest = state.inventory.add_chest(0)
        self.assertEqual(remaining_seconds(chest), UNLOCK_SPANS[0])
        start_unlock(state, chest, now=1000.0)
        self.assertEqual(remaining_seconds(chest, now=1000.0 + 60.5), 1800 - 60)
        self.assertEqual(remaining_seconds(chest, now=1000.0 + 5000.0), 0)

    def test_locked_not_in_unlocking(self):
        state = AppState()
        chest = state.inventory.add_chest(2)
        self.assertIn(chest, locked_chests(state))
        self.assertEqual(unlocking_chests(state), [])


class OpenResultTests(unittest.TestCase):
    def _seed_rng(self, seed: int = 1234) -> random.Random:
        return random.Random(seed)

    def test_letter_count_in_range_all_rarities(self):
        for rarity in range(5):
            for seed in range(20):
                result = generate_open_result(rarity, self._seed_rng(seed))
                lo, hi = LETTERS_PER_CHEST[rarity]
                self.assertTrue(lo <= len(result.letters) <= hi, (rarity, seed, result))

    def test_no_duplicate_letters_within_open(self):
        for rarity in range(5):
            for seed in range(50):
                result = generate_open_result(rarity, self._seed_rng(seed))
                letters = [l for l, _ in result.letters]
                self.assertEqual(len(set(letters)), len(letters), (rarity, seed))

    def test_rarities_within_range(self):
        result = generate_open_result(4, self._seed_rng(7))
        for _, rar in result.letters:
            self.assertTrue(0 <= rar <= 4)

    def test_guarantee_at_least_one_uncommon(self):
        # 保底:每箱至少 1 个字母稀有度 ≥ 1(罕见)
        for rarity in range(5):
            for seed in range(200):
                result = generate_open_result(rarity, self._seed_rng(seed))
                self.assertTrue(
                    any(r >= 1 for _, r in result.letters),
                    (rarity, seed, result),
                )

    def test_companion_currency_within_ranges(self):
        for rarity in range(5):
            for seed in range(100):
                result = generate_open_result(rarity, self._seed_rng(seed))
                self.assertGreaterEqual(result.gold, 0.0)
                self.assertGreaterEqual(result.diamond, 0.0)
                if result.gold > 0:
                    self.assertLessEqual(result.gold, 30.0)
                if result.diamond > 0:
                    self.assertLessEqual(result.diamond, 8.0)

    def test_deterministic_same_seed(self):
        a = generate_open_result(3, self._seed_rng(42))
        b = generate_open_result(3, self._seed_rng(42))
        self.assertEqual(a.letters, b.letters)
        self.assertEqual(a.gold, b.gold)
        self.assertEqual(a.diamond, b.diamond)


class OpenCommitTests(unittest.TestCase):
    def test_open_removes_chest_and_credits(self):
        state = AppState()
        chest = state.inventory.add_chest(2)
        from src.chest_opening import OpenResult

        result = OpenResult(
            letters=[("A", 1), ("B", 0), ("C", 3)],
            gold=5.0,
            diamond=1.5,
        )
        open_chest(state, chest, result)
        self.assertNotIn(chest, state.inventory.chests)
        self.assertEqual(state.inventory.letter_total("A"), 1)
        self.assertEqual(state.inventory.letters["B"][0], 1)
        self.assertEqual(state.inventory.letters["C"][3], 1)
        self.assertEqual(state.inventory.gold, 5.0)
        self.assertEqual(state.inventory.diamond, 1.5)

    def test_add_letter_stacks_counts(self):
        inv = Inventory()
        inv.add_letter("a", 0)
        inv.add_letter("A", 0)
        inv.add_letter("A", 4)
        self.assertEqual(inv.letters["A"][0], 2)
        self.assertEqual(inv.letters["A"][4], 1)
        self.assertEqual(inv.letter_total("A"), 3)
        self.assertEqual(inv.letters_collected_count(), 2)  # (A,普通) + (A,传奇)

    def test_letters_collected_count_cap(self):
        inv = Inventory()
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            inv.add_letter(letter, 0)
        self.assertEqual(inv.letters_collected_count(), 26)

    def test_add_letter_rejects_invalid(self):
        inv = Inventory()
        inv.add_letter("1", 0)
        inv.add_letter("ab", 1)
        self.assertNotIn("1", inv.letters)
        self.assertNotIn("ab", inv.letters)


class PersistenceTests(unittest.TestCase):
    def test_roundtrip_letters_and_unlock(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("src.storage.get_data_dir", return_value=Path(tmp)):
                state = AppState()
                chest = state.inventory.add_chest(1)
                chest.unlock_started_at = 1234.0
                state.inventory.add_letter("A", 0)
                state.inventory.add_letter("A", 2)
                state.inventory.add_letter("Z", 4)
                save_state(state)
                loaded = load_state()
                self.assertIsNone(validate_state_invariants(loaded))
                self.assertEqual(loaded.inventory.chests[0].unlock_started_at, 1234.0)
                self.assertEqual(loaded.inventory.letters["A"][0], 1)
                self.assertEqual(loaded.inventory.letters["A"][2], 1)
                self.assertEqual(loaded.inventory.letters["Z"][4], 1)

    def test_legacy_inventory_without_new_fields(self):
        inv = Inventory.from_dict({"gold": 1.0, "diamond": 0.5, "chests": []})
        self.assertEqual(inv.letters, {})
        chest = ChestItem.from_dict({"rarity": 2, "obtained_at": 1.0})
        self.assertIsNone(chest.unlock_started_at)
        self.assertEqual(chest.to_dict(), {"rarity": 2, "obtained_at": 1.0})

    def test_invalid_letter_rejected_by_invariant(self):
        s = AppState()
        s.inventory.letters["1"] = [1, 0, 0, 0, 0]
        self.assertIn("letters", validate_state_invariants(s) or "")
        s2 = AppState()
        s2.inventory.letters["A"] = [1, 0, 0, 0]
        self.assertIn("letters", validate_state_invariants(s2) or "")


if __name__ == "__main__":
    unittest.main()

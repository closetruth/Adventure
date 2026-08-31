"""词汇自走棋：鼠标可点、点击区不得每帧膨胀、启动不得堵住管道。"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.game_launcher import game_subprocess_stdio
from src.game_protocol import GameResult, GameSession

from games.word_arena import (
    LIFE_GOLD_COST,
    MAX_LIVES,
    ShopSlot,
    Unit,
    WordArenaGame,
    WORDS,
    lineup_from_dict,
    lineup_to_dict,
)


def _session(gold: float = 80.0) -> GameSession:
    return GameSession.create(gold=gold, diamond=2.0)


class WordArenaMouseTests(unittest.TestCase):
    def setUp(self):
        self.game = WordArenaGame(_session())

    def test_shop_click_zones_do_not_grow_each_frame(self):
        """每帧 _register_click 却不清空，几分钟后点击列表上万导致卡顿。"""
        self.game._click_start_game()
        self.game._draw()
        n1 = len(self.game._click_zones)
        self.assertGreater(n1, 0, "商店阶段应有可点区域")
        for _ in range(10):
            self.game._draw()
        self.assertEqual(
            len(self.game._click_zones),
            n1,
            "点击区必须每帧重建，不能累计",
        )

    def test_title_click_starts_game(self):
        self.game._draw()
        actions = [a for _, a, _ in self.game._click_zones]
        self.assertIn("start_game", actions)
        rect = next(r for r, a, _ in self.game._click_zones if a == "start_game")
        self.game._on_mouse_down(rect.center)
        self.assertEqual(self.game.phase, "shop")
        self.assertTrue(self.game.entry_paid)

    def test_click_shop_card_buys_without_crash(self):
        """曾把 (i,) 当成 idx 传入，点商店会 TypeError。"""
        g = self.game
        g._click_start_game()
        spec = WORDS[0]
        g.shop[0] = ShopSlot(kind="word", spec=spec)
        g.copper = 20
        g._draw()
        buy = next(r for r, a, args in g._click_zones if a == "buy_shop" and args == (0,))
        g._on_mouse_down((buy.x + 20, buy.y + 40))
        self.assertTrue(any(u is not None for u in g.team))
        self.assertIsNone(g.shop[0].spec)

    def test_freeze_button_not_swallowed_by_card(self):
        g = self.game
        g._click_start_game()
        g.shop[0] = ShopSlot(kind="word", spec=WORDS[0])
        g._draw()
        frz = next(r for r, a, args in g._click_zones if a == "freeze" and args == (0,))
        g._on_mouse_down(frz.center)
        self.assertTrue(g.frozen[0])
        self.assertIsNotNone(g.shop[0].spec)


class WordArenaCopperAndLifeTests(unittest.TestCase):
    def setUp(self):
        self.game = WordArenaGame(_session(gold=80.0))

    def test_shop_spend_uses_copper_not_gold(self):
        g = self.game
        g._click_start_game()
        gold_before = g.gold
        copper_before = g.copper
        spec = WORDS[0]
        g.shop[0] = ShopSlot(kind="word", spec=spec)
        g._click_buy_shop(0)
        self.assertEqual(g.gold, gold_before)
        self.assertEqual(g.copper, copper_before - spec.cost)
        self.assertTrue(any(u is not None for u in g.team))

    def test_start_does_not_deduct_entry_gold_again(self):
        g = self.game
        g._click_start_game()
        self.assertEqual(g.gold, 80.0)
        self.assertEqual(g.copper, 10)

    def test_buy_life_costs_five_gold(self):
        g = self.game
        g._click_start_game()
        g.lives = 7
        g.gold = 20
        g._click_buy_life()
        self.assertEqual(g.lives, 8)
        self.assertEqual(g.gold, 20 - LIFE_GOLD_COST)

    def test_buy_life_blocked_when_full_or_broke(self):
        g = self.game
        g._click_start_game()
        g.lives = MAX_LIVES
        g.gold = 50
        g._click_buy_life()
        self.assertEqual(g.lives, MAX_LIVES)
        self.assertEqual(g.gold, 50)
        g.lives = 3
        g.gold = LIFE_GOLD_COST - 1
        g._click_buy_life()
        self.assertEqual(g.lives, 3)
        self.assertEqual(g.gold, LIFE_GOLD_COST - 1)


class WordArenaLineupAndBattleTests(unittest.TestCase):
    def test_history_lineup_becomes_enemy(self):
        snap = lineup_to_dict(
            4,
            [Unit.from_spec(WORDS[0], 2), None, Unit.from_spec(WORDS[1], 1), None, None],
        )
        session = GameSession.create(gold=80.0, diamond=2.0, word_lineups=[snap])
        g = WordArenaGame(session)
        g._click_start_game()
        words = [u.word for u in g.enemy_team]
        self.assertIn(WORDS[0].word, words)
        self.assertIn(WORDS[1].word, words)

    def test_battle_display_starts_full_hp(self):
        g = WordArenaGame(_session())
        g._click_start_game()
        g.team[0] = Unit.from_spec(WORDS[0])
        g.enemy_team = [Unit.from_spec(WORDS[1])]
        start_hp = g.team[0].hp
        g._start_battle()
        self.assertEqual(g.phase, "battle")
        alive = [u for u in g.battle_players if u is not None]
        self.assertTrue(alive)
        self.assertEqual(alive[0].hp, start_hp)
        self.assertEqual(alive[0].hp, alive[0].max_hp)

    def test_session_result_roundtrip_lineups(self):
        snap = lineup_to_dict(2, [Unit.from_spec(WORDS[0]), None, None, None, None])
        session = GameSession.create(gold=1.0, diamond=0.0, word_lineups=[snap])
        path = session.write()
        loaded = GameSession.read(path)
        restored = lineup_from_dict(loaded.word_lineups[0])
        self.assertEqual(restored[0].word, WORDS[0].word)
        result = GameResult(session_id=session.session_id, word_lineups=[snap])
        out = session.result_path()
        result.write(out)
        back = GameResult.read(out)
        self.assertEqual(back.word_lineups[0]["units"][0]["word"], WORDS[0].word)
        path.unlink(missing_ok=True)
        out.unlink(missing_ok=True)


class GameLaunchStdioTests(unittest.TestCase):
    def test_stdout_not_piped(self):
        """capture_output 会把 pygame 的 stdout 堵死，游戏表现为卡顿。"""
        kw = game_subprocess_stdio()
        self.assertIs(kw["stdout"], subprocess.DEVNULL)
        self.assertIs(kw["stderr"], subprocess.PIPE)

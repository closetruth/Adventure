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
from src.game_protocol import GameSession

from games.word_arena import ShopSlot, WordArenaGame, WORDS


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
        g.gold = 20
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


class GameLaunchStdioTests(unittest.TestCase):
    def test_stdout_not_piped(self):
        """capture_output 会把 pygame 的 stdout 堵死，游戏表现为卡顿。"""
        kw = game_subprocess_stdio()
        self.assertIs(kw["stdout"], subprocess.DEVNULL)
        self.assertIs(kw["stderr"], subprocess.PIPE)

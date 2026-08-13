"""金币老虎机小游戏：入场后固定 8 把，三连发奖，只结算金币。"""
from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import List, Tuple

try:
    import pygame
except ImportError:
    print("请先安装 pygame-ce: pip install pygame-ce")
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from games.font_util import load_font  # noqa: E402
from src.game_protocol import GameResult, GameSession  # noqa: E402

W, H = 640, 520
FPS = 60
SPINS_TOTAL = 8
SPIN_CAP = 20.0

# 权重使单把 EV ≈ 1 金，8 把约 8 金 / 入场 10 → RTP ~80%
SYMBOLS = ("X", "BAR", "金", "7")
WEIGHTS = (6, 22, 50, 22)
PAYTABLE = {
    ("BAR", "BAR", "BAR"): 2.0,
    ("金", "金", "金"): 6.0,
    ("7", "7", "7"): 20.0,
}

COL_BG = (18, 20, 30)
COL_PANEL = (33, 37, 56)
COL_REEL = (12, 14, 22)
COL_TEXT = (240, 242, 250)
COL_MUTED = (168, 176, 196)
COL_GOLD = (255, 213, 79)
COL_BAR = (200, 210, 230)
COL_SEVEN = (255, 159, 67)
COL_MISS = (138, 144, 158)
COL_LINE = (90, 100, 140)
COL_WIN = (122, 232, 124)

REEL_STOP_S = (0.45, 0.90, 1.35)


def _pick_symbol() -> str:
    return random.choices(SYMBOLS, weights=WEIGHTS, k=1)[0]


def _payout(triple: Tuple[str, str, str]) -> float:
    return min(SPIN_CAP, PAYTABLE.get(triple, 0.0))


def _symbol_color(sym: str) -> Tuple[int, int, int]:
    if sym == "金":
        return COL_GOLD
    if sym == "7":
        return COL_SEVEN
    if sym == "BAR":
        return COL_BAR
    return COL_MISS


class SlotMachine:
    def __init__(self, session: GameSession):
        self.session = session
        self.initial_gold = session.gold
        self.gold = session.gold
        self.won = 0.0
        self.spin_index = 0
        self.phase = "idle"  # idle | spinning | settled | over
        self.reels: List[str] = ["X", "X", "X"]
        self.targets: List[str] = ["X", "X", "X"]
        self.locked = [False, False, False]
        self.spin_t = 0.0
        self.last_payout = 0.0
        self.log = "空格或点击转轮开始"

        pygame.init()
        pygame.display.set_caption("Adventure - 老虎机")
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.font = load_font(22)
        self.font_sm = load_font(16)
        self.font_lg = load_font(36, bold=True)
        self.font_sym = load_font(40, bold=True)

        self.reel_rects = [
            pygame.Rect(70 + i * 170, 150, 150, 180) for i in range(3)
        ]
        self.spin_btn = pygame.Rect(220, 400, 200, 52)

    def run(self) -> None:
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE:
                        running = False
                    elif e.key == pygame.K_SPACE:
                        self._try_spin()
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    if self.spin_btn.collidepoint(e.pos) or any(
                        r.collidepoint(e.pos) for r in self.reel_rects
                    ):
                        self._try_spin()
            if self.phase == "spinning":
                self._update_spin(dt)
            self._draw()
            if self.phase == "over":
                pygame.time.wait(1400)
                running = False
        self._write_result()

    def _try_spin(self) -> None:
        if self.phase == "over":
            return
        if self.phase == "spinning":
            return
        if self.spin_index >= SPINS_TOTAL:
            self.phase = "over"
            return
        self.targets = [_pick_symbol() for _ in range(3)]
        self.locked = [False, False, False]
        self.spin_t = 0.0
        self.last_payout = 0.0
        self.phase = "spinning"
        self.log = "停轮中…"

    def _update_spin(self, dt: float) -> None:
        self.spin_t += dt
        for i in range(3):
            if self.locked[i]:
                continue
            self.reels[i] = random.choice(SYMBOLS)
            if self.spin_t >= REEL_STOP_S[i]:
                self.reels[i] = self.targets[i]
                self.locked[i] = True
        if all(self.locked):
            triple = (self.reels[0], self.reels[1], self.reels[2])
            pay = _payout(triple)
            self.last_payout = pay
            self.won += pay
            self.gold += pay
            self.spin_index += 1
            if pay > 0:
                self.log = f"+{self._fmt(pay)} 金"
            else:
                self.log = "未中"
            if self.spin_index >= SPINS_TOTAL:
                self.phase = "over"
                self.log = f"本局结束，共赢 {self._fmt(self.won)} 金"
            else:
                self.phase = "idle"

    @staticmethod
    def _fmt(value: float) -> str:
        v = round(float(value), 1)
        if abs(v - int(v)) < 1e-9:
            return str(int(v))
        return f"{v:.1f}"

    def _draw(self) -> None:
        self.screen.fill(COL_BG)
        title = self.font_lg.render("老虎机", True, COL_TEXT)
        self.screen.blit(title, (W // 2 - title.get_width() // 2, 24))

        info = self.font_sm.render(
            f"已转 {self.spin_index} / {SPINS_TOTAL} 把"
            f"    本局已赢 {self._fmt(self.won)} 金",
            True,
            COL_MUTED,
        )
        self.screen.blit(info, (W // 2 - info.get_width() // 2, 78))

        pay_hint = self.font_sm.render(
            "三连：BAR=2  金=6  7=20（单把上限 20）",
            True,
            COL_MUTED,
        )
        self.screen.blit(pay_hint, (W // 2 - pay_hint.get_width() // 2, 108))

        for i, rect in enumerate(self.reel_rects):
            pygame.draw.rect(self.screen, COL_PANEL, rect, border_radius=14)
            inner = rect.inflate(-12, -12)
            pygame.draw.rect(self.screen, COL_REEL, inner, border_radius=10)
            border_col = COL_WIN if (
                self.phase != "spinning" and self.last_payout > 0 and all(
                    s == self.reels[0] for s in self.reels
                )
            ) else COL_LINE
            pygame.draw.rect(self.screen, border_col, inner, width=2, border_radius=10)
            sym = self.reels[i]
            label = self.font_sym.render(sym, True, _symbol_color(sym))
            self.screen.blit(
                label,
                (
                    inner.centerx - label.get_width() // 2,
                    inner.centery - label.get_height() // 2,
                ),
            )

        pygame.draw.rect(self.screen, (58, 92, 255), self.spin_btn, border_radius=10)
        if self.phase == "over":
            btn_txt = "结算中"
        elif self.phase == "spinning":
            btn_txt = "转动中"
        elif self.spin_index >= SPINS_TOTAL:
            btn_txt = "结束"
        else:
            btn_txt = "转一把（空格）"
        btn_label = self.font.render(btn_txt, True, COL_TEXT)
        self.screen.blit(
            btn_label,
            (
                self.spin_btn.centerx - btn_label.get_width() // 2,
                self.spin_btn.centery - btn_label.get_height() // 2,
            ),
        )

        log_col = COL_WIN if self.last_payout > 0 and self.phase != "spinning" else COL_MUTED
        log = self.font.render(self.log, True, log_col)
        self.screen.blit(log, (W // 2 - log.get_width() // 2, 468))
        pygame.display.flip()

    def _write_result(self) -> None:
        result = GameResult(
            session_id=self.session.session_id,
            gold_delta=round(self.gold - self.initial_gold, 1),
            diamond_delta=0.0,
            waves_cleared=self.spin_index,
            message=f"老虎机 {self.spin_index}/{SPINS_TOTAL} 把，赢得 {self._fmt(self.won)} 金币",
        )
        result.write(self.session.result_path())


def run_session(session_path: str | Path) -> int:
    p = Path(session_path)
    if not p.exists():
        print(f"会话文件不存在: {p}")
        return 2
    try:
        s = GameSession.read(p)
        game = SlotMachine(s)
        game.run()
        return 0
    except Exception as e:
        print(f"游戏运行错误: {e}")
        return 1


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python -m games.slot_machine <session_in.json>")
        raise SystemExit(2)
    raise SystemExit(run_session(sys.argv[1]))


if __name__ == "__main__":
    main()

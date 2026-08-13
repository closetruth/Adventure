"""金币老虎机小游戏：入场筹码可调下注，三连按倍数发奖，只结算金币。"""
from __future__ import annotations

import array
import math
import random
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple

try:
    import pygame
except ImportError:
    print("请先安装 pygame-ce: pip install pygame-ce")
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from games.font_util import load_font  # noqa: E402
from src.game_protocol import (  # noqa: E402
    SLOT_JACKPOT_CAP,
    SLOT_JACKPOT_CONTRIB,
    SLOT_JACKPOT_SEED,
    GameResult,
    GameSession,
)

W, H = 640, 640
FPS = 60
SPINS_TOTAL = 8
ENTRY_CHIPS = 10.0
BET_STEPS = (1, 2, 5)
PAY_CAP_MULT = 20.0
SETTLE_MISS_S = 0.85
SETTLE_NEAR_S = 1.15
SETTLE_BAR_S = 1.05
SETTLE_GOLD_S = 1.75
SETTLE_SEVEN_S = 2.80
NEAR_MISS_CHANCE = 0.30

# 赔付 = 倍数 × 下注。7 另加真奖池；抽成 15% 使长期 RTP 仍略亏。
SYMBOLS = ("X", "BAR", "金", "7")
WEIGHTS = (6, 22, 50, 22)
PAYTABLE = {
    ("BAR", "BAR", "BAR"): 2.0,
    ("金", "金", "金"): 6.0,
    ("7", "7", "7"): 6.0,
}
PAY_SYMS = ("BAR", "金", "7")

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
COL_NEAR = (255, 176, 80)
COL_PAYLINE = (255, 214, 102)
COL_HOT = (255, 92, 72)
COL_JACK = (255, 196, 72)
COL_LAST = (255, 120, 70)

# 先快转，再按轴减速咬停；第三轴（尤其 near-miss）最慢
REEL_FAST_S = (0.45, 1.05, 1.70)
REEL_FAST_NEAR_S = (0.45, 1.05, 1.85)
REEL_SPEED0 = (22.0, 19.5, 17.0)
# 进入减速时先把速度压到可读，再慢慢咬停
REEL_DECEL_V = (9.5, 6.5, 3.8)
REEL_DECEL_V_NEAR = (9.5, 6.5, 2.4)
REEL_DECEL_LOOPS = (1, 1, 1)
REEL_DECEL_LOOPS_NEAR = (1, 1, 2)
REEL_NUDGE_PAUSE = (0.0, 0.0, 0.11)
REEL_NUDGE_PAUSE_NEAR = (0.0, 0.0, 0.20)

_SOUND_EXTS = (".wav", ".ogg", ".mp3")


def _pick_symbol() -> str:
    return random.choices(SYMBOLS, weights=WEIGHTS, k=1)[0]


def _payout_mult(triple: Tuple[str, str, str]) -> float:
    return PAYTABLE.get(triple, 0.0)


def _payout(triple: Tuple[str, str, str], bet: float) -> float:
    return min(PAY_CAP_MULT * bet, _payout_mult(triple) * bet)


def _add_to_jackpot(pool: float, bet: float) -> float:
    add = round(float(bet) * SLOT_JACKPOT_CONTRIB, 1)
    return round(min(SLOT_JACKPOT_CAP, max(SLOT_JACKPOT_SEED, pool) + add), 1)


def _symbol_color(sym: str) -> Tuple[int, int, int]:
    if sym == "金":
        return COL_GOLD
    if sym == "7":
        return COL_SEVEN
    if sym == "BAR":
        return COL_BAR
    return COL_MISS


def _adjacent(sym: str, *, below: bool = True) -> str:
    idx = SYMBOLS.index(sym)
    step = 1 if below else -1
    return SYMBOLS[(idx + step) % len(SYMBOLS)]


def _roll_targets() -> Tuple[List[str], bool]:
    """先 RNG 出真实赔付；未中时提高「差一格」观感，不改金额。"""
    a, b, c = _pick_symbol(), _pick_symbol(), _pick_symbol()
    if _payout_mult((a, b, c)) > 0:
        return [a, b, c], False

    near = False
    if a == b and a in PAY_SYMS:
        c = _adjacent(a, below=random.random() < 0.5)
        near = True
    elif random.random() < NEAR_MISS_CHANCE:
        a = b = random.choice(PAY_SYMS)
        c = _adjacent(a, below=random.random() < 0.5)
        near = True
    return [a, b, c], near


def _win_tier(triple: Tuple[str, str, str], pay: float, *, near: bool) -> str:
    if pay <= 0:
        return "near" if near else "miss"
    if triple == ("7", "7", "7"):
        return "seven"
    if triple == ("金", "金", "金"):
        return "gold"
    return "bar"


def _settle_seconds(tier: str) -> float:
    return {
        "seven": SETTLE_SEVEN_S,
        "gold": SETTLE_GOLD_S,
        "bar": SETTLE_BAR_S,
        "near": SETTLE_NEAR_S,
        "miss": SETTLE_MISS_S,
    }.get(tier, SETTLE_MISS_S)


@dataclass
class ReelMotion:
    pos: float = 0.0
    speed: float = 0.0
    accel: float = 0.0
    dest: float = 0.0
    target: int = 0
    mode: str = "lock"  # spin | decel | lock
    fast_s: float = 0.55
    pause: float = 0.0


class SlotSfx:
    """合成短音 + 可选 roll_gold 文件。"""

    def __init__(self) -> None:
        self._ok = False
        self._win_file: Optional[pygame.mixer.Sound] = None
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=256)
            self._tick = self._beep(920, 55, 0.28)
            self._tick_hi = self._beep(1180, 70, 0.32)
            self._crawl = self._beep(740, 35, 0.18)
            self._miss = self._beep(160, 140, 0.34)
            self._near_a = self._beep(640, 90, 0.30)
            self._near_b = self._beep(220, 180, 0.36)
            self._chip = self._beep(1480, 22, 0.14)
            self._win_beep = self._beep(880, 160, 0.40)
            self._win_mid = self._beep(1040, 220, 0.42)
            self._win_big_a = self._beep(620, 200, 0.38)
            self._win_big_b = self._beep(980, 280, 0.42)
            self._win_file = self._load_roll_gold()
            self._ok = True
        except Exception:
            self._ok = False

    @staticmethod
    def _beep(freq: float, ms: int, volume: float) -> pygame.mixer.Sound:
        rate = 22050
        n = max(1, int(rate * ms / 1000))
        amp = int(32000 * volume)
        buf = array.array("h")
        fade = max(1, n // 8)
        for i in range(n):
            env = 1.0
            if i < fade:
                env = i / fade
            elif i > n - fade:
                env = (n - i) / fade
            v = int(amp * env * math.sin(2 * math.pi * freq * i / rate))
            buf.append(max(-32767, min(32767, v)))
        return pygame.mixer.Sound(buffer=buf.tobytes())

    @staticmethod
    def _load_roll_gold() -> Optional[pygame.mixer.Sound]:
        base = ROOT / "assets" / "sounds"
        for ext in _SOUND_EXTS:
            path = base / f"roll_gold{ext}"
            if path.is_file():
                try:
                    return pygame.mixer.Sound(str(path))
                except Exception:
                    return None
        return None

    def play_tick(self, *, last: bool = False) -> None:
        if not self._ok:
            return
        (self._tick_hi if last else self._tick).play()

    def play_crawl(self) -> None:
        if self._ok:
            self._crawl.play()

    def play_miss(self) -> None:
        if self._ok:
            self._miss.play()

    def play_chip(self) -> None:
        if self._ok:
            self._chip.play()

    def play_near(self) -> None:
        if not self._ok:
            return
        self._near_a.play()
        self._near_b.play()

    def play_win(self, tier: str = "bar") -> None:
        if not self._ok:
            return
        if tier == "seven":
            if self._win_file is not None:
                self._win_file.play()
            else:
                self._win_big_a.play()
            self._win_big_b.play()
            return
        if tier == "gold":
            if self._win_file is not None:
                self._win_file.play()
            else:
                self._win_mid.play()
            return
        if self._win_file is not None:
            self._win_file.play()
        else:
            self._win_beep.play()


class SlotMachine:
    def __init__(self, session: GameSession):
        self.session = session
        self.credit = ENTRY_CHIPS
        self.bet = BET_STEPS[0]
        self.spin_bet = self.bet
        self.wagered = 0.0
        self.returned = 0.0
        self.spin_index = 0
        self.phase = "idle"  # idle | spinning | settled | over
        self.reels: List[str] = ["X", "BAR", "金"]
        self.targets: List[str] = ["X", "BAR", "金"]
        self.motion: List[ReelMotion] = [
            ReelMotion(pos=float(SYMBOLS.index(sym)), target=SYMBOLS.index(sym))
            for sym in self.reels
        ]
        self.spin_t = 0.0
        self.settle_t = 0.0
        self.settle_need = SETTLE_MISS_S
        self.last_payout = 0.0
        self.near_miss = False
        self.win_tier = "miss"
        self.log = "选下注，空格转轮。Esc 带走剩余"
        # 筹码滚动 / 跳动（显示值，不改真实 credit）
        self.credit_shown = ENTRY_CHIPS
        self.credit_bounce = 0.0
        start_jp = float(getattr(session, "jackpot", 0) or 0)
        self.jackpot = start_jp if start_jp > 0 else SLOT_JACKPOT_SEED
        self.jackpot_shown = self.jackpot
        self.jackpot_taken = 0.0
        self.heat_flash = 0.0
        self.fx_t = 0.0
        self.shake = 0.0
        self.win_count_shown = 0.0
        self.win_count_target = 0.0

        pygame.init()
        pygame.display.set_caption("Adventure - 老虎机")
        self.sfx = SlotSfx()
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.font = load_font(22)
        self.font_sm = load_font(16)
        self.font_lg = load_font(36, bold=True)
        self.font_xl = load_font(52, bold=True)
        self.font_sym = load_font(34, bold=True)
        self.font_side = load_font(18, bold=True)

        self.reel_rects = [
            pygame.Rect(70 + i * 170, 178, 150, 210) for i in range(3)
        ]
        self.bet_minus_btn = pygame.Rect(70, 488, 56, 52)
        self.bet_plus_btn = pygame.Rect(246, 488, 56, 52)
        self.bet_label_rect = pygame.Rect(132, 488, 108, 52)
        self.spin_btn = pygame.Rect(330, 488, 240, 52)

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
                    elif e.key in (pygame.K_LEFT, pygame.K_MINUS):
                        self._nudge_bet(-1)
                    elif e.key in (pygame.K_RIGHT, pygame.K_EQUALS, pygame.K_PLUS):
                        self._nudge_bet(1)
                    elif e.key == pygame.K_1:
                        self._set_bet(1)
                    elif e.key == pygame.K_2:
                        self._set_bet(2)
                    elif e.key == pygame.K_5:
                        self._set_bet(5)
                    elif e.key == pygame.K_SPACE:
                        self._try_spin()
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    if self.bet_minus_btn.collidepoint(e.pos):
                        self._nudge_bet(-1)
                    elif self.bet_plus_btn.collidepoint(e.pos):
                        self._nudge_bet(1)
                    elif self.spin_btn.collidepoint(e.pos) or any(
                        r.collidepoint(e.pos) for r in self.reel_rects
                    ):
                        self._try_spin()
            self._update_fx(dt)
            if self.phase == "spinning":
                self._update_spin(dt)
            elif self.phase == "settled":
                self._update_settle(dt)
            self._draw()
            if self.phase == "over" and self.settle_t >= self.settle_need:
                pygame.time.wait(700)
                running = False
        self._write_result()

    def _can_change_bet(self) -> bool:
        return self.phase == "idle"

    def _max_affordable_bet(self) -> int:
        affordable = [b for b in BET_STEPS if b <= self.credit + 1e-9]
        return affordable[-1] if affordable else 0

    def _clamp_bet(self) -> None:
        cap = self._max_affordable_bet()
        if cap <= 0:
            self.bet = BET_STEPS[0]
            return
        if self.bet not in BET_STEPS or self.bet > cap:
            self.bet = max(b for b in BET_STEPS if b <= cap)

    def _set_bet(self, value: int) -> None:
        if not self._can_change_bet():
            return
        if value in BET_STEPS and value <= self.credit + 1e-9 and value != self.bet:
            self.bet = value
            self.sfx.play_tick()

    def _nudge_bet(self, direction: int) -> None:
        if not self._can_change_bet():
            return
        idx = BET_STEPS.index(self.bet) if self.bet in BET_STEPS else 0
        idx = max(0, min(len(BET_STEPS) - 1, idx + direction))
        self._set_bet(BET_STEPS[idx])

    def _try_spin(self) -> None:
        if self.phase in ("over", "spinning", "settled"):
            return
        self._clamp_bet()
        if self.spin_index >= SPINS_TOTAL or self.credit < 1:
            self.phase = "over"
            self.settle_t = self.settle_need
            return
        if self.credit + 1e-9 < self.bet:
            self.log = f"筹码不够，先把下注调到 {self._max_affordable_bet()}"
            return
        self.spin_bet = self.bet
        self.credit = round(self.credit - self.spin_bet, 1)
        self.wagered = round(self.wagered + self.spin_bet, 1)
        self.credit_bounce = 0.55
        last = self._is_last_spin()
        self.targets, self.near_miss = _roll_targets()
        self.jackpot = _add_to_jackpot(self.jackpot, self.spin_bet)
        self.jackpot_taken = 0.0
        fast = REEL_FAST_NEAR_S if self.near_miss else REEL_FAST_S
        self.spin_t = 0.0
        self.settle_t = 0.0
        self.last_payout = 0.0
        self.win_tier = "miss"
        self.win_count_shown = 0.0
        self.win_count_target = 0.0
        self.shake = 0.0
        self.phase = "spinning"
        if last:
            self.log = f"最后一把  下注 {self._fmt(self.spin_bet)}"
        else:
            self.log = f"下注 {self._fmt(self.spin_bet)}  停轮中…"
        for i, target in enumerate(self.targets):
            m = self.motion[i]
            m.target = SYMBOLS.index(target)
            m.pos = float(SYMBOLS.index(self.reels[i])) + random.random() * 0.2
            m.speed = REEL_SPEED0[i] + random.uniform(-1.5, 1.5)
            m.accel = 0.0
            m.dest = 0.0
            m.pause = 0.0
            m.fast_s = fast[i]
            m.mode = "spin"

    def _begin_decel(self, i: int) -> None:
        m = self.motion[i]
        n = len(SYMBOLS)
        cap = REEL_DECEL_V_NEAR[i] if self.near_miss else REEL_DECEL_V[i]
        m.speed = min(m.speed, cap)
        frac = (m.target - (m.pos % n)) % n
        if frac < 0.4:
            frac += n
        loops = REEL_DECEL_LOOPS_NEAR[i] if self.near_miss else REEL_DECEL_LOOPS[i]
        m.dest = m.pos + frac + loops * n
        dist = max(1.0, m.dest - m.pos)
        m.accel = -(m.speed ** 2) / (2.0 * dist)
        m.pause = 0.0
        m.mode = "decel"

    def _update_spin(self, dt: float) -> None:
        self.spin_t += dt
        n = len(SYMBOLS)
        for i, m in enumerate(self.motion):
            if m.mode == "lock":
                continue
            if m.pause > 0:
                m.pause -= dt
                continue
            old_pos = m.pos
            if m.mode == "spin":
                m.pos += m.speed * dt
                if self.spin_t >= m.fast_s:
                    self._begin_decel(i)
            elif m.mode == "decel":
                m.speed = max(0.0, m.speed + m.accel * dt)
                m.pos += m.speed * dt
                crossed = math.floor(m.pos) != math.floor(old_pos)
                if crossed and m.speed < 6.0:
                    self.sfx.play_crawl()
                    pause = (
                        REEL_NUDGE_PAUSE_NEAR[i]
                        if self.near_miss
                        else REEL_NUDGE_PAUSE[i]
                    )
                    if pause > 0:
                        m.pause = pause
                if m.speed <= 0.10 or m.pos >= m.dest - 0.02:
                    landed = math.floor(m.dest)
                    m.pos = float(landed + (m.target - landed % n) % n)
                    m.speed = 0.0
                    m.mode = "lock"
                    self.reels[i] = SYMBOLS[m.target]
                    self.sfx.play_tick(last=(i == 2))
                    if i == 2:
                        self._resolve_spin()
            self.reels[i] = SYMBOLS[int(math.floor(m.pos)) % n]

    def _resolve_spin(self) -> None:
        triple = (self.reels[0], self.reels[1], self.reels[2])
        pay = _payout(triple, self.spin_bet)
        self.jackpot_taken = 0.0
        if triple == ("7", "7", "7"):
            self.jackpot_taken = round(self.jackpot, 1)
            pay = round(pay + self.jackpot_taken, 1)
            self.jackpot = SLOT_JACKPOT_SEED
        self.last_payout = pay
        self.win_tier = _win_tier(triple, pay, near=self.near_miss)
        self.returned = round(self.returned + pay, 1)
        self.credit = round(self.credit + pay, 1)
        self.spin_index += 1
        self._clamp_bet()
        if self.near_miss and pay <= 0:
            self.heat_flash = 0.20
        self.settle_need = _settle_seconds(self.win_tier)
        self.win_count_target = pay
        self.win_count_shown = 0.0
        stake = self._fmt(self.spin_bet)
        if self.win_tier == "seven":
            self.log = (
                f"大奖  下注 {stake}  +{self._fmt(pay)}"
                f"  (含奖池 {self._fmt(self.jackpot_taken)})"
            )
            self.credit_bounce = 1.0
            self.shake = 7.5
            self.sfx.play_win("seven")
        elif self.win_tier == "gold":
            self.log = f"金三连  下注 {stake}  +{self._fmt(pay)}"
            self.credit_bounce = 0.85
            self.shake = 3.2
            self.sfx.play_win("gold")
        elif self.win_tier == "bar":
            self.log = f"下注 {stake}  +{self._fmt(pay)} 金"
            self.credit_bounce = 0.65
            self.shake = 1.2
            self.sfx.play_win("bar")
        elif self.near_miss:
            self.log = f"下注 {stake}  就差一格！"
            self.sfx.play_near()
        else:
            self.log = f"下注 {stake}  未中"
            self.sfx.play_miss()
        self.phase = "settled"
        self.settle_t = 0.0

    def _pool_heat(self) -> float:
        span = max(0.1, SLOT_JACKPOT_CAP - SLOT_JACKPOT_SEED)
        return max(0.06, min(0.97, (self.jackpot - SLOT_JACKPOT_SEED) / span))

    def _is_last_spin(self) -> bool:
        return self.spin_index >= SPINS_TOTAL - 1 and self.spin_index < SPINS_TOTAL

    def _net(self) -> float:
        return round(self.credit - ENTRY_CHIPS, 1)

    def _update_fx(self, dt: float) -> None:
        self.fx_t += dt
        if self.heat_flash > 0:
            self.heat_flash = max(0.0, self.heat_flash - dt * 0.35)
        self._lerp_number("jackpot_shown", self.jackpot, dt, speed_up=14.0, speed_down=18.0)
        old_shown = self.credit_shown
        self._lerp_number(
            "credit_shown",
            self.credit,
            dt,
            speed_up=max(2.6, abs(self.credit - self.credit_shown) * 1.25),
            speed_down=22.0,
        )
        if math.floor(self.credit_shown + 1e-6) != math.floor(old_shown + 1e-6):
            self.sfx.play_chip()
            self.credit_bounce = max(self.credit_bounce, 0.35)
        if self.credit_bounce > 0:
            self.credit_bounce = max(0.0, self.credit_bounce - dt * 2.4)
        if self.shake > 0:
            self.shake = max(0.0, self.shake - dt * 10.0)
        if self.win_count_target > 0 and self.phase == "settled":
            self._lerp_number(
                "win_count_shown",
                self.win_count_target,
                dt,
                speed_up=max(4.0, self.win_count_target * 1.6),
                speed_down=20.0,
            )

    def _lerp_number(
        self,
        attr: str,
        target: float,
        dt: float,
        *,
        speed_up: float,
        speed_down: float,
    ) -> None:
        cur = float(getattr(self, attr))
        diff = target - cur
        if abs(diff) < 0.04:
            setattr(self, attr, round(target, 1))
            return
        rate = speed_up if diff > 0 else speed_down
        step = math.copysign(min(abs(diff), rate * dt), diff)
        setattr(self, attr, cur + step)

    def _update_settle(self, dt: float) -> None:
        self.settle_t += dt
        if self.settle_t < self.settle_need:
            return
        if self.spin_index >= SPINS_TOTAL or self.credit < 1:
            self.phase = "over"
            if self.credit < 1:
                self.log = "筹码输光了"
            else:
                self.log = f"本局结束，剩余 {self._fmt(self.credit)} 金"
        else:
            self.phase = "idle"
            self.shake = 0.0

    @staticmethod
    def _fmt(value: float) -> str:
        v = round(float(value), 1)
        if abs(v - int(v)) < 1e-9:
            return str(int(v))
        return f"{v:.1f}"

    def _draw(self) -> None:
        last = self._is_last_spin()
        self.screen.fill(COL_BG)
        if last:
            pulse = 0.55 + 0.45 * abs(math.sin(self.fx_t * 4.2))
            frame = (
                int(COL_LAST[0] * pulse + 40),
                int(COL_LAST[1] * pulse + 20),
                int(COL_LAST[2] * pulse + 16),
            )
            pygame.draw.rect(self.screen, frame, pygame.Rect(6, 6, W - 12, H - 12), width=4, border_radius=12)

        title = self.font_lg.render("老虎机", True, COL_TEXT)
        self.screen.blit(title, (W // 2 - title.get_width() // 2, 10))
        self._draw_jackpot_row()
        self._draw_credit_row(last=last)

        sx = int(math.sin(self.fx_t * 52.0) * self.shake)
        sy = int(math.cos(self.fx_t * 41.0) * self.shake * 0.7)
        win_pulse = 0.0
        if self.phase == "settled" and self.last_payout > 0:
            win_pulse = 0.5 + 0.5 * abs(math.sin(self.fx_t * (7.0 if self.win_tier == "seven" else 5.0)))

        for i, base_rect in enumerate(self.reel_rects):
            rect = base_rect.move(sx, sy)
            pygame.draw.rect(self.screen, COL_PANEL, rect, border_radius=14)
            inner = rect.inflate(-10, -10)
            pygame.draw.rect(self.screen, COL_REEL, inner, border_radius=10)
            spinning = self.phase == "spinning" and self.motion[i].mode != "lock"
            self._draw_reel_window(inner, self.motion[i].pos, spinning=spinning, win_pulse=win_pulse)

            if last and self.phase != "settled":
                border = COL_LAST
            elif self.phase != "spinning":
                if self.last_payout > 0:
                    border = COL_SEVEN if self.win_tier == "seven" else COL_WIN
                elif self.near_miss:
                    border = COL_NEAR
                else:
                    border = COL_LINE
            elif self.motion[i].mode == "lock":
                border = COL_PAYLINE
            elif self.motion[i].mode == "decel":
                border = COL_NEAR if self.near_miss and i == 2 else COL_PAYLINE
            else:
                border = COL_LINE
            width = 3 if (win_pulse > 0.7 or last) else 2
            pygame.draw.rect(self.screen, border, inner, width=width, border_radius=10)

        log_col = COL_MUTED
        if last and self.phase in ("idle", "spinning"):
            log_col = COL_LAST
        elif self.phase != "spinning":
            if self.last_payout > 0:
                log_col = COL_SEVEN if self.win_tier == "seven" else COL_WIN
            elif self.near_miss:
                log_col = COL_NEAR
        log = self.font.render(self.log, True, log_col)
        self.screen.blit(log, (W // 2 - log.get_width() // 2, 398))

        self._draw_controls(last=last)
        if self.phase == "settled" and self.win_tier in ("gold", "seven"):
            self._draw_win_overlay()
        pygame.display.flip()

    def _draw_jackpot_row(self) -> None:
        row = pygame.Rect(40, 54, W - 80, 44)
        pygame.draw.rect(self.screen, COL_PANEL, row, border_radius=10)
        jack_l = self.font_sm.render("奖池", True, COL_MUTED)
        self.screen.blit(jack_l, (row.x + 12, row.y + 14))
        jack_n = self.font_lg.render(self._fmt(self.jackpot_shown), True, COL_JACK)
        self.screen.blit(jack_n, (row.x + 58, row.y + 4))
        heat = min(0.97, self._pool_heat() + self.heat_flash)
        heat_label = "将满" if heat >= 0.82 else ("偏满" if heat >= 0.45 else "累计")
        heat_col = COL_HOT if heat >= 0.82 else (COL_NEAR if heat >= 0.45 else COL_MUTED)
        ht = self.font_sm.render(heat_label, True, heat_col)
        bar = pygame.Rect(row.right - 168, row.y + 14, 110, 16)
        pygame.draw.rect(self.screen, (22, 24, 36), bar, border_radius=8)
        fill_w = max(4, int(bar.width * heat))
        fill_col = (
            COL_HOT if heat >= 0.82
            else (COL_NEAR if heat >= 0.45 else (90, 140, 200))
        )
        pygame.draw.rect(
            self.screen,
            fill_col,
            pygame.Rect(bar.x, bar.y, fill_w, bar.height),
            border_radius=8,
        )
        self.screen.blit(ht, (bar.right + 8, row.y + 12))
        tag = self.font_sm.render("热度", True, COL_MUTED)
        self.screen.blit(tag, (bar.x - tag.get_width() - 8, row.y + 12))

    def _draw_credit_row(self, *, last: bool) -> None:
        bounce = 1.0 + 0.22 * self.credit_bounce * abs(math.sin(self.fx_t * 18.0 + 0.4))
        rising = self.credit > self.credit_shown + 0.05
        chip_col = COL_GOLD if rising or self.credit_bounce > 0.2 else COL_TEXT
        y_off = int((bounce - 1.0) * -18)
        chip_txt = self.font_lg.render(self._fmt(self.credit_shown), True, chip_col)
        label = self.font_sm.render("本机", True, COL_MUTED)
        unit = self.font_sm.render("金", True, COL_MUTED)
        box = pygame.Rect(40, 106, 210, 42)
        pygame.draw.rect(self.screen, (28, 32, 48), box, border_radius=10)
        self.screen.blit(label, (box.x + 10, box.y + 12))
        self.screen.blit(
            chip_txt,
            (box.x + 52, box.y + 4 + y_off),
        )
        self.screen.blit(unit, (box.right - 28, box.y + 12))

        net = self._net()
        net_txt = f"+{self._fmt(net)}" if net > 0 else self._fmt(net)
        spins = f"{self.spin_index}/{SPINS_TOTAL}"
        if last:
            spins_l = self.font.render("最后一把", True, COL_LAST)
        else:
            spins_l = self.font_sm.render(f"已转 {spins}", True, COL_MUTED)
        net_l = self.font_sm.render(f"净利 {net_txt}", True, COL_MUTED)
        self.screen.blit(spins_l, (270, 114 if last else 118))
        self.screen.blit(net_l, (430, 118))

        pay_hint = self.font_sm.render(
            f"BAR x{int(PAYTABLE[('BAR','BAR','BAR')])}  "
            f"金 x{int(PAYTABLE[('金','金','金')])}  "
            f"7 x{int(PAYTABLE[('7','7','7')])}+奖池",
            True,
            COL_MUTED,
        )
        self.screen.blit(pay_hint, (W // 2 - pay_hint.get_width() // 2, 150))

    def _draw_controls(self, *, last: bool) -> None:
        can_bet = self.phase == "idle"
        minus_col = (58, 92, 255) if can_bet and self.bet > BET_STEPS[0] else (42, 48, 70)
        plus_col = (
            (58, 92, 255)
            if can_bet and self.bet < self._max_affordable_bet()
            else (42, 48, 70)
        )
        pygame.draw.rect(self.screen, minus_col, self.bet_minus_btn, border_radius=10)
        pygame.draw.rect(self.screen, COL_PANEL, self.bet_label_rect, border_radius=10)
        pygame.draw.rect(self.screen, plus_col, self.bet_plus_btn, border_radius=10)
        minus_l = self.font_lg.render("-", True, COL_TEXT)
        plus_l = self.font_lg.render("+", True, COL_TEXT)
        bet_l = self.font.render(f"下注 {self._fmt(self.bet)}", True, COL_GOLD)
        self.screen.blit(
            minus_l,
            (
                self.bet_minus_btn.centerx - minus_l.get_width() // 2,
                self.bet_minus_btn.centery - minus_l.get_height() // 2 - 2,
            ),
        )
        self.screen.blit(
            plus_l,
            (
                self.bet_plus_btn.centerx - plus_l.get_width() // 2,
                self.bet_plus_btn.centery - plus_l.get_height() // 2 - 2,
            ),
        )
        self.screen.blit(
            bet_l,
            (
                self.bet_label_rect.centerx - bet_l.get_width() // 2,
                self.bet_label_rect.centery - bet_l.get_height() // 2,
            ),
        )

        spin_col = COL_LAST if last and self.phase == "idle" else (58, 92, 255)
        pygame.draw.rect(self.screen, spin_col, self.spin_btn, border_radius=10)
        if self.phase == "over":
            btn_txt = "结算中"
        elif self.phase == "spinning":
            btn_txt = "最后一把" if last else "转动中"
        elif self.phase == "settled":
            btn_txt = "…"
        else:
            btn_txt = "最后一把" if last else "转（空格）"
        btn_label = self.font.render(btn_txt, True, COL_TEXT)
        self.screen.blit(
            btn_label,
            (
                self.spin_btn.centerx - btn_label.get_width() // 2,
                self.spin_btn.centery - btn_label.get_height() // 2,
            ),
        )
        hint = self.font_sm.render("左右键调下注    Esc 带走剩余金币", True, COL_MUTED)
        self.screen.blit(hint, (W // 2 - hint.get_width() // 2, 556))

    def _draw_win_overlay(self) -> None:
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        alpha = 90 if self.win_tier == "gold" else 130
        veil.fill((8, 8, 14, alpha))
        self.screen.blit(veil, (0, 0))
        if self.win_tier == "seven":
            headline = self.font_xl.render("奖池大奖", True, COL_SEVEN)
            sub = self.font_lg.render(f"+{self._fmt(self.win_count_shown)}", True, COL_GOLD)
            extra = self.font_sm.render(
                f"含奖池 {self._fmt(self.jackpot_taken)}",
                True,
                COL_JACK,
            )
            self.screen.blit(extra, (W // 2 - extra.get_width() // 2, 372))
        else:
            headline = self.font_lg.render("金  三连", True, COL_GOLD)
            sub = self.font.render(f"+{self._fmt(self.win_count_shown)}", True, COL_WIN)
        self.screen.blit(headline, (W // 2 - headline.get_width() // 2, 250))
        self.screen.blit(sub, (W // 2 - sub.get_width() // 2, 318))

    def _draw_reel_window(
        self,
        inner: pygame.Rect,
        pos: float,
        *,
        spinning: bool,
        win_pulse: float = 0.0,
    ) -> None:
        n = len(SYMBOLS)
        row_h = inner.height / 3
        pay_y = inner.centery - row_h / 2
        glow = int(48 + 50 * win_pulse)
        pygame.draw.rect(
            self.screen,
            (glow, 42, 22),
            pygame.Rect(inner.x + 4, int(pay_y) + 3, inner.width - 8, int(row_h) - 6),
            border_radius=6,
        )
        line_w = 3 if win_pulse > 0.4 else 2
        pygame.draw.line(
            self.screen, COL_PAYLINE,
            (inner.x + 6, int(pay_y)),
            (inner.right - 6, int(pay_y)),
            line_w,
        )
        pygame.draw.line(
            self.screen, COL_PAYLINE,
            (inner.x + 6, int(pay_y + row_h)),
            (inner.right - 6, int(pay_y + row_h)),
            line_w,
        )

        base = math.floor(pos)
        frac = pos - base
        old_clip = self.screen.get_clip()
        self.screen.set_clip(inner)
        for k in range(base - 2, base + 3):
            sym = SYMBOLS[k % n]
            cy = inner.centery - frac * row_h + (k - base) * row_h
            on_pay = abs(cy - inner.centery) < row_h * 0.45
            font = self.font_sym if on_pay else self.font_side
            color = _symbol_color(sym)
            if not on_pay:
                color = tuple(max(40, c - 70) for c in color)
            elif spinning:
                color = tuple(min(255, c + 24) for c in color)
            elif on_pay and win_pulse > 0:
                boost = int(40 * win_pulse)
                color = tuple(min(255, c + boost) for c in color)
            label = font.render(sym, True, color)
            self.screen.blit(
                label,
                (inner.centerx - label.get_width() // 2, cy - label.get_height() / 2),
            )
        self.screen.set_clip(old_clip)

    def _write_result(self) -> None:
        result = GameResult(
            session_id=self.session.session_id,
            gold_delta=round(self.credit, 1),
            diamond_delta=0.0,
            waves_cleared=self.spin_index,
            jackpot=round(self.jackpot, 1),
            message=(
                f"老虎机 {self.spin_index}/{SPINS_TOTAL} 把，"
                f"共下注 {self._fmt(self.wagered)}，"
                f"带回 {self._fmt(self.credit)} 金币，"
                f"奖池 {self._fmt(self.jackpot)}"
            ),
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

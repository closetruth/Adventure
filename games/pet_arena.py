"""小动物竞技场 — pygame 自走棋小游戏。

从主程序传入会话 JSON 路径，结束时写出结算 JSON（金币/钻石净变化）。

操作：
  标题：空格开始（消耗入场费）
  商店：1/2/3 购买宠物，空格开始本波战斗
  战斗：自动进行
  ESC：退出并结算
"""
from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import pygame
except ImportError:
    print("请先安装 pygame-ce（Python 3.14 必须用 ce 版）:")
    print("  pip install pygame-ce")
    raise SystemExit(1)

# 把项目根目录加入 path，便于读取 game_protocol
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.game_protocol import GameResult, GameSession  # noqa: E402

# ---------- 配置 ----------
W, H = 960, 640
FPS = 60
ENTRY_FEE = 10
FONT_NAMES = ("microsoftyaheiui", "microsoftyahei", "simhei", "arial")

COL_BG = (22, 24, 36)
COL_PANEL = (35, 38, 58)
COL_TEXT = (240, 242, 250)
COL_MUTED = (160, 168, 190)
COL_GOLD = (255, 213, 79)
COL_DIAM = (125, 211, 252)
COL_HP_BG = (50, 54, 72)
COL_HP = (111, 231, 133)
COL_ENEMY = (255, 120, 120)


@dataclass
class PetSpec:
    key: str
    name: str
    cost: int
    hp: int
    atk: int
    spd: float
    color: Tuple[int, int, int]


SPECS = [
    PetSpec("cat", "小猫", 5, 32, 9, 1.35, (255, 183, 77)),
    PetSpec("dog", "小狗", 8, 48, 13, 1.05, (129, 199, 132)),
    PetSpec("bear", "小熊", 12, 78, 11, 0.75, (149, 117, 205)),
]


@dataclass
class Fighter:
    spec: PetSpec
    hp: float
    max_hp: float
    atk: int
    spd: float
    x: float
    y: float
    side: str  # "player" | "enemy"
    attack_cd: float = 0.0
    alive: bool = True

    @classmethod
    def from_spec(cls, spec: PetSpec, side: str, x: float, y: float) -> "Fighter":
        return cls(
            spec=spec,
            hp=float(spec.hp),
            max_hp=float(spec.hp),
            atk=spec.atk,
            spd=spec.spd,
            x=x,
            y=y,
            side=side,
        )


def load_font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in FONT_NAMES:
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.SysFont(None, size, bold=bold)


class PetArenaGame:
    def __init__(self, session: GameSession):
        self.session = session
        self.initial_gold = session.gold
        self.initial_diamond = session.diamond
        self.gold = session.gold
        self.diamond = session.diamond

        self.wave = 0
        self.waves_cleared = 0
        self.phase = "title"  # title | shop | battle | over
        self.team: List[Fighter] = []
        self.enemies: List[Fighter] = []
        self.battle_log = ""
        self.over_msg = ""
        self.entry_paid = False
        self.shop_flash = 0.0

        pygame.init()
        pygame.display.set_caption("Adventure - 小动物竞技场")
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.font = load_font(22)
        self.font_lg = load_font(32, bold=True)
        self.font_sm = load_font(18)

    def run(self) -> None:
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    else:
                        self._on_key(event.key)

            if self.phase == "battle":
                self._update_battle(dt)
            self._draw()
            if self.phase == "over":
                pygame.time.wait(1200)
                running = False

        self._write_result()

    def _on_key(self, key: int) -> None:
        if self.phase == "title":
            if key == pygame.K_SPACE:
                if self.gold < ENTRY_FEE:
                    self.battle_log = f"金币不足，需要 {ENTRY_FEE} 入场"
                    return
                self.gold -= ENTRY_FEE
                self.entry_paid = True
                self.phase = "shop"
                self.wave = 1
                self.battle_log = "在商店购买宠物，空格开始战斗"
        elif self.phase == "shop":
            if key == pygame.K_1:
                self._buy(0)
            elif key == pygame.K_2:
                self._buy(1)
            elif key == pygame.K_3:
                self._buy(2)
            elif key == pygame.K_SPACE:
                if not self.team:
                    self.battle_log = "至少购买一只宠物"
                    return
                self._start_battle()
        elif self.phase == "over":
            if key == pygame.K_SPACE:
                pass

    def _buy(self, idx: int) -> None:
        if len(self.team) >= 5:
            self.battle_log = "队伍已满（最多 5 只）"
            return
        spec = SPECS[idx]
        if self.gold < spec.cost:
            self.battle_log = f"金币不足，{spec.name} 需要 {spec.cost}"
            return
        self.gold -= spec.cost
        y = 280 + len(self.team) * 56
        self.team.append(Fighter.from_spec(spec, "player", 140, y))
        self.battle_log = f"招募了 {spec.name}"
        self.shop_flash = 0.25

    def _start_battle(self) -> None:
        self.phase = "battle"
        self.enemies = self._spawn_enemies(self.wave)
        # 重置玩家位置
        for i, f in enumerate(self.team):
            f.x = 140
            f.y = 200 + i * 70
            f.attack_cd = random.uniform(0, 0.5)
            f.alive = f.hp > 0
        self.battle_log = f"第 {self.wave} 波战斗开始！"

    def _spawn_enemies(self, wave: int) -> List[Fighter]:
        count = min(1 + wave // 2, 5)
        out: List[Fighter] = []
        for i in range(count):
            spec = random.choice(SPECS)
            mult = 1.0 + wave * 0.12
            f = Fighter.from_spec(spec, "enemy", W - 160, 200 + i * 70)
            f.max_hp = f.hp = spec.hp * mult
            f.atk = int(spec.atk * (1 + wave * 0.08))
            out.append(f)
        return out

    def _update_battle(self, dt: float) -> None:
        all_f = [f for f in self.team + self.enemies if f.alive]
        if not any(f.side == "player" for f in self.team if f.alive):
            self.phase = "over"
            self.over_msg = f"战败于第 {self.wave} 波"
            return
        if not any(f.side == "enemy" for f in self.enemies if f.alive):
            reward = 4 + self.wave * 2
            self.gold += reward
            self.waves_cleared = self.wave
            if self.wave % 5 == 0:
                self.diamond += 1
                self.battle_log = f"通关第 {self.wave} 波！+{reward} 金币，+1 钻石"
            else:
                self.battle_log = f"通关第 {self.wave} 波！+{reward} 金币"
            for f in self.team:
                f.hp = f.max_hp
                f.alive = True
            self.wave += 1
            self.phase = "shop"
            return

        for f in all_f:
            f.attack_cd -= dt
            if f.attack_cd > 0:
                continue
            targets = self.enemies if f.side == "player" else self.team
            live = [t for t in targets if t.alive]
            if not live:
                continue
            target = min(live, key=lambda t: abs(t.x - f.x) + abs(t.y - f.y) * 0.3)
            target.hp -= f.atk
            f.attack_cd = 1.0 / f.spd
            if target.hp <= 0:
                target.hp = 0
                target.alive = False

    def _draw(self) -> None:
        self.screen.fill(COL_BG)
        self._draw_header()

        if self.phase == "title":
            self._draw_center([
                "小动物竞技场",
                "",
                f"入场费 {ENTRY_FEE} 金币",
                "空格开始  |  ESC 退出",
            ])
        elif self.phase == "shop":
            self._draw_shop()
        elif self.phase == "battle":
            self._draw_battle()
        elif self.phase == "over":
            self._draw_center([self.over_msg, "", "正在结算..."])

        self._draw_footer()
        pygame.display.flip()

    def _draw_header(self) -> None:
        pygame.draw.rect(self.screen, COL_PANEL, (0, 0, W, 52))
        t1 = self.font.render(f"金币 {self.gold}", True, COL_GOLD)
        t2 = self.font.render(f"钻石 {self.diamond}", True, COL_DIAM)
        tw = self.font.render(f"第 {max(1, self.wave)} 波", True, COL_TEXT)
        self.screen.blit(t1, (16, 12))
        self.screen.blit(t2, (130, 12))
        self.screen.blit(tw, (W // 2 - tw.get_width() // 2, 12))

    def _draw_footer(self) -> None:
        pygame.draw.rect(self.screen, COL_PANEL, (0, H - 44, W, 44))
        msg = self.battle_log or "ESC 退出并结算到背包"
        surf = self.font_sm.render(msg, True, COL_MUTED)
        self.screen.blit(surf, (16, H - 34))

    def _draw_center(self, lines: List[str]) -> None:
        y = H // 2 - len(lines) * 22
        for line in lines:
            surf = self.font_lg.render(line, True, COL_TEXT)
            self.screen.blit(surf, (W // 2 - surf.get_width() // 2, y))
            y += 44

    def _draw_shop(self) -> None:
        title = self.font_lg.render("商店 — 购买宠物", True, COL_TEXT)
        self.screen.blit(title, (40, 72))
        hint = self.font_sm.render("1/2/3 购买  |  空格开始战斗  |  最多 5 只", True, COL_MUTED)
        self.screen.blit(hint, (40, 118))

        for i, spec in enumerate(SPECS):
            y = 160 + i * 72
            pygame.draw.rect(self.screen, COL_PANEL, (40, y, 400, 60), border_radius=8)
            name = self.font.render(f"[{i+1}] {spec.name}  -{spec.cost} 金", True, COL_TEXT)
            stat = self.font_sm.render(
                f"生命 {spec.hp}  攻击 {spec.atk}  攻速 {spec.spd:.2f}",
                True,
                COL_MUTED,
            )
            pygame.draw.circle(self.screen, spec.color, (420, y + 30), 22)
            self.screen.blit(name, (52, y + 8))
            self.screen.blit(stat, (52, y + 34))

        self._draw_team_preview(480, 160)

    def _draw_team_preview(self, x: int, y: int) -> None:
        lab = self.font.render("我的队伍", True, COL_TEXT)
        self.screen.blit(lab, (x, y))
        if not self.team:
            empty = self.font_sm.render("（空）", True, COL_MUTED)
            self.screen.blit(empty, (x, y + 36))
            return
        for i, f in enumerate(self.team):
            row = y + 40 + i * 48
            pygame.draw.rect(self.screen, COL_PANEL, (x, row, 420, 42), border_radius=6)
            pygame.draw.circle(self.screen, f.spec.color, (x + 24, row + 21), 16)
            t = self.font_sm.render(
                f"{f.spec.name}  HP {int(f.hp)}/{int(f.max_hp)}",
                True,
                COL_TEXT,
            )
            self.screen.blit(t, (x + 48, row + 10))

    def _draw_battle(self) -> None:
        for f in self.team + self.enemies:
            if not f.alive:
                continue
            color = f.spec.color if f.side == "player" else COL_ENEMY
            pygame.draw.circle(self.screen, color, (int(f.x), int(f.y)), 26)
            # HP bar
            bw, bh = 52, 6
            bx, by = int(f.x) - bw // 2, int(f.y) - 42
            pygame.draw.rect(self.screen, COL_HP_BG, (bx, by, bw, bh))
            ratio = max(0.0, f.hp / f.max_hp)
            pygame.draw.rect(self.screen, COL_HP, (bx, by, int(bw * ratio), bh))
            label = self.font_sm.render(f.spec.name, True, COL_TEXT)
            self.screen.blit(label, (int(f.x) - label.get_width() // 2, int(f.y) + 30))

    def _write_result(self) -> None:
        result = GameResult(
            session_id=self.session.session_id,
            gold_delta=self.gold - self.initial_gold,
            diamond_delta=self.diamond - self.initial_diamond,
            waves_cleared=self.waves_cleared,
            message=self.over_msg or (
                f"完成 {self.waves_cleared} 波" if self.waves_cleared else "退出竞技场"
            ),
        )
        result.write(self.session.result_path())


def run_session(session_path: str | Path) -> int:
    """启动一局竞技场，返回进程退出码。"""
    path = Path(session_path)
    if not path.exists():
        print(f"会话文件不存在: {path}")
        return 2
    try:
        session = GameSession.read(path)
        game = PetArenaGame(session)
        game.run()
        return 0
    except Exception as e:
        print(f"游戏运行错误: {e}")
        return 1


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python -m games.pet_arena <session_in.json>")
        raise SystemExit(2)
    raise SystemExit(run_session(sys.argv[1]))


if __name__ == "__main__":
    main()

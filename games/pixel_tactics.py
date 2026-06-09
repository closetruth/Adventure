"""像素格子战场（TFT 风格轻量版）。"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path
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
from src.game_protocol import GameResult, GameSession  # noqa: E402

W, H = 980, 700
FPS = 60
GRID_COLS, GRID_ROWS = 6, 4
CELL = 62
BOARD_X, BOARD_Y = 120, 120
ENTRY_FEE = 12
ROUND_GOLD = 8

COL_BG = (18, 20, 30)
COL_PANEL = (33, 37, 56)
COL_GRID = (70, 78, 108)
COL_TEXT = (240, 242, 250)
COL_MUTED = (168, 176, 196)
COL_GOLD = (255, 214, 79)
COL_DIAM = (120, 210, 255)
COL_PLAYER = (122, 232, 124)
COL_ENEMY = (255, 126, 126)
COL_CURSOR = (110, 148, 255)


@dataclass
class PieceSpec:
    key: str
    name: str
    cost: int
    hp: int
    atk: int
    color: Tuple[int, int, int]


SPECS = [
    PieceSpec("knight", "骑士", 3, 12, 3, (129, 199, 132)),
    PieceSpec("ranger", "游侠", 3, 9, 4, (255, 183, 77)),
    PieceSpec("guard", "护卫", 4, 16, 2, (144, 202, 249)),
    PieceSpec("assassin", "刺客", 4, 8, 5, (206, 147, 216)),
    PieceSpec("mage", "法师", 5, 10, 5, (255, 138, 128)),
]


@dataclass
class Unit:
    spec: PieceSpec
    hp: int
    atk: int
    x: int
    y: int
    side: str

    @classmethod
    def from_spec(cls, spec: PieceSpec, x: int, y: int, side: str) -> "Unit":
        return cls(spec=spec, hp=spec.hp, atk=spec.atk, x=x, y=y, side=side)

    def alive(self) -> bool:
        return self.hp > 0


class PixelTactics:
    def __init__(self, session: GameSession):
        self.session = session
        self.initial_gold = session.gold
        self.initial_diamond = session.diamond
        self.gold = session.gold
        self.diamond = session.diamond
        self.round_no = 0
        self.wins = 0
        self.losses = 0
        self.phase = "title"  # title | prep | battle | result | over
        self.log = ""
        self.battle_lines: List[str] = []
        self.cursor = [0, GRID_ROWS - 1]
        self.selected_bench = 0
        self.board: List[List[Optional[Unit]]] = [[None for _ in range(GRID_COLS)] for _ in range(GRID_ROWS)]
        self.bench: List[Optional[PieceSpec]] = [None, None, None]
        self.enemy_units: List[Unit] = []
        self.battle_tick = 0.0

        pygame.init()
        pygame.display.set_caption("Adventure - 像素格子战场")
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.font = load_font(22)
        self.font_sm = load_font(17)
        self.font_lg = load_font(30, bold=True)

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
                    else:
                        self._on_key(e.key)
            if self.phase == "battle":
                self._update_battle(dt)
            self._draw()
            if self.phase == "over":
                pygame.time.wait(1100)
                running = False
        self._write_result()

    def _on_key(self, key: int) -> None:
        if self.phase == "title":
            if key == pygame.K_SPACE:
                if self.gold < ENTRY_FEE:
                    self.log = f"金币不足，需要 {ENTRY_FEE}"
                    return
                self.gold -= ENTRY_FEE
                self.round_no = 1
                self.phase = "prep"
                self._begin_round()
            return

        if self.phase == "prep":
            if key == pygame.K_LEFT:
                self.cursor[0] = max(0, self.cursor[0] - 1)
            elif key == pygame.K_RIGHT:
                self.cursor[0] = min(GRID_COLS - 1, self.cursor[0] + 1)
            elif key == pygame.K_UP:
                self.cursor[1] = max(2, self.cursor[1] - 1)
            elif key == pygame.K_DOWN:
                self.cursor[1] = min(GRID_ROWS - 1, self.cursor[1] + 1)
            elif key in (pygame.K_1, pygame.K_2, pygame.K_3):
                self.selected_bench = key - pygame.K_1
            elif key == pygame.K_z:
                self._place_selected_from_bench()
            elif key == pygame.K_x:
                self._remove_from_cell()
            elif key == pygame.K_r:
                self._reroll_bench()
            elif key == pygame.K_SPACE:
                if not self._player_units():
                    self.log = "至少上阵一个单位"
                    return
                self._start_battle()
            return

        if self.phase == "result" and key == pygame.K_SPACE:
            if self.losses >= 5:
                self.phase = "over"
                self.log = f"结束：{self.wins}胜{self.losses}负"
            else:
                self.round_no += 1
                self.phase = "prep"
                self._begin_round()

    def _begin_round(self) -> None:
        self.gold += ROUND_GOLD
        self._reroll_bench(free=True)
        self.log = f"第 {self.round_no} 回合：布阵后按空格开战"

    def _reroll_bench(self, free: bool = False) -> None:
        if not free:
            if self.gold <= 0:
                self.log = "金币不足，无法刷新"
                return
            self.gold -= 1
        for i in range(3):
            self.bench[i] = random.choice(SPECS)

    def _place_selected_from_bench(self) -> None:
        spec = self.bench[self.selected_bench]
        if spec is None:
            self.log = "该备战槽为空"
            return
        if self.gold < spec.cost:
            self.log = f"金币不足，{spec.name} 需要 {spec.cost}"
            return
        cx, cy = self.cursor
        if cy < 2:
            self.log = "只能放在我方后两排"
            return
        if self.board[cy][cx] is not None:
            self.log = "该格子已被占用"
            return
        self.gold -= spec.cost
        self.board[cy][cx] = Unit.from_spec(spec, cx, cy, "player")
        self.bench[self.selected_bench] = None
        self.log = f"已放置 {spec.name}"

    def _remove_from_cell(self) -> None:
        cx, cy = self.cursor
        u = self.board[cy][cx]
        if u is None:
            return
        refund = 1
        self.gold += refund
        self.board[cy][cx] = None
        self.log = f"移除 {u.spec.name}，返还 {refund} 金币"

    def _player_units(self) -> List[Unit]:
        out: List[Unit] = []
        for row in self.board:
            for u in row:
                if u is not None and u.alive():
                    out.append(u)
        return out

    def _spawn_enemy_units(self) -> List[Unit]:
        cnt = min(2 + self.round_no // 2, 5)
        out: List[Unit] = []
        spots = [(x, y) for y in range(2) for x in range(GRID_COLS)]
        random.shuffle(spots)
        for i in range(cnt):
            spec = random.choice(SPECS)
            x, y = spots[i]
            u = Unit.from_spec(spec, x, y, "enemy")
            u.hp += self.round_no
            u.atk += self.round_no // 2
            out.append(u)
        return out

    def _start_battle(self) -> None:
        self.enemy_units = self._spawn_enemy_units()
        self.phase = "battle"
        self.battle_tick = 0.0
        self.battle_lines = [f"第 {self.round_no} 回合战斗开始"]

    def _update_battle(self, dt: float) -> None:
        self.battle_tick += dt
        if self.battle_tick < 0.35:
            return
        self.battle_tick = 0.0
        players = self._player_units()
        enemies = [u for u in self.enemy_units if u.alive()]

        if not players or not enemies:
            self._finish_battle(players, enemies)
            return

        self._one_side_step(players, enemies)
        players = self._player_units()
        enemies = [u for u in self.enemy_units if u.alive()]
        if not players or not enemies:
            self._finish_battle(players, enemies)
            return
        self._one_side_step(enemies, players)
        self._finish_if_needed()

    def _finish_if_needed(self) -> None:
        players = self._player_units()
        enemies = [u for u in self.enemy_units if u.alive()]
        if not players or not enemies:
            self._finish_battle(players, enemies)

    def _closest(self, src: Unit, targets: List[Unit]) -> Unit:
        return min(targets, key=lambda t: abs(src.x - t.x) + abs(src.y - t.y))

    def _one_side_step(self, actors: List[Unit], targets: List[Unit]) -> None:
        if not actors or not targets:
            return
        for u in actors:
            if not u.alive():
                continue
            live_targets = [t for t in targets if t.alive()]
            if not live_targets:
                break
            tgt = self._closest(u, live_targets)
            dist = abs(u.x - tgt.x) + abs(u.y - tgt.y)
            if dist <= 1:
                tgt.hp -= u.atk
                self.battle_lines.append(f"{u.spec.name} -> {tgt.spec.name} -{u.atk}")
            else:
                self._move_towards(u, tgt)

    def _move_towards(self, u: Unit, tgt: Unit) -> None:
        dx = 0 if u.x == tgt.x else (1 if tgt.x > u.x else -1)
        dy = 0 if u.y == tgt.y else (1 if tgt.y > u.y else -1)
        # 优先横向推进
        nx, ny = u.x + dx, u.y
        if 0 <= nx < GRID_COLS and 0 <= ny < GRID_ROWS and self._cell_free(nx, ny, u):
            u.x, u.y = nx, ny
            return
        nx, ny = u.x, u.y + dy
        if 0 <= nx < GRID_COLS and 0 <= ny < GRID_ROWS and self._cell_free(nx, ny, u):
            u.x, u.y = nx, ny

    def _cell_free(self, x: int, y: int, moving: Unit) -> bool:
        all_units = self._player_units() + [u for u in self.enemy_units if u.alive()]
        for u in all_units:
            if u is moving:
                continue
            if u.x == x and u.y == y:
                return False
        return True

    def _finish_battle(self, players: List[Unit], enemies: List[Unit]) -> None:
        if players and not enemies:
            self.wins += 1
            gain = round(random.uniform(0.1, 1.0), 1)
            self.gold += gain
            if self.wins % 3 == 0:
                d = round(random.uniform(0.1, 1.0), 1)
                self.diamond += d
                self.log = f"胜利！+{gain:.1f} 金币，+{d:.1f} 钻石"
            else:
                self.log = f"胜利！+{gain:.1f} 金币"
        else:
            self.losses += 1
            self.log = f"失败。当前 {self.wins} 胜 {self.losses} 负"
        # 战后我方单位满血恢复
        for row in self.board:
            for u in row:
                if u is not None:
                    u.hp = u.spec.hp
        self.phase = "result"

    def _draw(self) -> None:
        self.screen.fill(COL_BG)
        self._draw_header()
        if self.phase == "title":
            self._draw_center(["像素格子战场", "", f"入场费 {ENTRY_FEE} 金币", "空格开始"])
        elif self.phase in ("prep", "battle", "result"):
            self._draw_board()
            self._draw_right_panel()
            if self.phase == "result":
                self._draw_result_overlay()
        elif self.phase == "over":
            self._draw_center([self.log, "", "正在结算..."])
        self._draw_footer()
        pygame.display.flip()

    def _draw_header(self) -> None:
        pygame.draw.rect(self.screen, COL_PANEL, (0, 0, W, 52))
        self.screen.blit(self.font.render(f"金币 {self.gold:.1f}", True, COL_GOLD), (16, 12))
        self.screen.blit(self.font.render(f"钻石 {self.diamond:.1f}", True, COL_DIAM), (140, 12))
        self.screen.blit(self.font.render(f"回合 {max(1, self.round_no)}", True, COL_TEXT), (420, 12))
        s = self.font_sm.render(f"战绩 {self.wins}胜 {self.losses}负", True, COL_MUTED)
        self.screen.blit(s, (W - s.get_width() - 20, 16))

    def _draw_footer(self) -> None:
        pygame.draw.rect(self.screen, COL_PANEL, (0, H - 48, W, 48))
        msg = self.log or "ESC 退出并结算"
        self.screen.blit(self.font_sm.render(msg, True, COL_MUTED), (14, H - 34))

    def _draw_center(self, lines: List[str]) -> None:
        y = H // 2 - len(lines) * 22
        for ln in lines:
            sf = self.font_lg.render(ln, True, COL_TEXT)
            self.screen.blit(sf, (W // 2 - sf.get_width() // 2, y))
            y += 44

    def _draw_board(self) -> None:
        for y in range(GRID_ROWS):
            for x in range(GRID_COLS):
                px = BOARD_X + x * CELL
                py = BOARD_Y + y * CELL
                rect = pygame.Rect(px, py, CELL - 2, CELL - 2)
                pygame.draw.rect(self.screen, COL_GRID, rect, border_radius=6)
                if self.phase == "prep" and [x, y] == self.cursor:
                    pygame.draw.rect(self.screen, COL_CURSOR, rect, 2, border_radius=6)

        # 玩家单位
        for row in self.board:
            for u in row:
                if u is None or not u.alive():
                    continue
                self._draw_unit(u, player=True)
        # 敌方
        if self.phase in ("battle", "result"):
            for u in self.enemy_units:
                if u.alive():
                    self._draw_unit(u, player=False)

    def _draw_unit(self, u: Unit, player: bool) -> None:
        px = BOARD_X + u.x * CELL + 8
        py = BOARD_Y + u.y * CELL + 8
        color = COL_PLAYER if player else COL_ENEMY
        pygame.draw.rect(self.screen, color, (px, py, CELL - 18, CELL - 18), border_radius=6)
        hp = self.font_sm.render(str(max(0, u.hp)), True, COL_TEXT)
        self.screen.blit(hp, (px + 8, py + 8))

    def _draw_right_panel(self) -> None:
        x = 560
        pygame.draw.rect(self.screen, COL_PANEL, (x, 96, 390, 540), border_radius=12)
        title = "布阵阶段" if self.phase == "prep" else "战斗中"
        self.screen.blit(self.font.render(title, True, COL_TEXT), (x + 16, 114))

        # bench
        self.screen.blit(self.font_sm.render("备战区（1/2/3 选中，Z 放置）", True, COL_MUTED), (x + 16, 150))
        for i, spec in enumerate(self.bench):
            ry = 178 + i * 64
            rr = pygame.Rect(x + 16, ry, 358, 52)
            pygame.draw.rect(self.screen, (47, 52, 78), rr, border_radius=8)
            if i == self.selected_bench and self.phase == "prep":
                pygame.draw.rect(self.screen, COL_CURSOR, rr, 2, border_radius=8)
            if spec is None:
                txt = self.font_sm.render(f"[{i+1}] 空", True, COL_MUTED)
            else:
                txt = self.font_sm.render(
                    f"[{i+1}] {spec.name}  费用{spec.cost}  攻{spec.atk} 血{spec.hp}",
                    True,
                    COL_TEXT,
                )
            self.screen.blit(txt, (x + 26, ry + 16))

        tips = [
            "操作：",
            "方向键移动光标（仅我方后两排）",
            "Z 放置选中备战单位",
            "X 移除格子单位（返1金）",
            "R 刷新备战（-1金）",
            "Space 开战 / 下一回合",
        ]
        ty = 395
        for t in tips:
            self.screen.blit(self.font_sm.render(t, True, COL_MUTED), (x + 16, ty))
            ty += 26

        if self.phase in ("battle", "result"):
            self.screen.blit(self.font_sm.render("战斗日志：", True, COL_TEXT), (x + 16, 560))
            for i, ln in enumerate(self.battle_lines[-2:]):
                self.screen.blit(self.font_sm.render(ln, True, COL_MUTED), (x + 16, 584 + i * 18))

    def _draw_result_overlay(self) -> None:
        pygame.draw.rect(self.screen, (0, 0, 0, 90), (0, 0, W, H))
        box = pygame.Rect(280, 260, 420, 140)
        pygame.draw.rect(self.screen, COL_PANEL, box, border_radius=12)
        self.screen.blit(self.font_lg.render("回合结算", True, COL_TEXT), (box.x + 130, box.y + 18))
        self.screen.blit(self.font.render(self.log, True, COL_MUTED), (box.x + 28, box.y + 70))
        self.screen.blit(self.font_sm.render("按 Space 继续", True, COL_MUTED), (box.x + 150, box.y + 108))

    def _write_result(self) -> None:
        result = GameResult(
            session_id=self.session.session_id,
            gold_delta=self.gold - self.initial_gold,
            diamond_delta=self.diamond - self.initial_diamond,
            waves_cleared=self.round_no,
            message=f"像素战场战绩：{self.wins} 胜 {self.losses} 负，最高回合 {self.round_no}",
        )
        result.write(self.session.result_path())


def run_session(session_path: str | Path) -> int:
    p = Path(session_path)
    if not p.exists():
        print(f"会话文件不存在: {p}")
        return 2
    try:
        s = GameSession.read(p)
        game = PixelTactics(s)
        game.run()
        return 0
    except Exception as e:
        print(f"游戏运行错误: {e}")
        return 1


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python -m games.pixel_tactics <session_in.json>")
        raise SystemExit(2)
    raise SystemExit(run_session(sys.argv[1]))


if __name__ == "__main__":
    main()


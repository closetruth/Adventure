"""小动物竞技场（AutoPet 风格 MVP）。

从主程序传入会话 JSON 路径，结束时写出结算 JSON（金币/钻石净变化）。

操作（鼠标为主，键盘仍可用）：
  标题：点击「开始」或空格（消耗入场费）
  商店：
    - 点击商店宠物购买；点击「冻」冻结该格
    - 点击队伍列表选位/换位（5 槽纵向，与原先一致）
    - 按钮：刷新、卖出、开战
  战斗：自动回合制结算
  ESC：退出并结算
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass
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
ROUND_GOLD = 10
MAX_TEAM = 5
SHOP_SIZE = 3
BATTLE_SLOTS = 5
BATTLE_SLOT_W = 82
BATTLE_SLOT_H = 58
BATTLE_SLOT_GAP = 10
BATTLE_ROW_Y = 188
TEAM_LIST_X = 500
TEAM_LIST_Y = 160
TEAM_ROW_H = 52
FONT_NAMES = ("microsoftyaheiui", "microsoftyahei", "simhei", "arial")

COL_BG = (22, 24, 36)
COL_PANEL = (35, 38, 58)
COL_TEXT = (240, 242, 250)
COL_MUTED = (160, 168, 190)
COL_GOLD = (255, 213, 79)
COL_DIAM = (125, 211, 252)
COL_ENEMY = (255, 120, 120)
COL_ACCENT = (108, 140, 255)
COL_WARN = (255, 190, 120)


@dataclass
class PetSpec:
    key: str
    name: str
    cost: int
    hp: int
    atk: int
    color: Tuple[int, int, int]


SPECS = [
    PetSpec("cat", "小猫", 3, 8, 3, (255, 183, 77)),
    PetSpec("dog", "小狗", 3, 9, 2, (129, 199, 132)),
    PetSpec("bear", "小熊", 4, 11, 2, (149, 117, 205)),
    PetSpec("fox", "小狐", 4, 7, 4, (255, 138, 128)),
    PetSpec("boar", "野猪", 5, 14, 1, (144, 202, 249)),
]


@dataclass
class Unit:
    spec: PetSpec
    hp: int
    max_hp: int
    atk: int
    level: int = 1

    @classmethod
    def from_spec(cls, spec: PetSpec) -> "Unit":
        return cls(
            spec=spec,
            hp=spec.hp,
            max_hp=spec.hp,
            atk=spec.atk,
        )

    def copy_for_battle(self) -> "Unit":
        return Unit(
            spec=self.spec,
            hp=self.hp,
            max_hp=self.max_hp,
            atk=self.atk,
            level=self.level,
        )

    def merge_from(self, other: "Unit") -> bool:
        """同名合成升级（最高 3 级）。"""
        if self.spec.key != other.spec.key or self.level >= 3:
            return False
        self.level += 1
        self.atk += 1 + other.level
        self.max_hp += 2 + other.level
        self.hp = self.max_hp
        return True


@dataclass
class ShopSlot:
    spec: Optional[PetSpec] = None
    frozen: bool = False


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

        self.round_no = 0
        self.wins = 0
        self.losses = 0
        self.waves_cleared = 0  # 兼容旧字段含义：当作胜场
        self.phase = "title"  # title | shop | battle | battle_res | over
        self.team: List[Optional[Unit]] = [None] * MAX_TEAM
        self.shop: List[ShopSlot] = [ShopSlot() for _ in range(SHOP_SIZE)]
        self.selected_slot = 0
        self.battle_result_lines: List[str] = []
        self.enemy_preview: List[Unit] = []
        self.battle_players: List[Unit] = []
        self.battle_enemies: List[Unit] = []
        self.battle_player_board: List[Optional[Unit]] = [None] * BATTLE_SLOTS
        self.battle_enemy_board: List[Optional[Unit]] = [None] * BATTLE_SLOTS
        self.battle_focus_p: int = 0
        self.battle_focus_e: int = 0
        self.battle_events: List[dict] = []
        self.battle_event_idx = 0
        self.battle_event_cooldown = 0.0
        self.hit_flash = {"p": 0.0, "e": 0.0}
        self.float_texts: List[dict] = []
        self.battle_log = ""
        self.over_msg = ""
        self.entry_paid = False
        self._click_zones: List[Tuple[pygame.Rect, str, tuple]] = []
        self._swap_pick: Optional[int] = None

        pygame.init()
        pygame.display.set_caption("Adventure - 小动物竞技场（AutoPet）")
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
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        self._on_mouse_down(event.pos)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    else:
                        self._on_key(event.key)

            if self.phase == "battle":
                self._update_battle_animation(dt)
            self._update_float_texts(dt)
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
                self.round_no = 1
                self._start_round_income()
                self._roll_shop(initial=True)
                self.enemy_preview = self._generate_enemy_team(self.round_no)
                self.battle_log = "点击商店/队伍操作，点「开战」"
        elif self.phase == "shop":
            if key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                self.selected_slot = key - pygame.K_1
            elif key == pygame.K_q:
                self._buy_from_shop(0)
            elif key == pygame.K_w:
                self._buy_from_shop(1)
            elif key == pygame.K_e:
                self._buy_from_shop(2)
            elif key == pygame.K_a:
                self._toggle_freeze(0)
            elif key == pygame.K_s:
                self._toggle_freeze(1)
            elif key == pygame.K_d:
                self._toggle_freeze(2)
            elif key == pygame.K_r:
                self._roll_shop(initial=False)
            elif key == pygame.K_x:
                self._sell_selected()
            elif key == pygame.K_LEFT:
                self._move_selected(-1)
            elif key == pygame.K_RIGHT:
                self._move_selected(1)
            elif key == pygame.K_SPACE:
                if not any(self.team):
                    self.battle_log = "至少上阵一只宠物"
                    return
                self._start_battle_animation()
        elif self.phase == "battle_res":
            if key == pygame.K_SPACE:
                if self.losses >= 5:
                    self.phase = "over"
                    self.over_msg = f"结束：胜 {self.wins} 负 {self.losses}"
                else:
                    self.phase = "shop"
                    self.round_no += 1
                    self._start_round_income()
                    self._roll_shop(initial=True)
                    self.enemy_preview = self._generate_enemy_team(self.round_no)
                    self.battle_log = f"第 {self.round_no} 回合：继续组队"

    def _first_empty_slot(self) -> Optional[int]:
        for i, unit in enumerate(self.team):
            if unit is None:
                return i
        return None

    def _buy_from_shop(self, shop_idx: int) -> None:
        if shop_idx < 0 or shop_idx >= SHOP_SIZE:
            return
        slot = self.shop[shop_idx]
        spec = slot.spec
        if spec is None:
            self.battle_log = "该商店槽位为空"
            return
        if self.gold < spec.cost:
            self.battle_log = f"金币不足，{spec.name} 需要 {spec.cost}"
            return
        target_idx = self.selected_slot
        target = self.team[target_idx]
        self.gold -= spec.cost
        new_unit = Unit.from_spec(spec)
        if target is not None:
            if target.merge_from(new_unit):
                self.battle_log = f"{spec.name} 合成成功，升到 Lv{target.level}"
            else:
                empty = self._first_empty_slot()
                if empty is None:
                    self.gold += spec.cost
                    self.battle_log = "队伍已满，且无法合成"
                    return
                self.team[empty] = new_unit
                self.battle_log = f"{spec.name} 放入槽位 {empty+1}"
        else:
            self.team[target_idx] = new_unit
            self.battle_log = f"{spec.name} 放入槽位 {target_idx+1}"
        slot.spec = None
        slot.frozen = False

    def _toggle_freeze(self, shop_idx: int) -> None:
        slot = self.shop[shop_idx]
        if slot.spec is None:
            return
        slot.frozen = not slot.frozen
        self.battle_log = f"商店槽位 {shop_idx+1} {'已冻结' if slot.frozen else '已解冻'}"

    def _roll_shop(self, initial: bool) -> None:
        if not initial:
            if self.gold <= 0:
                self.battle_log = "金币不足，无法刷新"
                return
            self.gold -= 1
        for i in range(SHOP_SIZE):
            if self.shop[i].frozen and self.shop[i].spec is not None:
                continue
            self.shop[i].spec = random.choice(SPECS)
            self.shop[i].frozen = False
        if not initial:
            self.battle_log = "商店已刷新（-1 金币）"

    def _sell_selected(self) -> None:
        unit = self.team[self.selected_slot]
        if unit is None:
            self.battle_log = "该槽位没有宠物可卖"
            return
        gain = 1 + (unit.level - 1)
        self.gold += gain
        self.team[self.selected_slot] = None
        self.battle_log = f"卖出 {unit.spec.name}，获得 {gain} 金币"

    def _move_selected(self, direction: int) -> None:
        dst = self.selected_slot + direction
        if 0 <= dst < MAX_TEAM:
            self._swap_team_slots(self.selected_slot, dst)

    def _swap_team_slots(self, a: int, b: int) -> None:
        if a == b or a < 0 or b < 0 or a >= MAX_TEAM or b >= MAX_TEAM:
            return
        self.team[a], self.team[b] = self.team[b], self.team[a]
        self.selected_slot = b

    def _team_slot_rect(self, index: int) -> pygame.Rect:
        return pygame.Rect(TEAM_LIST_X, TEAM_LIST_Y + 40 + index * TEAM_ROW_H, 420, TEAM_ROW_H - 6)

    def _shop_card_rect(self, index: int) -> pygame.Rect:
        return pygame.Rect(40, 160 + index * 72, 420, 60)

    def _shop_freeze_rect(self, index: int) -> pygame.Rect:
        r = self._shop_card_rect(index)
        return pygame.Rect(r.right - 44, r.y + 12, 36, 36)

    def _battle_visual_col(self, side: str, slot_index: int) -> int:
        """敌方棋盘视觉顺序与对战顺序相反：靠 VS 的右侧格先出战。"""
        if side == "e":
            return BATTLE_SLOTS - 1 - slot_index
        return slot_index

    def _battle_slot_rect(self, side: str, slot_index: int) -> pygame.Rect:
        span = BATTLE_SLOTS * (BATTLE_SLOT_W + BATTLE_SLOT_GAP) - BATTLE_SLOT_GAP
        if side == "e":
            x0 = (W // 2 - span - 36) // 2
        else:
            x0 = W // 2 + 36 + (W // 2 - span - 36) // 2
        col = self._battle_visual_col(side, slot_index)
        x = x0 + col * (BATTLE_SLOT_W + BATTLE_SLOT_GAP)
        return pygame.Rect(x, BATTLE_ROW_Y, BATTLE_SLOT_W, BATTLE_SLOT_H)

    def _battle_slot_center(self, side: str, slot_index: int) -> Tuple[int, int]:
        r = self._battle_slot_rect(side, slot_index)
        return r.centerx, r.centery

    @staticmethod
    def _leftmost_alive(board: List[Optional[Unit]]) -> Tuple[int, Optional[Unit]]:
        for i, u in enumerate(board):
            if u is not None and u.hp > 0:
                return i, u
        return -1, None

    def _register_click(self, rect: pygame.Rect, action: str, *args) -> None:
        self._click_zones.append((rect, action, args))

    def _on_mouse_down(self, pos: Tuple[int, int]) -> None:
        for rect, action, args in self._click_zones:
            if rect.collidepoint(pos):
                handler = getattr(self, f"_click_{action}", None)
                if handler:
                    handler(*args)
                return

    def _click_start_game(self) -> None:
        if self.phase != "title":
            return
        if self.gold < ENTRY_FEE:
            self.battle_log = f"金币不足，需要 {ENTRY_FEE} 入场"
            return
        self.gold -= ENTRY_FEE
        self.entry_paid = True
        self.phase = "shop"
        self.round_no = 1
        self._start_round_income()
        self._roll_shop(initial=True)
        self.enemy_preview = self._generate_enemy_team(self.round_no)
        self.battle_log = "点击商店/队伍操作，点「开战」"

    def _click_select_slot(self, index: int) -> None:
        if self.phase != "shop" or index < 0 or index >= MAX_TEAM:
            return
        if self._swap_pick is not None and self._swap_pick != index:
            self._swap_team_slots(self._swap_pick, index)
            self._swap_pick = None
            self.selected_slot = index
            self.battle_log = "已交换两格位置"
            return
        self._swap_pick = index
        self.selected_slot = index
        self.battle_log = f"选中第 {index + 1} 格，再点另一格可换位"

    def _click_buy_shop(self, shop_idx: int) -> None:
        if self.phase == "shop":
            self._buy_from_shop(shop_idx)

    def _click_freeze_shop(self, shop_idx: int) -> None:
        if self.phase == "shop":
            self._toggle_freeze(shop_idx)

    def _click_refresh(self) -> None:
        if self.phase == "shop":
            self._roll_shop(initial=False)

    def _click_sell(self) -> None:
        if self.phase == "shop":
            self._sell_selected()

    def _click_battle(self) -> None:
        if self.phase != "shop":
            return
        if not any(self.team):
            self.battle_log = "至少上阵一只宠物"
            return
        self._start_battle_animation()

    def _click_continue(self) -> None:
        if self.phase == "battle_res":
            if self.losses >= 5:
                self.phase = "over"
                self.over_msg = f"结束：胜 {self.wins} 负 {self.losses}"
            else:
                self.phase = "shop"
                self.round_no += 1
                self._start_round_income()
                self._roll_shop(initial=True)
                self.enemy_preview = self._generate_enemy_team(self.round_no)
                self.battle_log = f"第 {self.round_no} 回合：继续组队"

    def _start_round_income(self) -> None:
        self.gold += ROUND_GOLD
        self.battle_log = f"第 {self.round_no} 回合开始，+{ROUND_GOLD} 金币"

    def _generate_enemy_team(self, round_no: int) -> List[Unit]:
        count = min(2 + round_no // 2, MAX_TEAM)
        out: List[Unit] = []
        for _ in range(count):
            spec = random.choice(SPECS)
            u = Unit.from_spec(spec)
            u.atk += round_no // 2
            u.max_hp += round_no
            u.hp = u.max_hp
            if round_no >= 6 and random.random() < 0.35:
                u.level = 2
                u.atk += 2
                u.max_hp += 3
                u.hp = u.max_hp
            out.append(u)
        return out

    def _start_battle_animation(self) -> None:
        self.battle_player_board = [None] * BATTLE_SLOTS
        self.battle_enemy_board = [None] * BATTLE_SLOTS
        for i in range(BATTLE_SLOTS):
            if self.team[i] is not None:
                self.battle_player_board[i] = self.team[i].copy_for_battle()
        for i, u in enumerate(self.enemy_preview[:BATTLE_SLOTS]):
            self.battle_enemy_board[i] = u.copy_for_battle()
        self.battle_players = [u for u in self.battle_player_board if u is not None]
        self.battle_enemies = [u for u in self.battle_enemy_board if u is not None]
        self.battle_events = self._build_battle_events()
        pi, _ = self._leftmost_alive(self.battle_player_board)
        ei, _ = self._leftmost_alive(self.battle_enemy_board)
        self.battle_focus_p = max(0, pi)
        self.battle_focus_e = max(0, ei)
        self.battle_event_idx = 0
        self.battle_event_cooldown = 0.25
        self.battle_result_lines = [f"第 {self.round_no} 回合自动战斗："]
        self.phase = "battle"

    def _build_battle_events(self) -> List[dict]:
        p_board = [u.copy_for_battle() if u else None for u in self.battle_player_board]
        e_board = [u.copy_for_battle() if u else None for u in self.battle_enemy_board]
        events: List[dict] = []
        turns = 0
        while turns < 60:
            pi, p = self._leftmost_alive(p_board)
            ei, e = self._leftmost_alive(e_board)
            if p is None or e is None:
                break
            turns += 1
            e.hp -= p.atk
            events.append({
                "type": "hit",
                "attacker_side": "p",
                "attacker_slot": pi,
                "target_side": "e",
                "target_slot": ei,
                "attacker_name": p.spec.name,
                "target_name": e.spec.name,
                "damage": p.atk,
                "target_hp": max(0, e.hp),
                "target_max_hp": e.max_hp,
                "target_dead": e.hp <= 0,
            })
            if e.hp <= 0:
                e_board[ei] = None
                continue
            p.hp -= e.atk
            events.append({
                "type": "hit",
                "attacker_side": "e",
                "attacker_slot": ei,
                "target_side": "p",
                "target_slot": pi,
                "attacker_name": e.spec.name,
                "target_name": p.spec.name,
                "damage": e.atk,
                "target_hp": max(0, p.hp),
                "target_max_hp": p.max_hp,
                "target_dead": p.hp <= 0,
            })
            if p.hp <= 0:
                p_board[pi] = None
        _, p_alive = self._leftmost_alive(p_board)
        _, e_alive = self._leftmost_alive(e_board)
        events.append({
            "type": "result",
            "player_alive": p_alive is not None,
            "enemy_alive": e_alive is not None,
        })
        return events

    def _update_battle_animation(self, dt: float) -> None:
        self.hit_flash["p"] = max(0.0, self.hit_flash["p"] - dt * 2.5)
        self.hit_flash["e"] = max(0.0, self.hit_flash["e"] - dt * 2.5)
        self.battle_event_cooldown -= dt
        if self.battle_event_cooldown > 0:
            return
        if self.battle_event_idx >= len(self.battle_events):
            self.phase = "battle_res"
            return
        ev = self.battle_events[self.battle_event_idx]
        self.battle_event_idx += 1
        if ev["type"] == "hit":
            target_side = ev["target_side"]
            if target_side == "p":
                slot = ev["target_slot"]
                board = self.battle_player_board
                self.battle_focus_e = ev["attacker_slot"]
                self.battle_focus_p = slot
            else:
                slot = ev["target_slot"]
                board = self.battle_enemy_board
                self.battle_focus_p = ev["attacker_slot"]
                self.battle_focus_e = slot
            if 0 <= slot < BATTLE_SLOTS and board[slot] is not None:
                board[slot].hp = ev["target_hp"]
                self.hit_flash["p" if target_side == "p" else "e"] = 1.0
                self._spawn_damage_text(target_side, ev["damage"], slot)
                if ev["target_dead"]:
                    board[slot] = None
            self.battle_players = [u for u in self.battle_player_board if u is not None]
            self.battle_enemies = [u for u in self.battle_enemy_board if u is not None]
            self.battle_result_lines.append(
                f"{ev['attacker_name']} → {ev['target_name']} -{ev['damage']}  "
                f"血 {ev['target_hp']}/{ev['target_max_hp']}"
            )
            self.battle_result_lines = self.battle_result_lines[-10:]
            self.battle_event_cooldown = 0.45
        else:
            player_alive = ev["player_alive"]
            enemy_alive = ev["enemy_alive"]
            if player_alive and not enemy_alive:
                self.wins += 1
                self.waves_cleared = self.wins
                gain = round(random.uniform(0.1, 1.0), 1)
                self.gold += gain
                extra_diamond = round(random.uniform(0.1, 1.0), 1) if self.wins % 3 == 0 else 0.0
                self.diamond += extra_diamond
                self.battle_log = f"胜利！+{gain:.1f} 金币" + (
                    f"，+{extra_diamond:.1f} 钻石" if extra_diamond else ""
                )
            elif enemy_alive and not player_alive:
                self.losses += 1
                self.battle_log = f"失败。当前战绩 {self.wins} 胜 {self.losses} 负"
            else:
                self.losses += 1
                self.battle_log = "平局判负。"
            self.phase = "battle_res"
            if self.losses >= 5:
                self.phase = "over"
                self.over_msg = f"战绩：{self.wins} 胜 {self.losses} 负"
            self.battle_event_cooldown = 0.2

    def _spawn_damage_text(self, side: str, dmg: int, slot: int = 0) -> None:
        x, y = self._battle_slot_center(side, slot)
        self.float_texts.append({"x": x, "y": y, "ttl": 0.9, "text": f"-{dmg}"})

    def _update_float_texts(self, dt: float) -> None:
        alive: List[dict] = []
        for t in self.float_texts:
            t["ttl"] -= dt
            t["y"] -= dt * 38
            if t["ttl"] > 0:
                alive.append(t)
        self.float_texts = alive

    def _draw(self) -> None:
        self._click_zones = []
        self.screen.fill(COL_BG)
        self._draw_header()

        if self.phase == "title":
            self._draw_title()
        elif self.phase == "shop":
            self._draw_shop()
        elif self.phase == "battle":
            self._draw_battle_animated()
        elif self.phase == "battle_res":
            self._draw_battle_result()
            btn = pygame.Rect(W // 2 - 120, H // 2 + 40, 240, 48)
            pygame.draw.rect(self.screen, COL_ACCENT, btn, border_radius=10)
            lab = self.font.render("下一回合", True, COL_TEXT)
            self.screen.blit(lab, (btn.centerx - lab.get_width() // 2, btn.centery - 12))
            self._register_click(btn, "continue")
        elif self.phase == "over":
            self._draw_center([self.over_msg, "", "正在结算..."])

        self._draw_footer()
        pygame.display.flip()

    def _draw_header(self) -> None:
        pygame.draw.rect(self.screen, COL_PANEL, (0, 0, W, 52))
        t1 = self.font.render(f"金币 {self.gold:.1f}", True, COL_GOLD)
        t2 = self.font.render(f"钻石 {self.diamond:.1f}", True, COL_DIAM)
        tw = self.font.render(f"回合 {max(1, self.round_no)}", True, COL_TEXT)
        score = self.font_sm.render(f"战绩 {self.wins}胜 {self.losses}负", True, COL_MUTED)
        self.screen.blit(t1, (16, 12))
        self.screen.blit(t2, (130, 12))
        self.screen.blit(tw, (W // 2 - tw.get_width() // 2, 12))
        self.screen.blit(score, (W - score.get_width() - 20, 16))

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

    def _draw_title(self) -> None:
        self._draw_center([
            "小动物竞技场",
            "",
            f"入场费 {ENTRY_FEE} 金币",
        ])
        btn = pygame.Rect(W // 2 - 100, H // 2 + 20, 200, 52)
        pygame.draw.rect(self.screen, COL_ACCENT, btn, border_radius=12)
        t = self.font_lg.render("开始游戏", True, COL_TEXT)
        self.screen.blit(t, (btn.centerx - t.get_width() // 2, btn.centery - 16))
        self._title_start_rect = btn
        self._register_click(btn, "start_game")
        hint = self.font_sm.render("或按空格开始  ·  ESC 退出", True, COL_MUTED)
        self.screen.blit(hint, (W // 2 - hint.get_width() // 2, btn.bottom + 16))

    def _draw_shop(self) -> None:
        title = self.font_lg.render("商店阶段（AutoPet）", True, COL_TEXT)
        self.screen.blit(title, (40, 72))
        hint = self.font_sm.render(
            "鼠标：点商店行购买/冻结 · 点队伍行选位换位 · 左下按钮",
            True,
            COL_MUTED,
        )
        self.screen.blit(hint, (40, 118))

        for i, slot in enumerate(self.shop):
            card = self._shop_card_rect(i)
            bg = COL_PANEL if not slot.frozen else (54, 62, 95)
            pygame.draw.rect(self.screen, bg, card, border_radius=8)
            buy_rect = pygame.Rect(card.x, card.y, card.w - 48, card.h)
            if slot.spec is not None:
                self._register_click(buy_rect, "buy_shop", i)
                spec = slot.spec
                name = self.font.render(f"[{i+1}] {spec.name}  -{spec.cost} 金", True, COL_TEXT)
                stat = self.font_sm.render(f"生命 {spec.hp}  攻击 {spec.atk}", True, COL_MUTED)
                self.screen.blit(name, (card.x + 12, card.y + 8))
                self.screen.blit(stat, (card.x + 12, card.y + 34))
            else:
                txt = self.font.render(f"[{i+1}] (已售空)", True, COL_MUTED)
                self.screen.blit(txt, (card.x + 52, card.y + 18))
            frz = self._shop_freeze_rect(i)
            pygame.draw.rect(self.screen, (60, 66, 90), frz, border_radius=6)
            frz_txt = self.font_sm.render("冻", True, COL_WARN if slot.frozen else COL_MUTED)
            self.screen.blit(frz_txt, (frz.centerx - 8, frz.centery - 10))
            if slot.spec is not None:
                self._register_click(frz, "freeze_shop", i)

        for label, action, x, y in (
            ("刷新(-1)", "refresh", 40, 390),
            ("卖出", "sell", 140, 390),
            ("开战", "battle", 240, 390),
        ):
            rect = pygame.Rect(x, y, 88, 34)
            col = COL_ACCENT if action == "battle" else (48, 52, 78)
            pygame.draw.rect(self.screen, col, rect, border_radius=8)
            t = self.font_sm.render(label, True, COL_TEXT)
            self.screen.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - 10))
            self._register_click(rect, action)

        self._draw_team_preview(TEAM_LIST_X, TEAM_LIST_Y)
        self._draw_enemy_preview(TEAM_LIST_X, 470)

    def _draw_team_preview(self, x: int, y: int) -> None:
        lab = self.font.render("我的队伍（槽位 1~5 即战斗从左到右）", True, COL_TEXT)
        self.screen.blit(lab, (x, y))
        for i in range(MAX_TEAM):
            row = y + 40 + i * TEAM_ROW_H
            rect = pygame.Rect(x, row, 420, TEAM_ROW_H - 6)
            pygame.draw.rect(self.screen, COL_PANEL, rect, border_radius=6)
            if i == self.selected_slot:
                pygame.draw.rect(self.screen, COL_ACCENT, rect.inflate(6, 4), 2, border_radius=8)
            self._register_click(rect, "select_slot", i)
            f = self.team[i]
            if f is None:
                t = self.font_sm.render(f"[{i+1}] 空槽", True, COL_MUTED)
                self.screen.blit(t, (x + 12, row + 12))
                continue
            t = self.font_sm.render(
                f"[{i+1}] {f.spec.name} Lv{f.level}  攻{f.atk}  血{f.hp}/{f.max_hp}",
                True,
                COL_TEXT,
            )
            self.screen.blit(t, (x + 12, row + 10))

    def _draw_enemy_preview(self, x: int, y: int) -> None:
        lab = self.font_sm.render("敌方预览（靠右先出战）", True, COL_MUTED)
        self.screen.blit(lab, (x, y))
        padded: List[Optional[Unit]] = [None] * BATTLE_SLOTS
        for i, u in enumerate(self.enemy_preview[:BATTLE_SLOTS]):
            padded[i] = u
        ey = y + 24
        for i in range(BATTLE_SLOTS):
            col = self._battle_visual_col("e", i)
            sx = x + col * (BATTLE_SLOT_W + BATTLE_SLOT_GAP)
            rect = pygame.Rect(sx, ey, BATTLE_SLOT_W, BATTLE_SLOT_H - 8)
            pygame.draw.rect(self.screen, (42, 36, 48), rect, border_radius=6)
            u = padded[i]
            if u is None:
                continue
            name = self.font_sm.render(u.spec.name, True, COL_ENEMY)
            hp = self.font_sm.render(f"{u.hp}/{u.max_hp}", True, COL_MUTED)
            self.screen.blit(name, (rect.centerx - name.get_width() // 2, rect.y + 4))
            self.screen.blit(hp, (rect.centerx - hp.get_width() // 2, rect.y + 24))

    def _draw_battle_lane(self, side: str, board: List[Optional[Unit]], focus: int) -> None:
        for i in range(BATTLE_SLOTS):
            rect = self._battle_slot_rect(side, i)
            u = board[i] if i < len(board) else None
            alive = u is not None and u.hp > 0
            bg = COL_PANEL
            if alive and i == focus:
                if side == "p" and self.hit_flash["p"] > 0:
                    bg = (42, 80, 46)
                elif side == "e" and self.hit_flash["e"] > 0:
                    bg = (92, 44, 44)
                pygame.draw.rect(self.screen, COL_ACCENT, rect.inflate(4, 4), 2, border_radius=8)
            pygame.draw.rect(self.screen, bg, rect, border_radius=8)
            if not alive:
                dash = self.font_sm.render("—", True, COL_MUTED)
                self.screen.blit(dash, (rect.centerx - dash.get_width() // 2, rect.centery - 8))
                continue
            name_col = COL_TEXT if side == "p" else COL_ENEMY
            name = self.font_sm.render(u.spec.name, True, name_col)
            hp_txt = self.font_sm.render(f"{u.hp}/{u.max_hp}", True, COL_TEXT)
            atk_txt = self.font_sm.render(f"攻{u.atk}", True, COL_MUTED)
            self.screen.blit(name, (rect.centerx - name.get_width() // 2, rect.y + 4))
            self.screen.blit(hp_txt, (rect.centerx - hp_txt.get_width() // 2, rect.y + 22))
            self.screen.blit(atk_txt, (rect.right - atk_txt.get_width() - 4, rect.y + 4))
            if u.level > 1:
                lv = self.font_sm.render(f"L{u.level}", True, COL_GOLD)
                self.screen.blit(lv, (rect.x + 4, rect.y + 4))
            bar_w = int((rect.w - 8) * max(0.0, u.hp / max(1, u.max_hp)))
            pygame.draw.rect(
                self.screen,
                (70, 76, 96),
                (rect.x + 4, rect.bottom - 8, rect.w - 8, 4),
                border_radius=2,
            )
            if bar_w > 0:
                pygame.draw.rect(
                    self.screen,
                    (120, 220, 140) if side == "p" else (220, 100, 100),
                    (rect.x + 4, rect.bottom - 8, bar_w, 4),
                    border_radius=2,
                )

    def _draw_battle_animated(self) -> None:
        title = self.font_lg.render("自动战斗中", True, COL_TEXT)
        self.screen.blit(title, (W // 2 - title.get_width() // 2, 72))

        elab = self.font_sm.render("敌方", True, COL_ENEMY)
        plab = self.font_sm.render("我方", True, COL_TEXT)
        self.screen.blit(elab, (60, BATTLE_ROW_Y - 28))
        self.screen.blit(plab, (W - 60 - plab.get_width(), BATTLE_ROW_Y - 28))

        vs = self.font_lg.render("VS", True, COL_ACCENT)
        self.screen.blit(vs, (W // 2 - vs.get_width() // 2, BATTLE_ROW_Y + 12))

        self._draw_battle_lane("e", self.battle_enemy_board, self.battle_focus_e)
        self._draw_battle_lane("p", self.battle_player_board, self.battle_focus_p)

        for t in self.float_texts:
            alpha = max(0, min(255, int(255 * (t["ttl"] / 0.9))))
            surf = self.font_lg.render(t["text"], True, (255, 120, 120))
            surf.set_alpha(alpha)
            self.screen.blit(surf, (int(t["x"]), int(t["y"])))

        y_log = 520
        for line in self.battle_result_lines[-5:]:
            self.screen.blit(self.font_sm.render(line, True, COL_MUTED), (80, y_log))
            y_log += 22

    def _draw_battle_result(self) -> None:
        self._draw_center([
            "本回合战斗结束",
            self.battle_log,
            "",
            "空格继续下一回合",
        ])
        y = 420
        for line in self.battle_result_lines[-6:]:
            surf = self.font_sm.render(line, True, COL_MUTED)
            self.screen.blit(surf, (40, y))
            y += 26

    def _write_result(self) -> None:
        result = GameResult(
            session_id=self.session.session_id,
            gold_delta=self.gold - self.initial_gold,
            diamond_delta=self.diamond - self.initial_diamond,
            waves_cleared=self.round_no,
            message=self.over_msg or (
                f"战绩：{self.wins} 胜 {self.losses} 负，最高回合 {self.round_no}"
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

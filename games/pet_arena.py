"""小动物竞技场（AutoPet 风格 MVP）。

从主程序传入会话 JSON 路径，结束时写出结算 JSON（金币/钻石净变化）。

操作：
  标题：空格开始（消耗入场费）
  商店：
    - Q/W/E : 购买商店 1/2/3 宠物
    - A/S/D : 冻结/解冻商店 1/2/3
    - 1~5   : 选择队伍槽位
    - 左/右 : 移动所选宠物（调整站位）
    - X     : 卖出所选宠物（+1 金币）
    - R     : 刷新商店（-1 金币）
    - 空格   : 开始战斗
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
        self.battle_events: List[dict] = []
        self.battle_event_idx = 0
        self.battle_event_cooldown = 0.0
        self.hit_flash = {"p": 0.0, "e": 0.0}
        self.float_texts: List[dict] = []
        self.battle_log = ""
        self.over_msg = ""
        self.entry_paid = False

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
                self.battle_log = "商店阶段：Q/W/E购买，空格战斗"
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
        src = self.selected_slot
        dst = src + direction
        if dst < 0 or dst >= MAX_TEAM:
            return
        self.team[src], self.team[dst] = self.team[dst], self.team[src]
        self.selected_slot = dst

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
        self.battle_players = [u.copy_for_battle() for u in self.team if u is not None]
        self.battle_enemies = [u.copy_for_battle() for u in self.enemy_preview]
        self.battle_events = self._build_battle_events()
        self.battle_event_idx = 0
        self.battle_event_cooldown = 0.25
        self.battle_result_lines = [f"第 {self.round_no} 回合自动战斗："]
        self.phase = "battle"

    def _build_battle_events(self) -> List[dict]:
        player = [u.copy_for_battle() for u in self.team if u is not None]
        enemy = [u.copy_for_battle() for u in self.enemy_preview]
        events: List[dict] = []
        turns = 0
        while player and enemy and turns < 60:
            turns += 1
            p = player[0]
            e = enemy[0]
            e.hp -= p.atk
            events.append({
                "type": "hit",
                "attacker_side": "p",
                "attacker_name": p.spec.name,
                "target_side": "e",
                "target_name": e.spec.name,
                "damage": p.atk,
                "target_hp": max(0, e.hp),
                "target_dead": e.hp <= 0,
            })
            if e.hp <= 0:
                enemy.pop(0)
                continue
            p.hp -= e.atk
            events.append({
                "type": "hit",
                "attacker_side": "e",
                "attacker_name": e.spec.name,
                "target_side": "p",
                "target_name": p.spec.name,
                "damage": e.atk,
                "target_hp": max(0, p.hp),
                "target_dead": p.hp <= 0,
            })
            if p.hp <= 0:
                player.pop(0)
        events.append({
            "type": "result",
            "player_alive": bool(player),
            "enemy_alive": bool(enemy),
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
            if target_side == "p" and self.battle_players:
                t = self.battle_players[0]
                t.hp = ev["target_hp"]
                self.hit_flash["p"] = 1.0
                self._spawn_damage_text("p", ev["damage"])
                if ev["target_dead"]:
                    self.battle_players.pop(0)
            elif target_side == "e" and self.battle_enemies:
                t = self.battle_enemies[0]
                t.hp = ev["target_hp"]
                self.hit_flash["e"] = 1.0
                self._spawn_damage_text("e", ev["damage"])
                if ev["target_dead"]:
                    self.battle_enemies.pop(0)
            self.battle_result_lines.append(
                f"{ev['attacker_name']} 攻击 {ev['target_name']} -{ev['damage']}"
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

    def _spawn_damage_text(self, side: str, dmg: int) -> None:
        x = 260 if side == "p" else 700
        y = 255
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
            self._draw_battle_animated()
        elif self.phase == "battle_res":
            self._draw_battle_result()
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

    def _draw_shop(self) -> None:
        title = self.font_lg.render("商店阶段（AutoPet）", True, COL_TEXT)
        self.screen.blit(title, (40, 72))
        hint = self.font_sm.render(
            "Q/W/E购买  A/S/D冻结  1~5选槽位  左右换位  X卖出  R刷新  空格战斗",
            True,
            COL_MUTED,
        )
        self.screen.blit(hint, (40, 118))

        for i, slot in enumerate(self.shop):
            y = 160 + i * 72
            bg = COL_PANEL if not slot.frozen else (54, 62, 95)
            pygame.draw.rect(self.screen, bg, (40, y, 420, 60), border_radius=8)
            if slot.spec is None:
                txt = self.font.render(f"[{i+1}] (已售空)", True, COL_MUTED)
                self.screen.blit(txt, (52, y + 18))
                continue
            spec = slot.spec
            name = self.font.render(f"[{i+1}] {spec.name}  -{spec.cost} 金", True, COL_TEXT)
            stat = self.font_sm.render(f"生命 {spec.hp}  攻击 {spec.atk}", True, COL_MUTED)
            frz = self.font_sm.render(
                "冻结" if slot.frozen else "可刷新",
                True,
                COL_WARN if slot.frozen else COL_ACCENT,
            )
            pygame.draw.circle(self.screen, spec.color, (438, y + 30), 18)
            self.screen.blit(name, (52, y + 8))
            self.screen.blit(stat, (52, y + 34))
            self.screen.blit(frz, (340, y + 20))

        self._draw_team_preview(500, 160)
        self._draw_enemy_preview(500, 470)

    def _draw_team_preview(self, x: int, y: int) -> None:
        lab = self.font.render("我的队伍（前排在左）", True, COL_TEXT)
        self.screen.blit(lab, (x, y))
        for i, f in enumerate(self.team):
            row = y + 40 + i * 52
            pygame.draw.rect(self.screen, COL_PANEL, (x, row, 420, 42), border_radius=6)
            if i == self.selected_slot:
                pygame.draw.rect(self.screen, COL_ACCENT, (x - 4, row - 2, 428, 46), 2, border_radius=8)
            if f is None:
                t = self.font_sm.render(f"[{i+1}] 空槽", True, COL_MUTED)
                self.screen.blit(t, (x + 12, row + 12))
                continue
            pygame.draw.circle(self.screen, f.spec.color, (x + 24, row + 21), 16)
            t = self.font_sm.render(
                f"[{i+1}] {f.spec.name} Lv{f.level}  攻{f.atk}  血{f.hp}/{f.max_hp}",
                True,
                COL_TEXT,
            )
            self.screen.blit(t, (x + 48, row + 10))

    def _draw_enemy_preview(self, x: int, y: int) -> None:
        lab = self.font_sm.render("本回合敌方预览（强度估计）", True, COL_MUTED)
        self.screen.blit(lab, (x, y))
        for i, u in enumerate(self.enemy_preview[:5]):
            text = self.font_sm.render(
                f"{i+1}. {u.spec.name} Lv{u.level} 攻{u.atk} 血{u.hp}",
                True,
                COL_ENEMY,
            )
            self.screen.blit(text, (x, y + 24 + i * 20))

    def _draw_battle_animated(self) -> None:
        title = self.font_lg.render("自动战斗中...", True, COL_TEXT)
        self.screen.blit(title, (330, 84))

        p_x, e_x = 250, 710
        y = 250
        p_bg = (42, 80, 46) if self.hit_flash["p"] > 0 else COL_PANEL
        e_bg = (92, 44, 44) if self.hit_flash["e"] > 0 else COL_PANEL
        pygame.draw.rect(self.screen, p_bg, (p_x - 150, y - 70, 250, 180), border_radius=14)
        pygame.draw.rect(self.screen, e_bg, (e_x - 100, y - 70, 250, 180), border_radius=14)

        if self.battle_players:
            p = self.battle_players[0]
            pygame.draw.circle(self.screen, p.spec.color, (p_x - 20, y), 36)
            t = self.font.render(f"{p.spec.name} Lv{p.level}", True, COL_TEXT)
            hp = self.font_sm.render(f"HP {max(0, p.hp)}/{p.max_hp}  ATK {p.atk}", True, COL_MUTED)
            self.screen.blit(t, (p_x + 30, y - 30))
            self.screen.blit(hp, (p_x + 30, y + 4))
        else:
            self.screen.blit(self.font.render("我方全灭", True, COL_MUTED), (p_x - 70, y - 10))

        if self.battle_enemies:
            e = self.battle_enemies[0]
            pygame.draw.circle(self.screen, COL_ENEMY, (e_x + 20, y), 36)
            t = self.font.render(f"{e.spec.name} Lv{e.level}", True, COL_TEXT)
            hp = self.font_sm.render(f"HP {max(0, e.hp)}/{e.max_hp}  ATK {e.atk}", True, COL_MUTED)
            self.screen.blit(t, (e_x - 180, y - 30))
            self.screen.blit(hp, (e_x - 180, y + 4))
        else:
            self.screen.blit(self.font.render("敌方全灭", True, COL_MUTED), (e_x - 70, y - 10))

        # 显示双方全部宠物（列表）
        self.screen.blit(self.font_sm.render("我方全部宠物", True, COL_TEXT), (90, 430))
        for i, u in enumerate(self.battle_players[:5]):
            line = self.font_sm.render(
                f"{i+1}. {u.spec.name} Lv{u.level}  HP {max(0, u.hp)}/{u.max_hp}  攻 {u.atk}",
                True,
                COL_MUTED,
            )
            self.screen.blit(line, (90, 455 + i * 22))

        self.screen.blit(self.font_sm.render("敌方全部宠物", True, COL_TEXT), (560, 430))
        for i, u in enumerate(self.battle_enemies[:5]):
            line = self.font_sm.render(
                f"{i+1}. {u.spec.name} Lv{u.level}  HP {max(0, u.hp)}/{u.max_hp}  攻 {u.atk}",
                True,
                COL_MUTED,
            )
            self.screen.blit(line, (560, 455 + i * 22))

        for t in self.float_texts:
            alpha = max(0, min(255, int(255 * (t["ttl"] / 0.9))))
            surf = self.font_lg.render(t["text"], True, (255, 120, 120))
            surf.set_alpha(alpha)
            self.screen.blit(surf, (int(t["x"]), int(t["y"])))

        y_log = 560
        for line in self.battle_result_lines[-4:]:
            self.screen.blit(self.font_sm.render(line, True, COL_MUTED), (120, y_log))
            y_log += 24

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

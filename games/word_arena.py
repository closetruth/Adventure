"""计算机词汇自走棋（Super Auto Pets 式轻量版）。

用英语计算机词汇当棋子：每种词汇自带一个与本义强关联的触发技能。
每回合商店固定 10 金币，买词汇/食物、喂食、三合升星、调整队伍顺序；
自动回合制战斗（左列先手打右列），赢拿奖杯、输掉生命，集满 10 奖杯通关。

操作：
  鼠标点选商店卡片/队伍/按钮；空格=开始/开战/继续；ESC 退出并结算
  dummy 环境（SDL_VIDEODRIVER=dummy）自动模拟完整一局，便于无头验证
"""
from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    import pygame
except ImportError:
    print("请先安装 pygame-ce（Python 3.14 必须用 ce 版）:")
    print("  pip install pygame-ce")
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from games.font_util import load_font  # noqa: E402
from src.game_protocol import GameResult, GameSession  # noqa: E402

W, H = 1100, 700
FPS = 60
ENTRY_FEE = 10
ROUND_GOLD = 10
MAX_TEAM = 5
SHOP_SLOTS = 3
TIER_COUNT = 5
WIN_TROPHIES = 10
MAX_LIVES = 10

# 颜色
COL_BG = (18, 20, 30)
COL_PANEL = (33, 37, 56)
COL_CARD = (45, 50, 74)
COL_BORDER = (80, 90, 130)
COL_TEXT = (240, 242, 250)
COL_MUTED = (158, 166, 188)
COL_GOLD = (255, 213, 79)
COL_DIAM = (125, 211, 252)
COL_HP = (232, 86, 86)
COL_EXP = (120, 226, 255)
COL_ENEMY = (255, 120, 120)
COL_ACCENT = (110, 140, 255)
COL_STAR = (255, 205, 90)
COL_FOOD = (160, 230, 150)

TIER_NAMES = ["入门", "基础", "网络", "架构", "高级"]
TIER_COLORS = [
    (168, 176, 196),
    (108, 140, 255),
    (170, 90, 255),
    (255, 138, 128),
    (255, 213, 79),
]
# 商店出现概率：行=当前开放层数，列=Tier1..5（经典层级权重）
TIER_ODDS = [
    (100, 0, 0, 0, 0),
    (70, 30, 0, 0, 0),
    (60, 30, 10, 0, 0),
    (50, 32, 15, 3, 0),
    (40, 33, 20, 6, 1),
]

# 星级
STAR_BONUS = {1: 0, 2: 2, 3: 6}   # 每星额外攻/血


@dataclass
class WordSpec:
    """词库中的一种词汇（棋子原型）。"""

    word: str          # 英文单词（技能名/展示名）
    cn: str            # 中文释义
    tier: int          # 1-5
    cost: int          # 购买费用
    base_atk: int
    base_hp: int
    skill: str         # 技能 key，对应 _cast_* 方法
    skill_cn: str      # 技能中文说明
    color: Tuple[int, int, int]


# ---------- 词库：纯计算机词汇，技能=单词本义 ----------
WORDS: List[WordSpec] = []


def _w(word, cn, tier, cost, atk, hp, skill, skill_cn, color):
    WORDS.append(WordSpec(word, cn, tier, cost, atk, hp, skill, skill_cn, color))


# T1 入门
_w("bug", "缺陷/虫子", 1, 3, 2, 2, "bug", "死亡后留下一只 1/1 小虫子", (255, 140, 120))
_w("java", "Java 语言", 1, 3, 2, 3, "java", "编译执行：攻击后连击 1 次", (255, 183, 77))
_w("api", "接口", 1, 3, 2, 3, "api", "调用：开局给随机队友 +2 攻", (129, 199, 132))
_w("sql", "查询语言", 1, 3, 3, 2, "sql", "查询：攻击优先打血最少的敌人", (144, 202, 249))
_w("stack", "堆栈", 1, 2, 1, 4, "stack", "堆叠：替后排队友挡 1 次伤害", (190, 170, 255))
_w("git", "版本控制", 1, 3, 2, 3, "git", "提交：每有队友死亡 +2 攻", (255, 213, 79))
_w("shell", "外壳", 1, 2, 1, 4, "shell", "反弹：受击后对攻击者造成 1 点伤害", (178, 235, 242))
_w("loop", "循环", 1, 3, 3, 2, "loop", "重复：每回合首次攻击连打 2 次", (255, 200, 230))
# T2 基础
_w("python", "Python 语言", 2, 4, 3, 3, "python", "解释执行：攻击 30% 概率伤害×2", (255, 213, 79))
_w("cache", "缓存", 2, 3, 2, 3, "cache", "命中：攻击满血敌人伤害×2", (255, 170, 120))
_w("heap", "堆内存", 2, 3, 2, 3, "heap", "分配：受击时随机队友 +1 攻", (150, 230, 170))
_w("thread", "线程", 2, 4, 3, 2, "thread", "并发：攻击 25% 概率多打一次", (255, 180, 220))
_w("class", "类", 2, 4, 2, 3, "class", "继承：继承我方最前排单位的攻击", (200, 190, 255))
_w("kernel", "内核", 2, 4, 3, 4, "kernel", "核心：开局自身 +4 攻", (255, 150, 90))
_w("array", "数组", 2, 3, 3, 2, "array", "下标：攻击附带溅射 1 点伤害", (255, 200, 140))
_w("memory", "内存", 2, 3, 2, 4, "memory", "存储：开局全队 +2 血", (190, 220, 255))
# T3 网络/运行时
_w("docker", "容器", 3, 5, 3, 3, "docker", "镜像：开局复制一份自己", (140, 210, 255))
_w("router", "路由器", 3, 4, 2, 4, "router", "转发：受击时把 1 点伤害转给最前排", (255, 190, 120))
_w("node", "节点", 3, 4, 3, 3, "node", "连接：开局给相邻队友 +1 攻", (200, 230, 150))
_w("server", "服务器", 3, 4, 1, 6, "server", "服务：开局全队 +1 血", (255, 220, 220))
_w("queue", "队列", 3, 4, 3, 3, "queue", "排队：本回合后排队友先出手 1 次", (220, 190, 255))
_w("cookie", "会话饼干", 3, 3, 2, 3, "cookie", "会话：死亡后留下一块饼干（下次喂食效果×2）", (255, 210, 170))
_w("socket", "套接字", 3, 4, 3, 3, "socket", "连接：受击时全队回 1 血", (190, 190, 255))
_w("virus", "病毒", 3, 4, 4, 2, "virus", "感染：攻击后把 1 点伤害传染给另一个敌人", (255, 140, 200))
# T4 架构
_w("cluster", "集群", 4, 5, 3, 4, "cluster", "分布式：开局把自身血量分摊给全队", (160, 230, 180))
_w("backend", "后端", 4, 5, 4, 4, "backend", "处理：每回合给最弱队友 +2 血", (255, 170, 170))
_w("database", "数据库", 4, 5, 5, 3, "database", "查询：攻击时读取数据库，伤害+2", (180, 210, 255))
_w("firewall", "防火墙", 4, 5, 2, 6, "firewall", "拦截：开局挡掉前 2 次攻击", (255, 160, 110))
_w("proxy", "代理", 4, 5, 3, 3, "proxy", "代理：受击时 50% 转移给随机队友", (210, 190, 255))
_w("monitor", "监控", 4, 5, 3, 4, "monitor", "监控：死亡时全队回 2 血", (255, 220, 140))
_w("pipeline", "流水线", 4, 5, 4, 3, "pipeline", "流水：攻击后队友也攻击 1 次", (200, 240, 220))
_w("encrypt", "加密", 4, 5, 3, 5, "encrypt", "加密：受击时全队 +1 攻", (255, 200, 190))
# T5 高级
_w("kubernetes", "容器编排", 5, 7, 4, 4, "kubernetes", "编排：开局把自身攻击分摊给全队", (255, 190, 80))
_w("crypto", "密码学", 5, 7, 4, 4, "crypto", "加密：开局隐形 1 回合", (200, 170, 255))
_w("micro", "微服务", 5, 7, 5, 3, "micro", "微服务：死亡时分裂两只半属性小服务", (170, 240, 255))
_w("quantum", "量子计算", 5, 7, 5, 3, "quantum", "量子叠加：攻击 50% 概率打 2 次", (255, 160, 255))
_w("blockchain", "区块链", 5, 7, 4, 5, "blockchain", "链式：每回合 +1 攻 +1 血（永久累计）", (255, 220, 110))
_w("botnet", "僵尸网络", 5, 7, 4, 3, "botnet", "僵尸网络：死亡时全队 +1 攻", (180, 220, 150))


WORD_BY_KEY = {w.word: w for w in WORDS}


@dataclass
class FoodSpec:
    name: str
    cn: str
    cost: int
    effect: str       # apple|honey|garlic|chocolate
    desc: str
    color: Tuple[int, int, int]


FOODS: List[FoodSpec] = [
    FoodSpec("Apple", "苹果", 3, "apple", "喂食：+1 攻 +1 血", (235, 120, 110)),
    FoodSpec("Honey", "蜂蜜", 3, "honey", "喂食：死亡时召唤 1/1 小蜜蜂", (255, 200, 100)),
    FoodSpec("Garlic", "大蒜", 3, "garlic", "喂食：受击减伤 1", (240, 240, 230)),
    FoodSpec("Chocolate", "巧克力", 4, "chocolate", "喂食：当 1 份同名升星材料", (160, 120, 90)),
]


@dataclass
class Unit:
    """一个已上场的词汇单位（战斗中可复制的战斗单位）。"""

    word: str
    cn: str
    tier: int
    atk: int
    hp: int
    max_hp: int
    skill: str
    skill_cn: str
    star: int = 1           # 1-3
    honey: bool = False     # 死亡召唤蜜蜂
    garlic: bool = False    # 受击减伤 1
    cookie: bool = False    # 死亡留饼干（下次喂食效果×2）
    buffed_atk: int = 0     # 战斗中临时攻击加成（cloned/micro 用）
    cloned: bool = False    # docker 镜像标记（镜像不带镜像）
    dead_atk: int = 0       # git：本局死亡的队友数
    chain_atk: int = 0      # blockchain：每回合累计
    battle_extra_atk: int = 0  # database 本回合读取加成

    @classmethod
    def from_spec(cls, spec: WordSpec, star: int = 1) -> "Unit":
        b = STAR_BONUS.get(star, 0)
        atk = spec.base_atk + b
        hp = spec.base_hp + b
        return cls(
            word=spec.word, cn=spec.cn, tier=spec.tier,
            atk=atk, hp=hp, max_hp=hp,
            skill=spec.skill, skill_cn=spec.skill_cn, star=star,
        )

    @property
    def total_atk(self) -> int:
        return self.atk + self.buffed_atk + self.dead_atk + self.chain_atk + self.battle_extra_atk

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def display(self) -> str:
        return f"{self.word}({self.cn})"

    def copy_for_battle(self) -> "Unit":
        return Unit(
            word=self.word, cn=self.cn, tier=self.tier,
            atk=self.atk, hp=self.hp, max_hp=self.max_hp,
            skill=self.skill, skill_cn=self.skill_cn, star=self.star,
            honey=self.honey, garlic=self.garlic, cookie=self.cookie,
            buffed_atk=self.buffed_atk, cloned=self.cloned,
            dead_atk=self.dead_atk, chain_atk=self.chain_atk,
        )


@dataclass
class ShopSlot:
    kind: str = ""          # "word" | "food" | ""
    spec: object = None     # WordSpec 或 FoodSpec


class WordArenaGame:
    def __init__(self, session: GameSession):
        self.session = session
        self.initial_gold = session.gold
        self.initial_diamond = session.diamond
        self.gold = session.gold
        self.diamond = session.diamond

        self.phase = "title"  # title | shop | battle | battle_res | over
        self.round_no = 0
        self.trophies = 0
        self.lives = MAX_LIVES
        self.wins = 0
        self.losses = 0
        self.log = ""
        self.log_t = 0.0
        self.over_msg = ""
        self.entry_paid = False
        self.available_tiers = 1
        self.letters_awarded: List[Tuple[str, int]] = []
        self.used_letters: List[str] = []

        # 商店
        self.shop: List[ShopSlot] = [ShopSlot() for _ in range(SHOP_SLOTS)]
        self.frozen: List[bool] = [False] * SHOP_SLOTS
        self.shop_initial_rolled = False

        # 队伍
        self.team: List[Optional[Unit]] = [None] * MAX_TEAM
        self.selected_slot = 0

        # 战斗
        self.battle_players: List[Optional[Unit]] = []
        self.battle_enemies: List[Optional[Unit]] = []
        self.battle_events: List[dict] = []
        self.battle_event_idx = 0
        self.battle_event_cooldown = 0.0
        self.float_texts: List[dict] = []
        self.battle_over = False
        self.battle_result_msg = ""

        # 输入
        self._click_zones: List[Tuple[pygame.Rect, str, tuple]] = []
        self.auto_dummy = "SDL_VIDEODRIVER" in __import__("os").environ and \
            __import__("os").environ.get("SDL_VIDEODRIVER") == "dummy"
        self.dummy_t = 0.0

        pygame.init()
        pygame.display.set_caption("Adventure - 计算机词汇自走棋")
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.font = load_font(22)
        self.font_sm = load_font(17)
        self.font_lg = load_font(30, bold=True)
        self.font_lg2 = load_font(40, bold=True)

    # ---------- 主循环 ----------
    def run(self) -> None:
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.MOUSEBUTTONDOWN:
                    if e.button == 1:
                        self._on_mouse_down(e.pos)
                elif e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE:
                        running = False
                    elif e.key == pygame.K_SPACE:
                        self._on_space()
            if self.phase == "battle":
                self._update_battle(dt)
            if self.log_t > 0:
                self.log_t -= dt
            if self.auto_dummy:
                self._dummy_step(dt)
            self._draw()
            if self.phase == "over" and not self.auto_dummy:
                pygame.time.wait(1100)
                running = False
            elif self.phase == "over" and self.auto_dummy:
                running = False
        self._write_result()

    def _on_space(self) -> None:
        if self.phase == "title":
            if not self.entry_paid:
                self._pay_entry()
                return
            self._start_run()
        elif self.phase == "battle_res":
            self._next_round_or_end()

    def _on_mouse_down(self, pos) -> None:
        for rect, action, args in self._click_zones:
            if rect.collidepoint(pos):
                getattr(self, f"_click_{action}")(*args)
                return

    # ---------- 阶段流转 ----------
    def _pay_entry(self) -> None:
        if self.gold < ENTRY_FEE:
            self._set_log(f"金币不足，需要 {ENTRY_FEE}")
            return
        self.gold -= ENTRY_FEE
        self.entry_paid = True
        self._set_log(f"已支付入场费 {ENTRY_FEE} 金币，按空格开始")

    def _start_run(self) -> None:
        self.phase = "shop"
        self.round_no = 1
        self.available_tiers = 1
        self.gold += ROUND_GOLD
        self._roll_shop(initial=True)
        self._build_enemy_team()
        self._set_log("第 1 回合：买词汇和食物，然后按空格开战")

    def _next_round_or_end(self) -> None:
        if self.trophies >= WIN_TROPHIES:
            self.phase = "over"
            self.over_msg = f"通关！{self.trophies} 奖杯"
            self._award_letters(win=True)
            return
        if self.lives <= 0:
            self.phase = "over"
            self.over_msg = f"生命耗尽：{self.trophies} 奖杯"
            self._award_letters(win=False)
            return
        # 仁慈机制：第 3 回合起，若前两回合都输，回 1 命
        if self.round_no == 3 and self.losses >= 2:
            self.lives = min(MAX_LIVES, self.lives + 1)
            self._set_log("仁慈机制：你连输两场，回复 1 点生命")
        self.round_no += 1
        self.available_tiers = min(TIER_COUNT, 1 + (self.round_no - 1) // 2)
        self.gold += ROUND_GOLD
        self._roll_shop(initial=True)
        self._build_enemy_team()
        self.phase = "shop"
        self._set_log(f"第 {self.round_no} 回合：商店（解锁 {TIER_NAMES[self.available_tiers-1]} 层词汇）")

    # ---------- 商店 ----------
    def _roll_shop(self, initial: bool = False) -> None:
        if not initial:
            if self.gold <= 0:
                self._set_log("金币不足，无法刷新")
                return
            self.gold -= 1
        odds = TIER_ODDS[self.available_tiers - 1]
        for i in range(SHOP_SLOTS):
            if self.frozen[i] and self.shop[i].spec is not None:
                continue
            if random.random() < 0.28:
                self.shop[i] = ShopSlot(kind="food", spec=random.choice(FOODS))
            else:
                tier = random.choices(range(1, TIER_COUNT + 1), weights=odds, k=1)[0]
                pool = [w for w in WORDS if w.tier == tier]
                spec = random.choice(pool) if pool else random.choice(WORDS)
                self.shop[i] = ShopSlot(kind="word", spec=spec)
            self.frozen[i] = False

    def _click_buy_shop(self, idx: int) -> None:
        slot = self.shop[idx]
        if slot.spec is None:
            return
        if self.gold < slot.spec.cost:
            self._set_log(f"金币不足，需要 {slot.spec.cost}")
            return
        if slot.kind == "word":
            ok = self._buy_word(slot.spec)
        else:
            ok = self._buy_food(slot.spec)
        if ok:
            self.shop[idx] = ShopSlot()
            self.frozen[idx] = False

    def _buy_word(self, spec: WordSpec) -> bool:
        unit = Unit.from_spec(spec)
        # 先尝试同名合成
        for i, u in enumerate(self.team):
            if u is not None and u.word == spec.word and u.star < 3:
                self.gold -= spec.cost
                u.star += 1
                b = STAR_BONUS.get(u.star, 0)
                u.atk = spec.base_atk + b
                u.hp = spec.base_hp + b
                u.max_hp = u.hp
                self._set_log(f"升星！{spec.word} → {u.star}★（{spec.cn}）")
                return True
        # 放入空槽
        for i, u in enumerate(self.team):
            if u is None:
                self.gold -= spec.cost
                self.team[i] = unit
                self._set_log(f"获得词汇 {spec.word}（{spec.cn}）")
                return True
        self._set_log("队伍已满，无法购买")
        return False

    def _buy_food(self, spec: FoodSpec) -> bool:
        unit = self.team[self.selected_slot]
        if unit is None:
            self._set_log("先选择要喂食的队伍槽位")
            return False
        if self.gold < spec.cost:
            self._set_log(f"金币不足，需要 {spec.cost}")
            return False
        self.gold -= spec.cost
        if spec.effect == "apple":
            unit.atk += 1
            unit.max_hp += 1
            unit.hp += 1
        elif spec.effect == "honey":
            unit.honey = True
        elif spec.effect == "garlic":
            unit.garlic = True
        elif spec.effect == "chocolate":
            # 当 1 份同名升星材料
            if unit.star < 3:
                unit.star += 1
                b = STAR_BONUS.get(unit.star, 0)
                spec0 = WORD_BY_KEY[unit.word]
                unit.atk = spec0.base_atk + b
                unit.hp = spec0.base_hp + b
                unit.max_hp = unit.hp
                self._set_log(f"巧克力：{unit.word} → {unit.star}★")
            else:
                unit.atk += 2
                unit.max_hp += 2
                unit.hp += 2
                self._set_log(f"巧克力：{unit.word} 已满星，改为 +2 攻血")
        self._set_log(f"喂食 {spec.name} 给 {unit.word}")
        return True

    def _click_sell(self, idx: int) -> None:
        u = self.team[idx]
        if u is None:
            return
        refund = max(1, (u.star - 1) + WORD_BY_KEY[u.word].cost // 3)
        self.gold += refund
        self.team[idx] = None
        self._set_log(f"卖出 {u.word}，返还 {refund} 金币")

    def _click_team_slot(self, idx: int) -> None:
        if self.phase != "shop":
            return
        self.selected_slot = idx
        self._set_log(f"选中队伍槽位 {idx + 1}")

    def _click_refresh(self) -> None:
        if self.phase != "shop":
            return
        self._roll_shop()

    def _click_freeze(self, idx: int) -> None:
        if self.phase != "shop" or self.shop[idx].spec is None:
            return
        self.frozen[idx] = not self.frozen[idx]
        self._set_log("已冻结" if self.frozen[idx] else "已解冻")

    def _click_start_battle(self) -> None:
        if self.phase != "shop":
            return
        if not any(u is not None for u in self.team):
            self._set_log("至少上阵一个词汇单位")
            return
        self._start_battle()

    def _start_battle(self) -> None:
        self.phase = "battle"
        self.battle_players = [u.copy_for_battle() if u else None for u in self.team]
        self.battle_enemies = [u.copy_for_battle() for u in self.enemy_team]
        self.battle_events = []
        self.battle_event_idx = 0
        self.battle_event_cooldown = 0.0
        self.float_texts = []
        self.battle_over = False
        self.battle_result_msg = ""
        self._build_battle_events()

    # ---------- 敌方 ----------
    def _build_enemy_team(self) -> None:
        cnt = min(3 + self.round_no // 2, MAX_TEAM)
        avail = min(TIER_COUNT, 1 + (self.round_no - 1) // 2)
        team: List[Unit] = []
        for _ in range(cnt):
            tier = random.randint(1, avail)
            pool = [w for w in WORDS if w.tier == tier]
            spec = random.choice(pool) if pool else random.choice(WORDS)
            star = 1 if self.round_no < 6 else random.choice([1, 1, 2])
            u = Unit.from_spec(spec, star)
            u.atk += self.round_no // 2
            u.max_hp += self.round_no // 2
            u.hp = u.max_hp
            team.append(u)
        self.enemy_team = team

    # ---------- 战斗（先全量模拟成事件队列，再回放） ----------
    def _alive(self, team: List[Optional[Unit]]) -> List[Unit]:
        return [u for u in team if u is not None and u.alive]

    def _build_battle_events(self) -> None:
        self.battle_events = [{"type": "start", "msg": f"第 {self.round_no} 回合战斗开始"}]
        # 开局技能（先手方全员）
        for u in self._alive(self.battle_players):
            self._cast_skill(u, self.battle_players, self.battle_enemies)
        for u in self._alive(self.battle_enemies):
            self._cast_skill(u, self.battle_enemies, self.battle_players)

        # 回合模拟：每回合双方各行动一轮，直到一方全灭
        guard = 0
        while self._alive(self.battle_players) and self._alive(self.battle_enemies) and guard < 60:
            guard += 1
            self._one_round(self.battle_players, self.battle_enemies)
            if self._alive(self.battle_players) and self._alive(self.battle_enemies):
                self._one_round(self.battle_enemies, self.battle_players)

        if self._alive(self.battle_players) and not self._alive(self.battle_enemies):
            self.battle_events.append({"type": "end", "win": True, "msg": "胜利！"})
        elif self._alive(self.battle_enemies) and not self._alive(self.battle_players):
            self.battle_events.append({"type": "end", "win": False, "msg": "失败…"})
        else:
            self.battle_events.append({"type": "end", "win": False, "msg": "平局"})

    def _one_round(self, board: List[Optional[Unit]], targets: List[Optional[Unit]]) -> None:
        actors = self._alive(board)
        if self._has_skill(board, "queue"):
            actors.reverse()
        for u in actors:
            if not u.alive or not self._alive(targets):
                break
            live = self._alive(targets)
            if u.skill == "sql":
                target = min(live, key=lambda t: t.hp)
            else:
                target = live[0]
            self._unit_attack(u, target)

    def _has_skill(self, board: List[Optional[Unit]], skill: str) -> bool:
        return any(u is not None and u.skill == skill for u in board)

    def _board_of(self, u: Unit) -> List[Optional[Unit]]:
        if any(x is u for x in self.battle_players):
            return self.battle_players
        return self.battle_enemies

    def _unit_attack(self, attacker: Unit, target: Unit) -> None:
        dmg = max(1, attacker.total_atk)
        # loop：每回合首次攻击连打 2 次
        hits = 2 if attacker.skill == "loop" else 1
        # quantum：50% 概率打 2 次
        if attacker.skill == "quantum" and random.random() < 0.50:
            hits += 1
            self.battle_events.append({"type": "skill", "msg": f"{attacker.word} 量子叠加！"})
        for _ in range(hits):
            if not target.alive:
                break
            dmg_this = dmg
            # cache：打满血敌人伤害×2
            if attacker.skill == "cache" and target.hp >= target.max_hp:
                dmg_this *= 2
            # python：30% 概率伤害×2
            if attacker.skill == "python" and random.random() < 0.30:
                dmg_this *= 2
            # database：攻击时读取，本回合伤害+2
            if attacker.skill == "database":
                attacker.battle_extra_atk += 2
                dmg_this += 2
            self._deal_damage(attacker, target, dmg_this)
        if not target.alive:
            return
        # java：攻击后连击 1 次
        if attacker.skill == "java" and target.alive:
            self._deal_damage(attacker, target, dmg)
        # thread：25% 概率多打一次
        if attacker.skill == "thread" and target.alive and random.random() < 0.25:
            self._deal_damage(attacker, target, dmg)
        # virus：感染，把 1 点伤害传染给另一个敌人
        if attacker.skill == "virus" and target.alive:
            board = self._board_of(target)
            others = [t for t in self._alive(board) if t is not target]
            if others:
                self._deal_damage(attacker, random.choice(others), 1)
        # pipeline：队友也攻击 1 次
        if attacker.skill == "pipeline" and target.alive:
            board = self._board_of(attacker)
            allies = [a for a in self._alive(board) if a is not attacker]
            enemies = self._alive(self.battle_enemies if board is self.battle_players else self.battle_players)
            if allies and enemies:
                partner = random.choice(allies)
                self._deal_damage(partner, random.choice(enemies), max(1, partner.total_atk))

    def _deal_damage(self, attacker: Unit, target: Unit, dmg: int) -> None:
        if target.hp <= 0:
            return
        # 防火墙：拦截前 2 次攻击
        if target.skill == "firewall" and getattr(target, "_shield", 0) > 0:
            target._shield -= 1
            self.battle_events.append({"type": "block", "msg": f"{target.word} 防火墙拦截"})
            return
        # 隐身（crypto 开局 1 回合）
        if getattr(target, "_invisible", False):
            self.battle_events.append({"type": "block", "msg": f"{target.word} 隐形中"})
            return
        # 大蒜减伤
        dmg = max(0, dmg - (1 if target.garlic else 0))
        if dmg <= 0:
            self.battle_events.append({"type": "block", "msg": f"{target.word} 大蒜减伤"})
            return
        target.hp -= dmg
        self.battle_events.append({
            "type": "hit", "msg": f"{attacker.word} → {target.word} -{dmg}",
            "target_idx": self._unit_idx(target),
        })
        # socket：受击时全队回 1 血
        if target.alive and target.skill == "socket":
            for a in self._alive(self._board_of(target)):
                a.hp = min(a.max_hp, a.hp + 1)
            self.battle_events.append({"type": "skill", "msg": f"{target.word} 套接字：全队回 1 血"})
        # shell 反弹
        if target.alive and target.skill == "shell" and attacker.alive:
            attacker.hp -= 1
            self.battle_events.append({"type": "hit", "msg": f"{target.word} 反弹 -1"})
            if attacker.hp <= 0:
                self._on_faint(attacker)
        # heap：受击时随机队友 +1 攻
        if target.alive and target.skill == "heap":
            allies = [a for a in self._alive(self._board_of(target)) if a is not target]
            if allies:
                random.choice(allies).buffed_atk += 1
        # router：受击时把 1 点伤害转给最前排
        if target.alive and target.skill == "router" and attacker.alive:
            board = self._board_of(target)
            front = [a for a in self._alive(board) if a is not target]
            if front:
                front[0].hp -= 1
                self.battle_events.append({"type": "hit", "msg": f"{target.word} 路由转移"})
                if front[0].hp <= 0:
                    self._on_faint(front[0])
        # proxy：50% 转移给随机队友
        if target.alive and target.skill == "proxy" and random.random() < 0.50:
            allies = [a for a in self._alive(self._board_of(target)) if a is not target]
            if allies:
                proxy = random.choice(allies)
                proxy.hp -= max(0, dmg)
                self.battle_events.append({"type": "hit", "msg": f"{target.word} 代理转移"})
                if proxy.hp <= 0:
                    self._on_faint(proxy)
        # 死亡检查
        if not target.alive:
            self._on_faint(target)

    def _spawn_into_board(self, board: List[Optional[Unit]], unit: Unit) -> bool:
        """把新单位放进棋盘的第一个空槽。"""
        for i, x in enumerate(board):
            if x is None:
                board[i] = unit
                return True
        return False

    def _unit_idx(self, u: Unit) -> int:
        for i, x in enumerate(self.battle_players):
            if x is u:
                return i
        for i, x in enumerate(self.battle_enemies):
            if x is u:
                return i + 100
        return 0

    def _on_faint(self, u: Unit) -> None:
        team = self._board_of(u)
        self.battle_events.append({"type": "faint", "msg": f"{u.word} 倒下了"})
        # 从棋盘移除（原地留下 None，保持槽位顺序）
        try:
            team[team.index(u)] = None
        except ValueError:
            pass
        # honey：召唤 1/1 蜜蜂
        if u.honey:
            bee = Unit.from_spec(WORD_BY_KEY["bug"])
            bee.atk, bee.hp, bee.max_hp = 1, 1, 1
            if self._spawn_into_board(team, bee):
                self.battle_events.append({"type": "spawn", "msg": "蜂蜜：蜜蜂 1/1 出现"})
        # cookie：死亡留饼干（下次喂食效果×2）
        if u.cookie:
            self.battle_events.append({"type": "spawn", "msg": "会话饼干已留下"})
        # monitor：死亡时全队回 2 血
        if u.skill == "monitor":
            for a in self._alive(team):
                a.hp = min(a.max_hp, a.hp + 2)
            self.battle_events.append({"type": "spawn", "msg": "监控：全队回 2 血"})
        # botnet：死亡时全队 +1 攻
        if u.skill == "botnet":
            for a in self._alive(team):
                a.buffed_atk += 1
            self.battle_events.append({"type": "spawn", "msg": "僵尸网络：全队 +1 攻"})
        # micro：分裂两只半属性小服务
        if u.skill == "micro":
            for _ in range(2):
                m = Unit.from_spec(WORD_BY_KEY["java"])
                m.atk = max(1, u.atk // 2)
                m.hp = max(1, u.hp // 2)
                m.max_hp = m.hp
                self._spawn_into_board(team, m)
            self.battle_events.append({"type": "spawn", "msg": "微服务分裂"})
        # git：队友死亡时 +2 攻
        if team is self.battle_players:
            for a in self._alive(team):
                if a.skill == "git" and a is not u:
                    a.dead_atk += 2

    def _cast_skill(self, u: Unit, own: List[Optional[Unit]], foes: List[Optional[Unit]]) -> None:
        """开局技能。"""
        if u.skill == "api":
            allies = [a for a in self._alive(own) if a is not u]
            if allies:
                random.choice(allies).buffed_atk += 2
                self.battle_events.append({"type": "skill", "msg": f"{u.word} 调用接口：队友 +2 攻"})
        elif u.skill == "kernel":
            u.buffed_atk += 4
            self.battle_events.append({"type": "skill", "msg": f"{u.word} 核心强化 +4 攻"})
        elif u.skill == "memory":
            for a in self._alive(own):
                a.hp = min(a.max_hp, a.hp + 2)
            self.battle_events.append({"type": "skill", "msg": f"{u.word}：全队 +2 血"})
        elif u.skill == "docker":
            if not u.cloned:
                clone = u.copy_for_battle()
                clone.cloned = True
                if self._spawn_into_board(own, clone):
                    self.battle_events.append({"type": "spawn", "msg": f"{u.word} 镜像复制"})
        elif u.skill == "node":
            idx = self._unit_idx(u)
            if idx < len(own):
                for j in (idx - 1, idx + 1):
                    if 0 <= j < len(own) and own[j] is not None and own[j] is not u:
                        own[j].buffed_atk += 1
                self.battle_events.append({"type": "skill", "msg": f"{u.word} 节点连接：相邻 +1 攻"})
        elif u.skill == "server":
            for a in self._alive(own):
                a.hp = min(a.max_hp, a.hp + 1)
            self.battle_events.append({"type": "skill", "msg": f"{u.word}：全队 +1 血"})
        elif u.skill == "class":
            front = self._alive(own)
            if front:
                u.buffed_atk = max(u.buffed_atk, front[0].total_atk)
                self.battle_events.append({"type": "skill", "msg": f"{u.word} 继承前排攻击"})
        elif u.skill == "cluster":
            allies = [a for a in self._alive(own) if a is not u]
            if allies:
                share = u.hp // 4
                for a in allies:
                    a.hp = min(a.max_hp, a.hp + share)
                self.battle_events.append({"type": "skill", "msg": f"{u.word} 集群：血量分摊"})
        elif u.skill == "kubernetes":
            allies = [a for a in self._alive(own) if a is not u]
            if allies:
                share = u.total_atk // 4
                for a in allies:
                    a.buffed_atk += share
                self.battle_events.append({"type": "skill", "msg": f"{u.word} 编排：攻击分摊"})
        elif u.skill == "crypto":
            u._invisible = True
            self.battle_events.append({"type": "skill", "msg": f"{u.word} 加密：隐形 1 回合"})
        elif u.skill == "firewall":
            u._shield = 2
            self.battle_events.append({"type": "skill", "msg": f"{u.word} 防火墙就绪"})
        elif u.skill == "blockchain":
            u.chain_atk += 1
            u.max_hp += 1
            u.hp = min(u.max_hp, u.hp + 1)
            self.battle_events.append({"type": "skill", "msg": f"{u.word} 链式增长 +1/+1"})

    # ---------- 战斗播放 ----------
    def _update_battle(self, dt: float) -> None:
        self.battle_event_cooldown -= dt
        if self.battle_event_cooldown > 0:
            return
        self.battle_event_cooldown = 0.42
        if self.battle_event_idx >= len(self.battle_events):
            if not self.battle_over:
                self._on_battle_end(self.battle_events[-1])
            return
        ev = self.battle_events[self.battle_event_idx]
        self.battle_event_idx += 1
        if ev["type"] == "end":
            self._on_battle_end(ev)
            return
        if ev.get("target_idx") is not None:
            self._spawn_float(ev)
        self._set_log(ev["msg"])

    def _spawn_float(self, ev: dict) -> None:
        # 在对应单位头上飘伤害数字
        idx = ev.get("target_idx", 0)
        if idx < 100 and idx < len(self.battle_players) and self.battle_players[idx]:
            u = self.battle_players[idx]
            x, y = 420 + idx * 150, 320
        else:
            j = idx - 100
            if 0 <= j < len(self.battle_enemies) and self.battle_enemies[j]:
                u = self.battle_enemies[j]
                x, y = 420 + j * 150, 150
            else:
                return
        self.float_texts.append({"x": x, "y": y, "text": ev["msg"].split(" -")[-1], "t": 0.0})

    def _on_battle_end(self, ev: dict) -> None:
        self.battle_over = True
        win = ev.get("win", False)
        if win:
            self.wins += 1
            self.trophies += 1
            gain = round(random.uniform(0.3, 1.2), 1)
            self.gold += gain
            if self.trophies % 3 == 0:
                d = round(random.uniform(0.1, 0.6), 1)
                self.diamond += d
                self.battle_result_msg = f"胜利！+{gain:.1f} 金币，+{d:.1f} 钻石"
            else:
                self.battle_result_msg = f"胜利！+{gain:.1f} 金币"
        else:
            self.losses += 1
            self.lives -= 1
            self.battle_result_msg = f"失败，-1 生命（剩余 {self.lives}）"
        self.phase = "battle_res"

    # ---------- 奖励 ----------
    def _award_letters(self, win: bool) -> None:
        """按表现给 1-2 个字母（稀有度与表现挂钩）。"""
        rar = 0 if not win else (2 if self.round_no >= 12 else 1)
        if win and self.round_no >= 14:
            rar = 3
        for _ in range(2 if win and self.trophies >= WIN_TROPHIES else 1):
            letter = random.choice([c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in self.used_letters])
            self.used_letters.append(letter)
            self.letters_awarded.append((letter, rar))

    def _set_log(self, msg: str) -> None:
        self.log = msg
        self.log_t = 3.0

    # ---------- 绘制 ----------
    def _draw(self) -> None:
        self.screen.fill(COL_BG)
        self._draw_header()
        if self.phase == "title":
            self._draw_title()
        elif self.phase in ("shop", "battle", "battle_res"):
            self._draw_shop_or_battle()
        elif self.phase == "over":
            self._draw_center([self.over_msg, "", "正在结算..."])
        self._draw_footer()
        pygame.display.flip()

    def _draw_header(self) -> None:
        pygame.draw.rect(self.screen, COL_PANEL, (0, 0, W, 54))
        self.screen.blit(self.font.render(f"金币 {self.gold:.1f}", True, COL_GOLD), (16, 10))
        self.screen.blit(self.font.render(f"钻石 {self.diamond:.1f}", True, COL_DIAM), (160, 10))
        self.screen.blit(self.font.render(f"回合 {max(1, self.round_no)}", True, COL_TEXT), (330, 10))
        self.screen.blit(self.font_sm.render(f"层级 {TIER_NAMES[self.available_tiers-1]}", True, COL_MUTED), (470, 16))
        # 奖杯
        self.screen.blit(self.font_sm.render(f"奖杯 {self.trophies}/{WIN_TROPHIES}", True, COL_STAR), (620, 16))
        # 生命
        for i in range(self.lives):
            pygame.draw.circle(self.screen, COL_HP, (W - 40 - i * 26, 26), 8)
        self.screen.blit(self.font_sm.render(f"胜 {self.wins} 负 {self.losses}", True, COL_MUTED), (W - 240, 16))

    def _draw_title(self) -> None:
        lines = [
            ("计算机词汇自走棋", self.font_lg2, COL_TEXT),
            ("用英语计算机词汇当棋子，边玩边学", self.font_sm, COL_MUTED),
            ("商店买词汇/食物 → 三合升星 → 自动战斗 → 集满 10 奖杯通关", self.font_sm, COL_MUTED),
            ("", self.font_sm, COL_MUTED),
            (f"入场费 {ENTRY_FEE} 金币", self.font_sm, COL_GOLD),
            ("按空格 开始 / ESC 退出", self.font_lg, COL_TEXT),
        ]
        y = 140
        for text, f, c in lines:
            s = f.render(text, True, c)
            self.screen.blit(s, (W // 2 - s.get_width() // 2, y))
            y += s.get_height() + 16
        # 词库预览
        self._draw_word_grid()

    def _draw_word_grid(self) -> None:
        x0, y0 = 60, 340
        for i, w in enumerate(WORDS[:12]):
            x = x0 + (i % 4) * 250
            y = y0 + (i // 4) * 110
            pygame.draw.rect(self.screen, COL_CARD, (x, y, 230, 90), border_radius=8)
            pygame.draw.rect(self.screen, TIER_COLORS[w.tier - 1], (x, y, 230, 90), 1, border_radius=8)
            self.screen.blit(self.font_sm.render(f"{w.word}", True, TIER_COLORS[w.tier - 1]), (x + 10, y + 8))
            self.screen.blit(self.font_sm.render(w.cn, True, COL_TEXT), (x + 10, y + 30))
            self.screen.blit(self.font_sm.render(f"T{w.tier} {w.skill_cn}", True, COL_MUTED), (x + 10, y + 56))

    def _draw_shop_or_battle(self) -> None:
        # 左：商店卡片区
        pygame.draw.rect(self.screen, COL_PANEL, (16, 70, 420, 430), border_radius=12)
        self.screen.blit(self.font.render("商店", True, COL_TEXT), (30, 86))
        # 刷新按钮
        self._register_click(pygame.Rect(330, 82, 90, 32), "refresh")
        pygame.draw.rect(self.screen, COL_CARD, (330, 82, 90, 32), border_radius=8)
        self.screen.blit(self.font_sm.render("刷新 -1", True, COL_GOLD), (344, 90))
        for i, slot in enumerate(self.shop):
            x, y = 30, 130 + i * 120
            pygame.draw.rect(self.screen, COL_CARD, (x, y, 390, 105), border_radius=10)
            if self.frozen[i]:
                pygame.draw.rect(self.screen, COL_ACCENT, (x, y, 390, 105), 2, border_radius=10)
            if slot.spec is None:
                self.screen.blit(self.font_sm.render("已售出", True, COL_MUTED), (x + 20, y + 30))
                continue
            self._register_click(pygame.Rect(x, y, 390, 105), "buy_shop", (i,))
            self._register_click(pygame.Rect(x + 350, y + 8, 34, 24), "freeze", (i,))
            freeze_c = COL_ACCENT if self.frozen[i] else COL_MUTED
            self.screen.blit(self.font_sm.render("冻", True, freeze_c), (x + 360, y + 12))
            if slot.kind == "word":
                spec = slot.spec
                c = TIER_COLORS[spec.tier - 1]
                self.screen.blit(self.font.render(f"{spec.word}", True, c), (x + 20, y + 12))
                self.screen.blit(self.font_sm.render(f"T{spec.tier} {spec.cn}", True, COL_TEXT), (x + 20, y + 42))
                self.screen.blit(self.font_sm.render(f"攻{spec.base_atk} 血{spec.base_hp}", True, COL_MUTED), (x + 150, y + 12))
                self.screen.blit(self.font_sm.render(spec.skill_cn, True, COL_MUTED), (x + 20, y + 66))
                self.screen.blit(self.font_sm.render(f"${spec.cost}", True, COL_GOLD), (x + 340, y + 70))
            else:
                f = slot.spec
                self.screen.blit(self.font.render(f.name, True, COL_FOOD), (x + 20, y + 12))
                self.screen.blit(self.font_sm.render(f.cn, True, COL_TEXT), (x + 20, y + 42))
                self.screen.blit(self.font_sm.render(f.desc, True, COL_MUTED), (x + 20, y + 66))
                self.screen.blit(self.font_sm.render(f"${f.cost}", True, COL_GOLD), (x + 340, y + 70))
        # 队伍
        pygame.draw.rect(self.screen, COL_PANEL, (16, 520, 420, 165), border_radius=12)
        self.screen.blit(self.font.render("我的队伍", True, COL_TEXT), (30, 536))
        self.screen.blit(self.font_sm.render("（点击选择喂食目标）", True, COL_MUTED), (130, 542))
        for i, u in enumerate(self.team):
            x, y = 30 + i * 85, 572
            rr = pygame.Rect(x, y, 76, 84)
            if self.selected_slot == i and self.phase == "shop":
                pygame.draw.rect(self.screen, COL_ACCENT, rr, 2, border_radius=10)
            self._register_click(rr, "team_slot", (i,))
            self._register_click(pygame.Rect(x, y + 92, 76, 20), "sell", (i,))
            if u is None:
                pygame.draw.rect(self.screen, COL_CARD, rr, border_radius=10)
                self.screen.blit(self.font_sm.render("空", True, COL_MUTED), (x + 26, y + 30))
                continue
            pygame.draw.rect(self.screen, COL_CARD, rr, border_radius=10)
            c = TIER_COLORS[u.tier - 1]
            self.screen.blit(self.font_sm.render(u.word, True, c), (x + 8, y + 6))
            self.screen.blit(self.font_sm.render(f"{u.total_atk}/{u.hp}", True, COL_TEXT), (x + 8, y + 30))
            self.screen.blit(self.font_sm.render("★" * u.star, True, COL_STAR), (x + 8, y + 52))
            self.screen.blit(self.font_sm.render("卖", True, COL_HP), (x + 56, y + 94))

        # 右：开战按钮 / 战斗
        if self.phase == "shop":
            self._register_click(pygame.Rect(560, 520, 200, 50), "start_battle")
            pygame.draw.rect(self.screen, COL_ACCENT, (560, 520, 200, 50), border_radius=12)
            self.screen.blit(self.font.render("开战（空格）", True, COL_TEXT), (590, 532))
            # 敌方预览
            pygame.draw.rect(self.screen, COL_PANEL, (520, 70, 560, 430), border_radius=12)
            self.screen.blit(self.font.render("敌方（预览）", True, COL_ENEMY), (540, 86))
            for i, u in enumerate(self.enemy_team):
                x = 540 + i * 100
                y = 120
                pygame.draw.rect(self.screen, COL_CARD, (x, y, 90, 110), border_radius=10)
                c = TIER_COLORS[u.tier - 1]
                self.screen.blit(self.font_sm.render(u.word, True, c), (x + 8, y + 8))
                self.screen.blit(self.font_sm.render(f"{u.total_atk}/{u.hp}", True, COL_TEXT), (x + 8, y + 34))
                self.screen.blit(self.font_sm.render("★" * u.star, True, COL_STAR), (x + 8, y + 56))
        else:
            # 战斗中/结算：双方对阵
            pygame.draw.rect(self.screen, COL_PANEL, (520, 70, 560, 430), border_radius=12)
            self.screen.blit(self.font.render("战斗", True, COL_ENEMY), (540, 86))
            self._draw_battle_units()
            if self.phase == "battle_res":
                self._register_click(pygame.Rect(820, 580, 240, 52), "next_round")
                pygame.draw.rect(self.screen, COL_ACCENT, (820, 580, 240, 52), border_radius=12)
                self.screen.blit(self.font_sm.render(f"继续（空格） {self.battle_result_msg}", True, COL_TEXT), (836, 594))

    def _click_next_round(self) -> None:
        if self.phase == "battle_res":
            self._next_round_or_end()

    def _draw_battle_units(self) -> None:
        # 我方（左侧）
        for i, u in enumerate(self.battle_players):
            if u is None:
                continue
            x, y = 540 + i * 100, 160
            c = TIER_COLORS[u.tier - 1]
            pygame.draw.rect(self.screen, COL_CARD, (x, y, 90, 110), border_radius=10)
            if not u.alive:
                pygame.draw.rect(self.screen, (30, 32, 45), (x, y, 90, 110), border_radius=10)
                self.screen.blit(self.font_sm.render("倒下", True, COL_MUTED), (x + 24, y + 40))
                continue
            self.screen.blit(self.font_sm.render(u.word, True, c), (x + 8, y + 8))
            self.screen.blit(self.font_sm.render(f"{u.total_atk}/{u.hp}", True, COL_TEXT), (x + 8, y + 34))
            self.screen.blit(self.font_sm.render("★" * u.star, True, COL_STAR), (x + 8, y + 56))
        # 敌方（右侧）
        for i, u in enumerate(self.battle_enemies):
            if u is None:
                continue
            x, y = 740 + i * 100, 160
            c = TIER_COLORS[u.tier - 1]
            pygame.draw.rect(self.screen, COL_CARD, (x, y, 90, 110), border_radius=10)
            if not u.alive:
                pygame.draw.rect(self.screen, (30, 32, 45), (x, y, 90, 110), border_radius=10)
                self.screen.blit(self.font_sm.render("倒下", True, COL_MUTED), (x + 24, y + 40))
                continue
            self.screen.blit(self.font_sm.render(u.word, True, c), (x + 8, y + 8))
            self.screen.blit(self.font_sm.render(f"{u.total_atk}/{u.hp}", True, COL_TEXT), (x + 8, y + 34))
            self.screen.blit(self.font_sm.render("★" * u.star, True, COL_STAR), (x + 8, y + 56))

    def _draw_float_texts(self) -> None:
        for f in self.float_texts:
            f["t"] += 1 / FPS
            if f["t"] > 0.9:
                continue
            alpha = int(255 * (1 - f["t"] / 0.9))
            s = self.font_sm.render(f["text"], True, (255, 255, 255))
            s.set_alpha(alpha)
            self.screen.blit(s, (int(f["x"]), int(f["y"]) - int(f["t"] * 30)))

    def _draw_footer(self) -> None:
        pygame.draw.rect(self.screen, COL_PANEL, (0, H - 40, W, 40))
        msg = self.log or "ESC 退出并结算"
        self.screen.blit(self.font_sm.render(msg, True, COL_MUTED), (14, H - 30))

    def _draw_center(self, lines: List[str]) -> None:
        y = H // 2 - len(lines) * 30
        for ln in lines:
            s = self.font_lg.render(ln, True, COL_TEXT)
            self.screen.blit(s, (W // 2 - s.get_width() // 2, y))
            y += 60

    def _register_click(self, rect: pygame.Rect, action: str, *args) -> None:
        self._click_zones.append((rect, action, args))

    # ---------- dummy 无头模式 ----------
    def _dummy_step(self, dt: float) -> None:
        self.dummy_t += dt
        if self.phase == "title":
            if self.gold >= ENTRY_FEE and not self.entry_paid:
                self._pay_entry()
                return
            if self.entry_paid and self.dummy_t > 0.3:
                self._start_run()
                self.dummy_t = 0.0
            return
        if self.phase == "shop":
            if self.dummy_t < 1.0:
                # 有金币就买第一个可买的
                for i, slot in enumerate(self.shop):
                    if slot.spec is not None and self.gold >= slot.spec.cost:
                        self._click_buy_shop(i)
                        return
                # 都买不起：刷新（金币不足时会被拒绝）
                self._click_refresh()
            elif self.dummy_t > 2.2:
                # 空队也强制开战（dummy 就是要跑完流程）
                self._start_battle()
                self.dummy_t = 0.0
            return
        if self.phase == "battle":
            # dummy 加速回放
            self.battle_event_cooldown = 0.0
            return
        if self.phase == "battle_res":
            if self.dummy_t > 1.0:
                self._next_round_or_end()
                self.dummy_t = 0.0
            return

    # ---------- 结算 ----------
    def _write_result(self) -> None:
        result = GameResult(
            session_id=self.session.session_id,
            gold_delta=self.gold - self.initial_gold,
            diamond_delta=self.diamond - self.initial_diamond,
            waves_cleared=self.round_no,
            letters=self.letters_awarded,
            message=f"词汇自走棋：{self.trophies} 奖杯 · {self.wins}胜{self.losses}负 · 最高回合 {self.round_no}",
        )
        result.write(self.session.result_path())


def run_session(session_path: str | Path) -> int:
    p = Path(session_path)
    if not p.exists():
        print(f"会话文件不存在: {p}")
        return 2
    try:
        s = GameSession.read(p)
        game = WordArenaGame(s)
        game.run()
        return 0
    except Exception as e:
        print(f"游戏运行错误: {e}")
        return 1


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python -m games.word_arena <session_in.json>")
        raise SystemExit(2)
    raise SystemExit(run_session(sys.argv[1]))


if __name__ == "__main__":
    main()

# 概率系统设计总览

Adventure 全部核心随机系统的概率设计。开箱系统的详细公式见 [开箱系统概率设计](chest-opening-probabilities.md)。

> 范围:开奖系统(`src/reward_system.py`)、开箱系统(`src/chest_opening.py`)、视觉宝箱条(`src/ui_roll_bar.py`)。音效与小游戏的概率不在此文档。

---

## 1. 随机性总览

| 系统 | 随机来源 | 分布 | 触发 | 意图 |
|------|----------|------|------|------|
| 开奖周期 | `start_new_roll_cycle` | 均匀 6-14 操作 | 每次开奖后 | 节奏不可预测 |
| 开奖概率 | `reshuffle_roll_params` | 截断对数正态 | 每 10 分钟重抽 | 概率动态漂移 |
| 掉落判定 | `maybe_roll` | 伯努利(金币/钻石独立) | 开奖点 | 奖励多样化 |
| 金额 | `maybe_roll` | 截断对数正态 | 命中时 | 多数低值偶发高值 |
| 暴击 | `maybe_roll` | 8% 命中 + 对数正态倍率 | 命中后 | 大奖记忆深 |
| 分段颜色 | `generate_segment_colors` | 均匀色相 | 新周期 | 视觉新鲜 |
| 开箱·字母数 | `generate_open_result` | 几何 p=0.5(0-∞) | 开箱 | 数量右偏 |
| 开箱·字母稀有度 | `generate_open_result` | 加权(5×5 表) | 每字母 | 宝箱越稀有越高档 |
| 开箱·货币 | `generate_open_result` | 伯努利 + 对数正态(0-∞) | 开箱 | 均值分层 + 无限尾 |
| 宝箱条·周期 | `_ease_span_for_cycle` | 确定性算法(540-708s) | 每视觉周期 | 无随机可复现 |
| 宝箱条·检查点 | `_cycle_checkpoints` | 种子化均匀 | 每视觉周期 | 同周期同布局 |
| 宝箱条·稀有度 | `_cycle_chest_rarities` | 种子化加权 | 每视觉周期 | 越靠后越高档 |

---

## 2. 开奖系统(`src/reward_system.py`)

### 2.1 开奖周期:均匀 6-14 操作

```
span = randint(6, 14)     # 每次开奖后重抽
next_roll_at = total_operations + span
```

以**操作数**计(非秒)。节奏不固定,奖励时刻不可预测。

![周期对比](img/roll_span_uniform.svg)

### 2.2 每 10 分钟重抽全部参数

`reshuffle_roll_params()` 每 `SHUFFLE_INTERVAL_SEC = 600` 秒重抽一次,由两个触发器驱动:开奖点检查 + 主窗 QTimer。重抽范围:

| 参数 | 范围 | 分布 |
|------|------|------|
| `gold_chance` | 0.22 - 0.48 | 截断对数正态(σ=0.55) |
| `diamond_chance` | 0.03 - 0.10 | 截断对数正态 |
| `gold_min/max` | 0.08-0.15 / 1.0-2.0 | 均匀 |
| `diamond_min/max` | 0.01-0.03 / 0.12-0.35 | 均匀 |

截断对数正态:中位数落在区间约 25% 分位,多数抽到偏低值,偶发高值。

![开奖概率](img/roll_chance_lognormal.svg)

### 2.3 掉落判定(伯努利,独立)

```
金币: random() < gold_chance
钻石: random() < diamond_chance     # 与金币独立
```

可同时命中、命中其一或全落空。钻石命中后金额下限 0.1(避免显示取整成 0)。

### 2.4 金额:截断对数正态

```
amount = _right_skewed(min, max)    # σ=0.55,中位数在 25% 分位
```

多数靠近下限,偶发靠近上限。

### 2.5 暴击:8% + 对数正态倍率

```
CRIT_CHANCE = 0.08                  # 命中后才判(每货币独立)
mult = _right_skewed(1.2, 20.0, σ=0.95)
```

暴击倍率严重右偏:多数 1.2-3x,极少数接近 20x——"偶发大奖记忆深"。

![暴击倍率](img/crit_mult_lognormal.svg)

---

## 3. 开箱系统(`src/chest_opening.py`)

详见 [开箱系统概率设计](chest-opening-probabilities.md),要点:

- 字母数量:几何分布 p=0.5,均值 2,0-∞ 右偏
- 字母稀有度:5×5 加权表(宝箱越稀有越高档)
- 货币:50%/20% 命中 + 对数正态(均值按稀有度 2→18,0-∞ 无限尾)

![货币对数正态](img/currency_lognormal.svg)

---

## 4. 视觉宝箱条(`src/ui_roll_bar.py`)

**纯视觉周期,与真实开奖完全独立**(不改变 `maybe_roll` 概率)。

### 4.1 周期:确定性算法(非随机)

```
span = 540 + ((cycle_id × 7) % 15) × 12     # 540-708 秒(约 9-12 分钟),步长 12
```

7 与 15 **互质**,所以 15 轮内正好走遍全部 15 种跨度(540, 552, …, 708)。以运行中目标的 `active_seconds + operations//10` 为单位推进。

![缓动条周期跨度](img/ease_span_distribution.svg)

### 4.2 检查点:种子化均匀分布

每个视觉周期一组检查点(到达时发光 + 播钻石音效):

```
p1 ∈ [0.18, 0.32]           # 第一点偏早
p2 ∈ [max(0.52, p1+0.22), 0.78]   # 第二点拉开
p3 = 1.0                    # 终点固定
```

用**种子化 RNG** 抽取,同一 (span, cycle_id) 永远得到相同布局:

```
rng = random.Random(f"ease:{span}:{cycle_id}")
```

重启/回放可复现,不持久化任何 RNG 状态。

![缓动条检查点](img/ease_checkpoints.svg)

### 4.3 三箱稀有度:种子化加权

每个视觉周期的三个宝箱各自独立抽稀有度,**越靠后高档略多**:

| 箱子 | 普通 | 罕见 | 稀有 | 史诗 | 传奇 |
|------|------|------|------|------|------|
| 第 1 箱 | 50% | 28% | 14% | 6% | 2% |
| 第 2 箱 | 35% | 28% | 20% | 12% | 5% |
| 第 3 箱 | 22% | 25% | 25% | 18% | 10% |

```
rng = random.Random(f"chest:{span}:{cycle_id}")    # 三个箱子各自 randrange 抽取
```

![缓动条三箱稀有度](img/ease_rarity_weights.svg)

### 4.4 与真实开奖的独立性

缓动条只决定**视觉呈现**(进度、宝箱稀有度、音效触发),不参与任何奖励数值;真实开奖完全由 `maybe_roll` 决定。视觉周期约 9-12 分钟,真实开奖 6-14 操作,两者刻意解耦。

---

## 5. 持久化与迁移

- 开奖运行参数全部存在 `roll_runtime`(`RollRuntime`),含 `next_roll_at / roll_span / segment_colors / 概率 / 金额范围 / last_shuffle_at`
- `settings` 里的旧字段(`roll_interval / roll_chance / gold_chance …`)仅供**旧存档迁移**:加载时被 `_migrate_roll_runtime` 消费一次,随即被新随机参数替换,不再作为固定概率生效
- 开箱只持久化结果与时间戳(奖励已入账),不存任何 RNG 状态
- 宝箱条状态存 `EaseChestsState`(周期领取防重),RNG 本身靠种子确定性再生

## 6. 测试与确定性

| 模式 | 用途 | 实现 |
|------|------|------|
| 全局 `random.seed()` | 开奖系统测试 | `tests/test_reward_system.py` 设 seed,断言跨度/顺序 |
| `rng: random.Random` 注入 | 开箱系统测试 | `generate_open_result(rarity, rng)` 传 seed,验证分布不变量 |
| 种子化 `random.Random(str)` | 宝箱条测试 | 同周期同布局断言 |

开箱测试覆盖:几何分布右偏(P(1)>P(2)>P(3+))、单箱字母不重复、货币均值≈设定、中位数<均值(右偏)、无限尾值存在(5000 采样 >5× 均值)。

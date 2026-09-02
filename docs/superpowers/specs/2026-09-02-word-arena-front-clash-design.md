# 词汇自走棋：前排对撞（Super Auto Pets 式）

## Goal

把 `games/word_arena.py` 的战斗从「每拍全员出手」改成 Super Auto Pets 式前排对撞：左右当前前排同时互打，两边一起掉血，停约 0.5 秒再倒下或打下一拍。商店、铜币、奖杯、词库、入场费、其它小游戏不变。

## Scope

- **In:** 战斗模拟（谁出手、打谁、何时死亡）、战斗回放（双人冲锋、同时跳血、停顿）、战场槽位绘制（我方镜像）、相关单测。
- **Out:** 商店买卖/升星/食物、铜币与买命、奖杯与生命、词库内容、阵型存档协议、pet/grid 游戏。

## Combat rules

### Front

商店从左到右槽 0→4，**槽 0（最左）是前排**。

开战时：

- 我方整队左右对调再画到左半场：槽 0 出现在我方最右侧（贴中线）。
- 敌方不转：槽 0 出现在敌方最左侧（贴中线）。

格子位置整场固定，空槽保留，倒下后不向中线挤。当前前排 = 从槽 0 起第一个仍存活的单位。若槽 0 为空，贴中线的格子是空的，出手的是下一个存活单位。

### Default clash

双方当前前排同时各打出 **1 次** 攻击（`total_atk`，含当次 cache/python/database/mybatis 等单次修正）。两边都在死亡结算前掉血。一方或双方 hp≤0 时，本拍互打仍完整打完，然后才倒下。

### Snipe

只有技能 key 为 `sql` 或 `mybatis` 的单位（词：sql、search、mybatis）在**打出**伤害时改打敌方当前血最少的存活单位。他们挨的还手仍来自这一拍的互打对象（默认是对方当前前排）。因此 sql 当前排时，可以出现：自己打到对方后排，自己仍被对方前排打。

### Extra clashes are mutual

每一次额外出手都是又一次完整互打：两边都造成伤害，再冲、再跳血、再停 0.5 秒。若这一下已经把互打的任一方打死，该出手方剩下的连击取消。

额外次数沿用现有技能（在第一次互打之后追加）：

| 技能 | 额外互打次数 |
|------|----------------|
| `loop` / `threadpool` | +1 |
| `java` / `alibaba` | +1 |
| `quantum` | 50% +1 |
| `dubbo` / `mq` | 50% +1 |
| `thread` | 25% +1 |

同一单位多条叠加（例如 loop+java → 第一次互打后再互打两次）。先结算我方前排的额外互打，再结算敌方前排的额外互打。每次互打后立刻结算死亡，再决定是否还有下一记。

### queue / pipeline

对撞（含前排连击）之后：

- **pipeline**（技能 `pipeline`）：一次互打结束后，若该次出手单位技能是 pipeline，随机一名**其他**存活队友与对方**当前前排**再互打一次。双方前排都是 pipeline 时各触发一次（先我后敌）。pipeline 触发出来的那一次互打不再次触发 pipeline，避免连锁。
- **queue**（场上存在技能 `queue` 的单位即可）：前排对撞与连击、以及本段 pipeline 都结束后，该侧每个存活单位按槽序，各与对方**当前前排**互打一次（后排冲上去，对方前排还手）。先处理我方 queue，再处理敌方 queue。每次互打后结算死亡；对方前排已死后，后续互打改为对新的当前前排。queue 里出手的 pipeline 单位仍按上条触发一次（同样不连锁）。

sql/mybatis 在 queue/pipeline 里出手时，打出仍点最低血，挨打仍来自对方当前前排。

### Not mutual

这些保持原逻辑，挂在当次互打的结算里，不另开一拍互打：virus 溅 1 点到另一敌人；shell 反弹；router/nginx/proxy 转伤；socket/redis/heap 受击效果；开局技能与死亡召唤。

## Replay

每次互打是一条 `clash` 事件。回放四段：

1. **冲（0.12s）** 两个出手单位同时冲向各自目标。
2. **撞（1 帧）** 本拍所有 hit/block 的血量与飘字同时套上。
3. **停（0.50s）** 停在接触位置，血量已是新值。
4. **收** `clash.after` 里的 faint/spawn/skill：倒下的播残影，活着的退回格子，然后下一条事件。

常量：`CLASH_LUNGE_OUT = 0.12`、`CLASH_HOLD = 0.50`、`CLASH_LUNGE_BACK = 0.18`。

现在的单个 `_lunge` 改成最多两个同时冲锋。冲锋只是绘制偏移，槽位不变。

`SDL_VIDEODRIVER=dummy`：一次 `_update_battle` 走完整段 clash（立刻跳血并处理 after），避免无头测试被 0.5s 卡住。

开局 `start`/`skill`/`spawn` 仍逐条播；`end` 结束战斗。

## Events

```python
{
  "type": "clash",
  "msg": str,
  "lunges": [
    {"side": "p"|"e", "slot": int, "target_side": "p"|"e", "target_slot": int},
    {"side": "p"|"e", "slot": int, "target_side": "p"|"e", "target_slot": int},
  ],
  "hits": [
    {
      "target_side": "p"|"e", "target_slot": int,
      "attacker_side": "p"|"e", "attacker_slot": int,
      "damage": int, "target_hp": int,
    },
  ],
  "blocks": [{"target_side": ..., "target_slot": ..., "msg": str}],
  "after": [  # faint / spawn / skill，停顿之后再播
    {"type": "faint", "side": ..., "slot": ..., "msg": ...},
    ...
  ],
}
```

`lunges` 一定两条（互打双方）。`hits` 可以多于两条（反弹、转伤）。被完全挡住的一侧进 `blocks`，不进 `hits`。

## Layout

`_battle_slot_rect` 的列号：

- 我方：`col = MAX_TEAM - 1 - slot`（槽 0 在右，贴中线）
- 敌方：`col = slot`（槽 0 在左，贴中线）

与今天的实现相反。商店队伍栏仍从左到右槽 0→4，不镜像。战场标签改为双方都是前排靠中线。

## Architecture

战斗模拟仍留在 `WordArenaGame`（`_deal_damage` / `_on_faint` / 开局技能依赖同一份棋盘）。抽出纯函数便于单测：

- `front_index(board) -> Optional[int]`
- `is_snipe(skill) -> bool`
- `extra_clash_count(unit, rng) -> int`
- `battle_draw_col(side, slot) -> int`

`_one_combat_tick` 改为：取双方 `front_index`，做一次互打，再按上面的顺序追加连击 / pipeline / queue。不再让全体存活单位每拍都出手。

`_pick_target`：默认对方 `front_index` 指向的单位；snipe 仍是血最少。

一次互打：拍首锁定两个出手者及其目标，各执行 **一次** `_swing`（现 `_unit_attack` 里单次伤害那一段，不含连击循环），再 `_settle_deaths`，把本拍 hit/block/faint 收进一条 `clash`。

## Testing

`tests/test_game_input.py` 里 `WordArenaSimultaneousBattleTests` 按新规则改，并补：

- 后排在默认对撞中不出手（3v1 时后排 hp 不变，直到前排倒下）。
- 1v1 同攻同血：两条 hit 都在 faint 之前；回放事件是一条 `clash` 含两次 hit。
- mybatis/sql 当前排时第一记打出血最少槽。
- queue：1v1 在首次 clash 之后还有至少一次 clash（互打，两边都有 hit）。
- `battle_draw_col("p", 0) == MAX_TEAM - 1`，`battle_draw_col("e", 0) == 0`。
- sentinel 前两次对撞受击仍为 block。
- dummy 整局仍收敛（事件数上限、10 秒内 `phase == over`）。

随机连击测试里把 `random.random` 钉死，或选用不含随机额外互打的词。

## Error handling

互打任一方在锁定后、出手前已经不存活：跳过这一次 clash。60 次 clash 上限仍在，防止无限互打。回放下标越界或 clash 缺 `lunges`：当作该事件结束，继续下一条，不崩。

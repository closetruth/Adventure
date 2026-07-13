# Adventure

一个能在 Windows 10/11 桌面悬浮显示的「**任务 + 奖励**」小部件。  
敲键盘、点鼠标会累计操作数并周期性「开奖」；奖励先挂在当前任务上，完成任务后再领进背包。附带两个 pygame 小游戏。

---
## 演示



https://github.com/user-attachments/assets/1e629403-fa90-4cbe-847e-aedf050f35ad




## 功能特性

### 任务
- 创建任务（标题 + 备注），可添加多个**子目标**（按时长累计）
- 暂停 / 恢复 / 删除
- 子目标时长达标后手动「完成」并「领取」pending 奖励
- 完成任务并领取该任务剩余待领奖励
- 显示创建时间、完成时间、本任务操作数、**进行中累计时长**（暂停与系统休眠不计）
- 同一时间只能有一个「进行中」任务

### 奖励
- 金币与钻石（浮点数，界面最多显示 1 位小数）
- 全局键鼠监听：每次独立按键按下或鼠标按下计 1 次操作（长按不重复计）
- **内置随机开奖**：每 **6～14 次操作**（每轮随机）触发一次开奖；未命中也会记入开奖历史
- **每 10 分钟**自动重抽中奖概率与奖励数值范围（内置机制，无设置界面）
- 奖励先进入**当前进行中子目标**的待领列表，**点击领取**后才进背包
- 开奖参数运行时保存在 `roll_runtime`；`settings` 中的旧字段仅用于存档迁移

### 悬浮窗
- 置顶、可拖动、系统托盘、右键菜单（置顶 / 固定到所有虚拟桌面 / 开机自启 / 退出）
- **全局统计**（总操作、背包金币/钻石、近 1 分钟操作）以小字显示
- **任务区**突出显示：本任务操作、累计金币/钻石、近 1 分钟操作、自上次开奖以来累计掉落
- **彩色分段进度条**：每格随机颜色，显示 `距下次开奖 x/y` 与当前有效概率
- 开奖瞬间轻量反馈：命中显示 `+金币` / `+钻石` 并闪动进度条；落空显示灰色「未中」
- 最近 3 条开奖历史
- 子目标：按时长累计，完成后手动领取 pending 奖励

### 奖励背包
- 查看金币、钻石、任务统计、**完整开奖历史**（可滚动）
- 启动小游戏并结算回背包

### 小游戏
| 游戏 | 入口 | 入场费 | 说明 |
|------|------|--------|------|
| 小动物竞技场 | 开始游戏 | 10 金币 | 鼠标布阵（5 槽列表）；战斗 5 vs 5 对位，`ESC` 结算 |
| 像素格子战场 | 开始像素格子模式 | 12 金币 | 6×4 布阵对战，`ESC` 结算 |

操作说明见游戏内提示；主程序通过子进程 + JSON 会话文件与游戏通信。

---

## 快速开始（Windows）

> **推荐 Python 3.12 或 3.13。** 若使用 **3.14**，必须用 `pygame-ce`（`requirements.txt` 已指定），不要用官方 `pygame`。

1. 将项目放到任意目录（如 `Desktop\Adventure`）。
2. 双击 **`install.bat`**：创建 `.venv` 并安装依赖。
3. 双击 **`run.bat`** 启动（无控制台窗口）。
4. （可选）小游戏无法启动时，双击 **`fix_game.bat`** 仅重装 `pygame-ce`。
5. 在悬浮窗右键菜单可勾选「开机自启」。

手动启动：

```bat
.venv\Scripts\pythonw.exe run.py
```

---

## 手动安装（开发者）

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

小游戏子进程（调试）：

```bat
python run.py --game pet <session_in.json>
python run.py --game grid <session_in.json>
```

> 非 Windows 无法使用「固定到所有虚拟桌面」；macOS 上 pynput 需授予辅助功能权限。

---

## 打包为 exe

```bat
build.bat
```

需要项目根目录存在 **`Adventure.spec`**（PyInstaller 配置）。产物一般在 `dist\Adventure\Adventure.exe`。

---

## 使用说明

| 操作 | 说明 |
|------|------|
| 左键拖动 | 移动悬浮窗 |
| 右键 | 置顶 / 全桌面 / 开机自启 / 退出 |
| 任务管理 | 创建、暂停、恢复、完成、删除任务 |
| 奖励背包 | 资产、统计、开奖历史、进入小游戏 |
| 托盘单击 | 重新显示悬浮窗 |

---

## 数据存储

路径：

```
%APPDATA%\Adventure\data.json
```

小游戏会话（临时）：

```
%APPDATA%\Adventure\game_sessions\
```

主要字段：

| 字段 | 含义 |
|------|------|
| `inventory` | 已领取的金币、钻石 |
| `tasks[]` | 任务列表、子目标、`pending_rewards`、完成后 `completed_reward_*` |
| `total_operations` | 全局操作总数 |
| `last_roll_at` | 上次开奖时的操作数 |
| `since_roll` | 自上次开奖以来掉落到当前子目标的累计奖励 |
| `roll_history[]` | 开奖历史（最多约 100 条） |
| `roll_runtime` | 当前开奖周期：下次阈值、分段颜色、有效概率与奖励范围 |
| `settings` | 窗口行为、子目标默认值、`pet_best_round` 等 |

`roll_runtime` 示例（由程序自动维护，一般无需手改）：

```json
{
  "next_roll_at": 128,
  "roll_span": 11,
  "segment_colors": ["#a3c2f1", "#e8b44d", "..."],
  "roll_chance": 0.312,
  "diamond_chance": 0.09,
  "gold_min": 0.11,
  "gold_max": 0.95,
  "diamond_min": 0.02,
  "diamond_max": 0.12,
  "last_shuffle_at": 1710000000.0
}
```

`settings` 中仍保留 `roll_interval`、`roll_chance` 等字段，供**旧存档迁移**时使用；实际开奖以 `roll_runtime` 为准。内置随机范围见 `src/reward_system.py` 顶部常量。

程序约每 15 秒自动保存；退出时也会保存。损坏的 `data.json` 会尝试从 `.bak*` / `.anchor` / `.snap.*` 恢复，并备份为 `data.broken.*.json`。

---

## 项目结构

```
Adventure/
├── run.py                 # 主程序 / --game 子进程入口
├── run.bat                # 一键启动
├── install.bat            # 一键安装 venv + 依赖
├── fix_game.bat           # 仅修复 pygame-ce
├── build.bat              # PyInstaller 打包
├── requirements.txt
├── games/
│   ├── pet_arena.py       # 小动物竞技场
│   └── pixel_tactics.py   # 像素格子战场
└── src/
    ├── main.py            # Qt 应用、托盘、操作事件管线
    ├── widget.py          # 悬浮窗（彩色开奖进度条、中奖反馈）
    ├── ui_roll_bar.py     # 彩色分段开奖进度条
    ├── task_dialog.py     # 任务管理
    ├── inventory_dialog.py# 背包与开奖历史
    ├── ui_task_stats.py   # 任务统计条组件
    ├── ui_text.py         # 金额与历史文案格式化
    ├── task_manager.py    # 任务 CRUD
    ├── reward_system.py   # 内置随机开奖、10 分钟重抽参数
    ├── input_monitor.py   # pynput 全局监听
    ├── op_tracker.py      # 近 1 分钟操作计数（仅内存）
    ├── models.py          # 数据模型
    ├── storage.py         # JSON 持久化
    ├── game_launcher.py   # 启动游戏子进程
    ├── game_protocol.py   # 主程序 ↔ 游戏 JSON 协议
    └── win_utils.py         # 置顶、虚拟桌面、开机自启
```

可选脚本：`install.ps1`（与 `install.bat` 类似）。`run_game.bat` 仅作提示，正常从背包进入游戏即可。

---

## 性能说明

- 平时只开悬浮窗时负载很低；全局监听在独立线程，UI 在主线程更新。
- 若**开着「任务管理」窗口**同时快速打字，会因频繁重建任务卡片而略顿，关掉即可。
- 小游戏在**独立子进程**中运行，不拖慢主窗口。

---

## 隐私

- 只统计操作次数，**不记录**按键内容、鼠标坐标或前台应用名。
- 数据仅保存在本机 `%APPDATA%\Adventure\`，不上传。

---

## 许可

见 [LICENSE](LICENSE)。

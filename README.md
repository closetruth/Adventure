# Adventure

一个能在 Windows 10 桌面悬浮显示的「**任务 + 奖励**」小部件。
做完任务领奖励，敲键盘/点鼠标随机掉落金币与钻石，让普通的工作时光变成一场冒险 ✨

![preview](docs/preview-placeholder.png)

---

## 功能特性

### Todo 列表
- ✅ 创建任务（标题 + 备注）
- ⏸ 暂停 / ▶ 恢复任务
- 🗑 删除任务
- 🎉 完成任务并领取累计奖励
- 显示任务创建时间 / 完成时间
- 显示该任务进行期间累计的「操作数」

### 奖励系统
- 奖励分为 🪙 金币 与 💎 钻石
- 自动监听全局键盘 / 鼠标点击，每次操作累计计数
- 每 `N` 次操作（默认 10 次）触发一次「开奖」
- 命中概率与金币/钻石区间均可在 `data.json → settings` 自定义
- 奖励先暂存在「当前进行中」的任务里，**任务完成后**才能领入背包
- 一次只能有一个「进行中」任务，新建/恢复其它任务会自动暂停当前任务

### 小部件 (悬浮窗)
- 常驻桌面，始终置顶
- **Win10/Win11 自动固定到所有虚拟桌面**（依赖 `pyvda`）
- 显示操作数、距下次开奖的进度条
- 显示当前持有的金币 / 钻石
- 显示进行中的任务标题 + 待领取奖励
- 支持拖动移动、最小化、右键菜单（置顶 / 全桌面 / 开机自启 / 退出）
- 同时驻留系统托盘，关闭悬浮窗后可从托盘再次唤出

### 小游戏：小动物竞技场（pygame）
- 在「奖励背包」点击 **开始游戏** 进入
- 入场费 **10 金币**；用金币招募小猫/小狗/小熊（按键 1/2/3）
- 空格开始波次战斗，自动攻击；通关获得金币，每 5 波额外 **1 钻石**
- **ESC** 退出并结算到背包

---

## 一键安装到 Windows 10（推荐路径）

> 推荐 **Python 3.12 或 3.13**。若使用 **Python 3.14**，小游戏依赖 `pygame-ce`（不要用官方 `pygame`，会编译失败）。

1. 把整个项目目录复制到本机任意位置（例如 `C:\Users\<你>\Desktop\Adventure`）。
2. 双击 `install.bat`：创建 `.venv` 并安装依赖（含 `pygame-ce`）。
3. 若只修复游戏依赖：双击 `fix_game.bat`。
3. 双击 `run.bat` 即可启动 Adventure。
4. 在悬浮窗右键菜单中勾选「开机自启」，开机后即可自动随系统启动。

如需打包成独立的 `.exe`（无需用户装 Python），执行：

```bat
build.bat
```

打包产物位于 `dist\Adventure\Adventure.exe`，可直接双击运行，也能拷贝到任意 Win10 机器上使用。

---

## 手动安装（开发者 / 跨平台）

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

> ⚠️ 非 Windows 平台无法使用「固定到所有虚拟桌面」功能；其余 Todo / 奖励 / 监听仍可工作（依赖 pynput 的全局监听在 macOS 上需要授予「辅助功能」权限）。

---

## 使用指南

| 入口 | 说明 |
| --- | --- |
| 悬浮窗 - 拖动 | 左键按住任意位置拖动小部件移动 |
| 悬浮窗 - 右键 | 弹出菜单：置顶 / 全桌面固定 / 开机自启 / 退出 |
| 悬浮窗 - 任务管理 | 打开任务面板：创建 / 暂停 / 恢复 / 完成 / 删除 |
| 悬浮窗 - 奖励背包 | 查看金币、钻石及统计 |
| 系统托盘 - 单击 | 重新显示悬浮窗 |
| 系统托盘 - 右键 | 与悬浮窗右键菜单基本一致 |

数据自动保存到：

```
%APPDATA%\Adventure\data.json
```

可手动备份 / 调整其中的 `settings` 字段：

```json
{
  "roll_interval": 10,
  "roll_chance": 0.35,
  "gold_min": 1,
  "gold_max": 10,
  "diamond_chance": 0.08
}
```

---

## 项目结构

```
Adventure/
├── README.md
├── requirements.txt
├── install.bat            # Win10 一键安装：创建 venv + 装依赖
├── run.bat                # Win10 一键启动 (pythonw, 无黑框)
├── build.bat              # PyInstaller 打包为 .exe
├── run.py                 # 跨平台开发入口
├── games/
│   └── pet_arena.py       # pygame 小动物竞技场
└── src/
    ├── __init__.py
    ├── main.py            # Qt 应用入口、信号桥接
    ├── widget.py          # 悬浮主小部件
    ├── task_dialog.py     # 任务管理对话框
    ├── inventory_dialog.py# 奖励背包对话框
    ├── task_manager.py    # 任务 CRUD 与状态机
    ├── reward_system.py   # 开奖逻辑
    ├── input_monitor.py   # pynput 全局键鼠监听
    ├── storage.py         # JSON 持久化 (原子写入)
    ├── models.py          # 数据模型 (dataclass)
    ├── game_launcher.py   # 启动小游戏子进程并结算
    ├── game_protocol.py   # 主程序与小游戏 JSON 通信
    └── win_utils.py       # Windows 专属：固定虚拟桌面 / 开机启动
```

---

## 隐私说明
- 全局监听仅统计**按键 / 点击次数**，不记录任何按键内容、坐标、应用名或上下文。
- 所有数据存储在本地 `%APPDATA%\Adventure\` 下，不上传任何远端。

# AimLoot 品牌重命名

## Goal

将产品从 **Adventure** 统一重命名为 **AimLoot**（中文副标题：**目标奖励管理工具**）。用户可见文案、存档目录、开机启动注册表键、构建产物与文档/GitHub 链接一并更新；已有用户从旧 `%APPDATA%\Adventure`（或 `~/.adventure`）自动迁移到新目录，不丢存档。

## Scope

- **In:**
  - 品牌常量（英文名、中文副标题、托盘/对话框文案模板）
  - UI / 托盘 / 消息框 / 小游戏窗口标题
  - `get_data_dir()` 新路径 + 旧目录一次性迁移
  - `sfx` 等硬编码 `Adventure` 路径改为走 `get_data_dir()`
  - 开机启动注册表键 `Adventure` → `AimLoot`（清理旧键）
  - `Adventure.spec` → `AimLoot.spec`，bat 脚本与 README / RELEASE_NOTES 中的产品名、exe、zip、仓库链接
  - 迁移逻辑的单元测试；改完后跑完整 unittest
- **Out:**
  - 实际在 GitHub 上把远程仓库改名（文档先写 `closetruth/AimLoot`；仓库改名由维护者在 GitHub 完成）
  - 重写无关历史设计/计划文档全文（仅路径提及可轻量更新）
  - 删除旧 `%APPDATA%\Adventure` 目录（迁移后**保留**旧目录作为备份）
  - 改文件夹外的 Windows 用户名路径、或已发布的旧 release 资产

## Approach

采用「品牌常量 + 启动时迁移」：

1. 集中定义 `APP_NAME = "AimLoot"`、`APP_NAME_ZH = "目标奖励管理工具"`（及托盘提示等派生字符串），UI/启动/文档引用常量或等价文案。
2. `get_data_dir()` 指向新目录；在首次解析数据目录时按规则迁移。
3. 全局替换剩余产品名字符串；构建与发布文案同步。

不采用长期双目录读写，也不做无封装的纯字符串替换。

## Branding and UI

| 位置 | 文案 |
|------|------|
| 应用名 / 悬浮窗标题 / QLabel 标题 | `AimLoot` |
| 托盘 tooltip | `AimLoot - 目标奖励管理工具` |
| 对话框标题 | 如 `目标管理 - AimLoot`、`奖励背包 - AimLoot` |
| 退出菜单 | `退出 AimLoot` |
| 消息框 / 单实例提示标题 | `AimLoot` |
| 小游戏窗口 caption | `AimLoot - …`（原 Adventure 前缀替换） |
| README / Release 说明 | 产品名 AimLoot；中文介绍带「目标奖励管理工具」 |

主标题保持英文 **AimLoot**；中文作为副标题出现在托盘与文档，不抢主标题。

## Data directory and migration

**新路径**

- Windows：`%APPDATA%\AimLoot`
- 非 Windows：`~/.aimloot`

**旧路径（仅作迁移源）**

- Windows：`%APPDATA%\Adventure`
- 非 Windows：`~/.adventure`

**规则（在创建新目录供使用前」执行一次逻辑判断）**

1. 新目录已有有效 `data.json` → 不迁，直接使用新目录。
2. 新目录空或无有效存档，且旧目录存在数据 → **复制**旧目录内容到新目录（至少包括 `data.json`、备份文件、`runtime_intervals.json`、`game_sessions`、`sfx_cache` 及目录内其它既有文件）。使用复制而非 move，以便失败可回退。
3. 迁移成功后**不删除**旧目录（保留作备份）。
4. 两边都没有有效存档 → 创建并使用空白新目录。

`sfx.py` 等不得再硬编码 `Adventure`；统一通过 `get_data_dir()`（或其子目录）解析。

单实例锁文件仍位于 `get_data_dir() / "instance.lock"`（须在迁移逻辑完成后再创建/占用锁，避免锁落在旧路径）。

## Startup registry

`win_utils` 开机启动 Run 键名：`Adventure` → `AimLoot`。

- 启用：写入 `AimLoot` 键；若存在旧 `Adventure` 键则删除。
- 禁用：删除 `AimLoot` 键；并尝试删除遗留的 `Adventure` 键。

## Build and docs

- `Adventure.spec` 重命名为 `AimLoot.spec`；`EXE`/`COLLECT` 的 `name='AimLoot'`。
- `build.bat`、`install.bat`、`run.bat`、`fix_game.bat`、`run_game.bat` 等用户可见脚本说明改为 AimLoot；`build.bat` 调用 `AimLoot.spec`，产物路径 `dist\AimLoot\AimLoot.exe`。
- `README.md`、`RELEASE_NOTES.md`、`docs/README.md`、`CLAUDE.md`/`AGENTS.md` 中产品名、路径、`closetruth/Adventure` → `closetruth/AimLoot`、`Adventure-vX.Y.Z.zip` → `AimLoot-vX.Y.Z.zip`。
- 历史 `docs/superpowers/` 文档中的 `%APPDATA%\Adventure` 可改为 AimLoot 或注明已迁移；不强制重写计划全文。

## Testing

- 单元测试覆盖迁移三分支：新目录已有数据；新空 + 旧有数据；两边皆空。
- 可选：注册表键名常量可测（或纯函数抽离后测）。
- 完成后运行：`.venv\Scripts\python.exe -m unittest discover -s tests -v`。

## Error handling

- 迁移复制失败：记日志；**本会话仍使用旧目录读写**，并向用户弹出警告（说明迁移未完成、数据仍在旧路径）；下次启动再尝试迁到新目录。禁止静默丢档或写入不完整的新目录后当作成功。
- 不在迁移过程中删除旧目录任何文件。
- 若复制部分完成但校验失败（例如新目录缺少可读的 `data.json`）：清理本次不完整的新目录内容（或忽略该残缺新目录），回退旧目录；不得把残缺新目录当成「已有有效存档」。

## Out of band (maintainer)

- 在 GitHub 上将仓库从 `Adventure` 重命名为 `AimLoot`，使 README 新链接生效。
- 下一版 release 资产文件名使用 `AimLoot-vX.Y.Z.zip`。

# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-10-16

首个发布版本。

### 新增

- `gefjon init`：生成 `migrations/`（`alembic.ini`、`env.py`、`script.py.mako`）与示例 `models.yaml`
- `gefjon generate`：按 `models.yaml` 生成 SQLAlchemy 模型包（`base.py`、`__init__.py`、各模型文件，支持 `module:` 子目录）
- `gefjon migrate` / `upgrade` / `downgrade` / `history`：迁移脚本生成与执行（`migrate` 默认只生成、不执行）
- `gefjon status`：项目版本、数据库 revision、待应用的迁移、版本映射
- `gefjon shell`：预加载配置与模型包的交互式 shell
- `gefjon version`
- 迁移前自动备份：迁移脚本目录 + 当前 revision，落到 `.gefjon/backups/`
- 版本映射缓存：`.gefjon/version_map.json`
- **类型**：通用 20 项、PostgreSQL 47 项、MySQL 34 项；含数组、枚举、范围与多重范围、`DOMAIN`、以及几何/空间与 `XML`（按需生成 `_gefjon_types.py`）
- **索引**：`using`、`ops`、`where`（部分索引）、`expressions`（表达式索引）、`concurrently`、`prefix`/`lengths`（MySQL 全文与前缀索引）
- **表**：`unlogged: true`（PostgreSQL UNLOGGED）
- **关系**：`relationships` 声明 ORM `relationship`（`target` / `back_populates` / `cascade` / `lazy` / `uselist` / `secondary`），双向关系交叉校验
- **`gefjon generate --check`**：只读的漂移检测，模型包与 `models.yaml` 不一致时以非零退出码结束（适合放进 CI）
- **`gefjon migrate --dry-run`**：只预览将要应用的 schema 变更，不生成脚本、不执行
- 生成输出是**确定性**的（生成文件不含时间戳），因此 `--check` 与 git diff 都只反映真实变化

### 安全

- 日志中的数据库连接串始终遮盖密码；`data/install.lock` 使用 scrypt 派生密钥并按 fail-closed 解析（解密失败即报错，不静默回退到其它连接串）
- 代码生成只接受白名单类型与受限语法（字段默认值、`index.where`、`expressions`），解析后重新拼装，用户输入不会以原始形式进入生成的代码或 SQL
- 生成过程先渲染后落盘、原子写；模板缺失或渲染失败直接报错，不会把已有模型文件清空

### 已知限制

见 README 的「已知限制与 Roadmap」：空间运算能力需 geoalchemy2、`DOMAIN` 的 `CHECK`/`DEFAULT` 未支持、表分区与索引排序方向未支持。

[0.1.0]: https://github.com/Athenavi/Gefjon/releases/tag/v0.1.0

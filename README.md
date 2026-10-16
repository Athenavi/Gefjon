# ⚡ Gefjon

> 基于 YAML 配置生成 SQLAlchemy ORM 模型，并用 Alembic 完成数据库迁移 —— 让数据库版本管理像预言一样清晰。

---

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 📖 目录

- [简介](#简介)
- [核心特性](#核心特性)
- [为什么叫 Gefjon？](#为什么叫-gefjon)
- [安装](#安装)
- [快速开始](#快速开始)
- [models.yaml 配置说明](#modelsyaml-配置说明)
- [CLI 命令](#cli-命令)
- [数据库连接串的来源](#数据库连接串的来源)
- [项目结构](#项目结构)
- [已知限制与 Roadmap](#已知限制与-roadmap)
- [开发](#开发)
- [许可证](#许可证)

---

## 简介

**Gefjon** 是一个数据库版本管理工具。你只维护一份 `models.yaml`，它负责：

- 生成 SQLAlchemy ORM 模型代码；
- 基于 Alembic 生成并执行迁移脚本；
- 维护**项目版本 ↔ 数据库 revision** 的映射关系。

`models.yaml` 是唯一事实来源：模型定义、数据库连接、迁移目录、第三方项目映射都写在这里。

---

## 核心特性

- 🚀 **配置驱动**：用 YAML 声明数据模型，不手写重复的 ORM 代码
- 🔄 **自动迁移**：集成 Alembic，`generate` 之后 `migrate` 即可生成迁移脚本
- 📋 **版本映射**：记录项目版本与数据库 revision 的对应关系，写入 `.gefjon/version_map.json`
- 🛡️ **迁移前备份**：每次迁移前自动备份迁移脚本目录并记录当前 revision
- 🔒 **安全的凭据处理**：日志中的连接串始终遮盖密码；`install.lock` 使用 scrypt 派生密钥
- 🧱 **安全的代码生成**：字段名、类型、默认值全部经过白名单校验，生成前不落盘、写入是原子的

---

## 为什么叫 Gefjon？

在北欧神话中，**Gefjon** 是一位预言与命运的女神。这座工具也是如此 —— 你用 `models.yaml` 预言数据库的未来形态，Gefjon 精准地把它变成现实。

---

## 安装

```bash
pip install gefjon
```

从源码安装：

```bash
git clone https://github.com/yourusername/gefjon.git
cd gefjon
pip install -e ".[dev]"
```

**环境要求**：Python **3.10+**（使用了 `X | None` 类型语法），SQLAlchemy **2.0+**（`Uuid` 等类型需要 2.0），Alembic 1.7+。

---

## 快速开始

```bash
# 1. 初始化项目结构（生成 migrations/、alembic.ini、示例 models.yaml）
gefjon init

# 2. 按 models.yaml 生成 ORM 模型
gefjon generate

# 3. 生成迁移脚本（默认只生成，不执行）
gefjon migrate --message "create user and post tables"

# 4. 应用迁移
gefjon upgrade

# 5. 查看状态
gefjon status
```

`gefjon status` 输出示例：

```
项目版本：1.0.0
数据库：postgresql://app:***@localhost:5432/mydb
当前 DB revision：def456
最新 revision：def456
待应用的迁移：无
版本映射缓存： project_version=1.0.0 db_revision=def456 updated_at=2026-08-27T10:30:00+00:00
```

---

## models.yaml 配置说明

```yaml
project:
  name: myproject
  version: 1.0.0          # 也可写在顶层 `version:`

database:
  url: "postgresql://user:password@localhost:5432/mydb"
  dialect: postgresql      # postgresql / mysql / sqlite
  pool_size: 10
  echo: false

models:
  - name: User             # Python 类名，必须是合法标识符
    table: users
    description: 用户
    module: ""             # 可选：输出到模型包的子目录，如 auth -> models/auth/user.py
    fields:
      - name: id
        type: Integer
        primary_key: true
      - name: username
        type: String(50)
        nullable: false
        unique: true
      - name: email
        type: String(100)
        nullable: false
      - name: created_at
        type: DateTime
        default: "func.now()"
      - name: user_id
        type: Integer
        foreign_key: users.id
    indexes:
      - columns: [email]
        unique: true
    unique_constraints:
      - name: uq_users_email_username
        columns: [email, username]

migration:
  directory: ./migrations
  template: ./templates/alembic.ini.j2   # 可选

mapping:
  third_party:
    - project: auth-service
      version: v2.1.0
      db_revision: abc123
```

### 模型选项

| 选项 | 说明 |
| :--- | :--- |
| `name` | Python 类名（必须合法标识符） |
| `table` | 表名；省略时由类名推断（`User` → `users`） |
| `description` | 模型说明，写入类 docstring |
| `module` | 输出子目录，如 `auth` → `models/auth/user.py` |
| `unlogged` | PostgreSQL：生成 UNLOGGED 表（建表后执行 `ALTER TABLE ... SET UNLOGGED`） |

### 字段选项

| 选项 | 说明 |
| :--- | :--- |
| `name` | Python 属性名（必须合法标识符）；与 SQLAlchemy 保留名冲突时自动写成 `extra_<name>`，列名保持原样 |
| `type` | 列类型，见下方[类型](#类型) |
| `column` | 显式指定数据库列名 |
| `maxLength` | 无参数 `String` 的长度，默认 255 |
| `values` | `Enum` / `Set`（含 `mysql.SET`、`pg.ENUM`）的取值列表，如 `values: [draft, published]` |
| `item_type` | `ARRAY` 的元素类型、`DOMAIN` 的基类型，如 `item_type: Text` |
| `timezone` | `TIMESTAMP` / `TIME` 是否带时区，如 `timezone: true` |
| `domain_name` | PostgreSQL `DOMAIN` 的名字，如 `domain_name: us_postal_code` |
| `not_null` | PostgreSQL `DOMAIN` 的 `NOT NULL` 约束 |
| `nullable` | **默认 `false`（NOT NULL）**；生成的代码里始终显式写出 `nullable=`，不存在“静默失效” |
| `primary_key` | 主键；整数主键默认 `autoincrement=true` |
| `autoincrement` | 显式覆盖自增行为 |
| `unique` / `index` | 对**所有**类型都生效 |
| `default` | 见下方“默认值” |
| `description` / `doc` | 生成到 `Column(doc=...)` |
| `foreign_key` | 形如 `表名.列名` |

### 类型

类型名不区分大小写，只接受下表登记的类型；不在表内的类型**会直接报错**，不会写进生成的代码。

**通用类型**（`sqlalchemy`，跨方言可用）

| 类型 | 说明 |
| :--- | :--- |
| `Integer` / `SmallInteger` / `BigInteger` | 整数（别名 `int` / `integer` / `smallint` / `bigint`） |
| `String(n)` | 变长字符串，`n` 省略时取 `maxLength`（默认 255）；别名 `varchar` / `char` |
| `Text` | 长文本 |
| `Unicode` / `UnicodeText` | Unicode 字符串 |
| `Boolean` | 布尔（别名 `bool`） |
| `Date` / `Time(p)` / `DateTime(p)` / `Interval(p)` | 日期时间；`Time` / `DateTime` 支持 `timezone: true` |
| `Float` / `Numeric(p, s)` | 浮点 / 定点（别名 `float` / `real` / `double` / `decimal`） |
| `JSON` | JSON |
| `LargeBinary(n)` | 二进制（别名 `binary` / `blob`） |
| `Enum` | 枚举，需要 `values:` |
| `Uuid` | UUID（别名 `uuid`） |
| `ARRAY` | 数组，需要 `item_type:`；在 PostgreSQL 上渲染为 `TEXT[]` 这类原生数组 |
| `PickleType` | pickle 序列化 |

**PostgreSQL 专有类型**（可用 `pg.` 前缀显式指定）

| 分类 | 类型 |
| :--- | :--- |
| 数值 / 货币 | `SMALLINT` `INTEGER` `BIGINT` `REAL` `FLOAT` `DOUBLE_PRECISION` `NUMERIC(p,s)` `MONEY` |
| 字符 / 二进制 | `CHAR(n)` `VARCHAR(n)` `TEXT` `CITEXT` `BYTEA` |
| 日期时间 | `TIMESTAMP` `TIME` `DATE` `INTERVAL`（`TIMESTAMP` / `TIME` 支持 `timezone: true`） |
| 布尔 / 位串 | `BOOLEAN`、`BIT(n)`、`varbit(n)`（渲染为 `BIT(n, varying=True)`） |
| 网络地址 | `CIDR` `INET` `MACADDR` `MACADDR8` |
| UUID / JSON 系 | `UUID` `JSON` `JSONB` `JSONPATH` `HSTORE` |
| 全文检索 | `TSVECTOR` `TSQUERY` |
| 范围 | `INT4RANGE` `INT8RANGE` `NUMRANGE` `DATERANGE` `TSRANGE` `TSTZRANGE` |
| 多重范围 | `INT4MULTIRANGE` `INT8MULTIRANGE` `NUMMULTIRANGE` `DATEMULTIRANGE` `TSMULTIRANGE` `TSTZMULTIRANGE` |
| 对象标识 | `OID` `REGCLASS` `REGCONFIG` |
| 数组 / 枚举 | `ARRAY`（需 `item_type:`）、`ENUM`（需 `values:`） |
| 域 | `DOMAIN`（需 `domain_name:` 与 `item_type:`，可选 `not_null:`） |
| 几何 / XML | `POINT` `LINE` `LSEG` `BOX` `PATH` `POLYGON` `CIRCLE` `XML`（见下方说明） |

**MySQL 专有类型**（可用 `mysql.` 前缀显式指定）

| 分类 | 类型 |
| :--- | :--- |
| 数值 | `TINYINT(n)` `SMALLINT(n)` `MEDIUMINT(n)` `INTEGER(n)` `BIGINT(n)` `DECIMAL(p,s)` `NUMERIC(p,s)` `FLOAT(p,s)` `DOUBLE(p,s)` `REAL(p,s)` `BIT(n)` `BOOLEAN` |
| 日期时间 | `YEAR` `DATE` `TIME(p)` `DATETIME(p)` `TIMESTAMP(p)` |
| 字符串 | `CHAR(n)` `VARCHAR(n)` `NCHAR(n)` `NVARCHAR(n)` `TINYTEXT` `TEXT` `MEDIUMTEXT` `LONGTEXT` |
| 二进制 | `BINARY(n)` `VARBINARY(n)` `TINYBLOB` `BLOB` `MEDIUMBLOB` `LONGBLOB` |
| 枚举 / 集合 | `ENUM`（需 `values:`）、`SET`（需 `values:`） |
| JSON / 网络 | `JSON` `INET4` `INET6` |
| 空间 | `GEOMETRY` `POINT` `LINESTRING` `POLYGON` `MULTIPOINT` `MULTILINESTRING` `MULTIPOLYGON` `GEOMETRYCOLLECTION`（见下方说明） |

**同名类型如何解析？** 通用类型优先 —— `TEXT`、`JSON`、`timestamp`、`UUID` 都落到通用类型。
`BIT` 在 PostgreSQL 与 MySQL 里都存在、且通用类型没有对应物，因此必须写成 `pg.BIT` / `mysql.BIT`，
或者在 `models.yaml` 里声明 `database.dialect` 让解析器按方言挑。

> **几何 / 空间与 XML 类型**：SQLAlchemy 不内置这些类型，Gefjon 会按需生成一个
> `_gefjon_types.py` 辅助模块（`UserDefinedType` 子类，只负责渲染类型名）。
> 它保证列类型与 DDL 正确；但 `geography` 运算、空间索引等能力需要
> [geoalchemy2](https://geoalchemy-2.readthedocs.io/)。

示例：

```yaml
database:
  dialect: postgresql

models:
  - name: Article
    table: articles
    fields:
      - name: id
        type: Integer
        primary_key: true
      - name: payload
        type: JSONB
      - name: tags
        type: pg.ARRAY
        item_type: Text
      - name: state
        type: Enum
        values: [draft, published, archived]
      - name: address
        type: INET
```

### 索引选项

`indexes` 的每一项除 `columns` / `unique` / `name` 外，还支持方言专用选项：

| 选项 | 方言 | 说明 |
| :--- | :--- | :--- |
| `using` | PostgreSQL | 索引方法：`btree`（默认）/ `hash` / `gist` / `gin` / `brin` / `spgist` |
| `ops` | PostgreSQL | 操作符类，如 `ops: {payload: jsonb_path_ops}` |
| `where` | PostgreSQL | 部分索引条件，支持 `列 IS [NOT] NULL` 与 `列 比较符 字面量`，用 `AND` / `OR` 连接 |
| `expressions` | 通用 | 表达式（函数）索引，如 `expressions: ["lower(email)"]`；只允许 `列名` 或 `白名单函数(列名)` |
| `concurrently` | PostgreSQL | `CREATE INDEX CONCURRENTLY` |
| `prefix` | MySQL | `fulltext`（全文索引）或 `spatial` |
| `lengths` | MySQL | 前缀索引长度，如 `lengths: {url: 191}` |

```yaml
indexes:
  - columns: [email]
    unique: true
  - columns: [payload]              # PostgreSQL：GIN + 操作符类
    using: gin
    ops: {payload: jsonb_path_ops}
  - columns: [deleted_at]           # PostgreSQL：部分索引
    where: "deleted_at IS NULL"
  - columns: [body]                 # MySQL：全文索引
    prefix: fulltext
  - columns: [url]                  # MySQL：前缀索引
    lengths: {url: 191}
  - expressions: ["lower(email)"]   # 表达式索引
    unique: true
    concurrently: true              # PostgreSQL：并发建索引
```

`where` 与 `expressions` 都只接受上述受限语法（解析后按结构化结果重新拼装 SQL），
出现 `;`、`--`、`(` 等一律拒绝 —— 因此 `models.yaml` 里的条件无法注入任意 SQL。

### 默认值

只有白名单内的表达式会被当作表达式，其余字符串按**字符串字面量**处理：

| 写法 | 结果 |
| :--- | :--- |
| `default: "func.now()"` | SQLAlchemy 函数表达式（`now`/`current_timestamp`/`current_date`/`random` 等） |
| `default: "datetime.utcnow"` | `datetime.utcnow` |
| `default: "uuid.uuid4"` | `uuid.uuid4` |
| `default: 0` / `default: false` | 数字 / 布尔字面量 |
| `default: "pending"` | 字符串字面量 `'pending'` |

看起来像表达式但不在白名单内（例如 `"os.system(...)"`）**会直接报错** —— 既不会被执行，也不会被静默当成字符串。

---

## CLI 命令

| 命令 | 说明 |
| :--- | :--- |
| `gefjon init` | 初始化项目结构（`migrations/`、`alembic.ini`、`env.py`、示例 `models.yaml`） |
| `gefjon generate` | 按 `models.yaml` 生成 ORM 模型代码 |
| `gefjon migrate` | 生成新的迁移脚本（默认**只生成不执行**） |
| `gefjon upgrade` | 应用迁移到指定 revision（默认 `head`） |
| `gefjon downgrade` | 回滚到指定 revision（默认 `base`） |
| `gefjon history` | 显示迁移历史 |
| `gefjon status` | 显示项目版本、数据库 revision、待应用的迁移与版本映射 |
| `gefjon shell` | 启动预加载配置与模型包的交互式 shell |
| `gefjon version` | 显示版本号 |

常用选项：

```bash
gefjon generate --output ./models --model User --model Post   # 只生成指定模型
gefjon generate --no-backup                                   # 不备份旧输出
gefjon migrate --message "add index" --no-autogenerate        # 生成空脚本手工编写
gefjon migrate --message "add index" --apply                  # 生成后立即应用
gefjon upgrade 123abc                                         # 升级到指定 revision
gefjon init --directory db/migrations --output app/models
gefjon shell --ipython
```

---

## 数据库连接串的来源

`migrations/env.py` 按下面的顺序解析连接串，**fail-closed**：

1. `DATABASE_DSN` 环境变量；
2. `data/install.lock` —— AES-256-GCM 密文，密钥用 **scrypt** 从 `APP_SECRET` 派生（每个文件独立随机 salt）。**只要该文件存在却无法解密就直接报错**，不会静默换用其它连接串；
3. `alembic.ini` 的 `sqlalchemy.url`（`gefjon init` 会写入 `models.yaml` 里的 `database.url`）。

日志中出现的连接串一律经过遮盖（`postgresql://app:***@host/db`），并且不会因为密码里含有 `@`、`#` 这类字符而泄漏片段。

> 注意：`install.lock` 保护的是“连接串不被明文落盘”，不是数据库本身。请配合 `chmod 600` 与密钥管理使用。

---

## 项目结构

使用 Gefjon 的项目：

```
my-project/
├── models.yaml              # 唯一配置入口
├── models/                  # 由 gefjon generate 生成
│   ├── __init__.py
│   ├── base.py
│   ├── user.py
│   └── post.py
├── migrations/              # 由 gefjon init 生成
│   ├── alembic.ini
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
└── .gefjon/                 # Gefjon 内部状态
    ├── version_map.json     # 项目版本 ↔ DB revision
    └── backups/             # 迁移前的脚本备份
```

生成目录里的文件都带“请勿手动修改”标记；`models/` 与 `migrations/versions/` 建议纳入版本控制。

---

## 已知限制与 Roadmap

当前版本（0.1）已实现上面的全部命令。尚未实现、不做承诺的能力：

- **空间运算能力**：几何/空间类型只做类型名渲染（生成 `_gefjon_types.py`），空间索引、距离查询等需要 geoalchemy2；
- **`DOMAIN` 的约束**：`CHECK` 与 `DEFAULT` 尚未支持（两者都会引入新的 SQL 注入面，需要额外的受限解析）；
- **其它 DDL 细节**：表分区（`postgresql_partition_by`）、索引排序方向（`ASC`/`DESC`）、`ALTER` 类运维语句不在生成范围内；
- **Django ORM / FastAPI 路由**等其它框架的代码生成（早期原型中存在过相关代码，已删除，未纳入本版本）；
- `models/` 的**增量生成**：`generate` 每次重写整个模型包（写入前会备份）；
- 数据库**数据**的物理备份：迁移前备份的是迁移脚本目录与当前 revision，数据备份请使用数据库自身的工具（`pg_dump` 等）。

---

## 开发

```bash
pip install -e ".[dev]"
pytest
```

测试覆盖：配置校验（含字段默认值、`index.where` 与 `expressions` 的注入尝试）、类型目录（含“登记的类型名必须真实存在于 SQLAlchemy”的校验、以及 udt 类型的生成）、生成产物可编译且**可导入**（含真实 DDL 断言）、`nullable`/`unique` 语义、索引方言参数与表达式索引、`UNLOGGED` 与 `CONCURRENTLY`、方言 import 分组、“模板缺失时不写空文件”、连接串遮盖与 fail-closed 解析、`install.lock` 往返与篡改检测、以及 `init → generate → migrate → upgrade → status` 的端到端流程。

---

## 许可证

本项目采用 **MIT License**。详见 [LICENSE](LICENSE)。

---

## 致谢

- [Alembic](https://alembic.sqlalchemy.org/) 提供迁移能力
- [SQLAlchemy](https://www.sqlalchemy.org/) 提供 ORM 框架
- 灵感来自北欧神话中的女神 **Gefjon**

---

**Gefjon** —— 让你的数据库版本管理，如预言般清晰。

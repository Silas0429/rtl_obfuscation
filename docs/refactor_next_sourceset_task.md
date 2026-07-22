# 下一步实现计划：SourceSet 与三入口输入合同

- 计划状态：`CONTRACTED_AS_T039`
- 所属阶段：R1
- 实现状态：`ACCEPTED`，交付提交 `5a8b073`
- 后续任务：[`T040`](tasks/T040_source_catalog_owner_registry.md) 已设为 `READY`
- 前置条件：已满足；T038 工作区已保存为提交 `e4f3f94`
- Formal verification：`N/A`，本步骤不产生 rewritten RTL

本文保留为 R1 设计草案；正式实现边界、API、fixture 和验收以
[`docs/tasks/T039_sourceset_input_contract.md`](tasks/T039_sourceset_input_contract.md) 为准。T038
停点已由主 Agent 保存为提交 `e4f3f94`，用户随后授权建立 T039。

## 1. 单一目标

新增一个不依赖 rewrite、inventory 或 mapping 版本的 `SourceSet` 输入层，使单文件、显式
filelist 和 project-root 三个 adapter 输出同一种、可比较、可序列化的数据结构。

本步骤只证明输入文件集合、顺序、include/define、top 和 closure 语义，不收集可重命名对象，
不生成 gate，不修改现有 encrypt/decrypt 行为。

## 2. 固定数据合同

最小 SourceSet 记录：

```text
schema_version: 1
origin: single-file | filelist | project-root
source_root: Path
ordered_source_files: tuple[str, ...]
included_files: tuple[str, ...]
include_dirs: tuple[str, ...]
defines: tuple[tuple[str, str], ...]
top: str | None
top_closure_files: tuple[str, ...]
compile_order: tuple[str, ...]
```

约束：

1. 所有记录使用 source-root-relative POSIX 路径；
2. `ordered_source_files` 对 single-file/filelist 保留用户顺序，禁止排序；
3. single-file/filelist 的 `compile_order` 保持显式 source 顺序；project-root 根据依赖生成确定顺序；
4. `.svh` 只进入 `included_files`，不作为独立 source unit；
5. filelist 无 top 时，`top_closure_files=()`；
6. filelist 有 top 时，`ordered_source_files` 仍包含全部列出文件，closure 只作为 overlay；
7. project-root 必须提供 top，且 `ordered_source_files` 只包含自动发现的 top closure source units；
8. 单文件 adapter 必须等价于一个只含该文件的 filelist adapter；
9. adapter 失败必须返回稳定错误码，不写输出文件或缓存。

首批固定错误码：

- `SOURCESET_DUPLICATE_FILE`；
- `SOURCESET_PATH_OUTSIDE_ROOT`；
- `SOURCESET_FILE_NOT_FOUND`；
- `SOURCESET_UNSUPPORTED_FILE`；
- `SOURCESET_TOP_REQUIRED`；
- `SOURCESET_TOP_NOT_FOUND`。

## 3. 建议实现边界

### 3.1 新模块

新增 `rtl_obfuscator/source_set.py`，只包含：

- `SourceSet` frozen dataclass；
- `from_single_file(...)`；
- `from_filelist(...)`；
- `from_project_root(...)`；
- `to_report()`，返回可 JSON 序列化的稳定 dict；
- 路径、重复项、include/define 和 top 参数校验。

project-root adapter 可以复用现有 discovery 代码，但不得把旧 inventory、profile、mapping 或
rewrite 逻辑导入新模块。若必须提取 discovery helper，只允许做无行为变化的最小移动，并由目标
测试覆盖。

### 3.2 不包含

- 不新增 mapping 版本；
- 不修改 category registry；
- 不收集 SymbolGraph 或 source ranges；
- 不改写 RTL；
- 不修改 encrypt/decrypt/formal-view/formal-align；
- 不删除 legacy 代码或测试；
- 不处理嵌套 `-f`、library mapping、DPI、bind 或 class；
- 不增加兼容 fallback。

## 4. 固定 compact fixture

新增 `tests/fixtures/refactor_source_set/`：

```text
design.f
rtl/z_defs.sv
rtl/a_child.sv
rtl/top.sv
rtl/unused.sv
include/common.svh
```

fixture 必须故意让 filelist 顺序不同于路径排序，并覆盖：

- `z_defs.sv` 在 `a_child.sv` 之前；
- top 依赖 child 和 include header；
- `unused.sv` 在 filelist 中但不在 top closure；
- project-root discovery 排除 unused；
- single-file fixture 不依赖外部可改写 source；
- 一个重复 filelist entry 负例；
- 一个 source-root 外路径负例；
- 一个 project-root 缺失 top 负例。

fixture 只为 SourceSet 语义服务，不冻结 renaming entry 数量。

## 5. 机器可检查结果

目标测试至少断言：

1. single-file 与单项 filelist 的 normalized report 相同，允许 `origin` 字段不同；
2. filelist 的 `ordered_source_files` 与 `design.f` 原顺序逐项相同；
3. filelist + top 保留 `unused.sv`，但 `top_closure_files` 不包含它；
4. project-root + top 只产生 closure source files；
5. 等价 project-root 与显式 closure filelist 的 include/define/top/closure/compile-order 相同；
6. include header 只出现在 `included_files`；
7. 重复项、越界路径和 project-root 缺失 top 使用稳定错误码失败；
8. 连续两次 `to_report()` byte-identical。

本任务不冻结 RISC-V-Vector 数量、mapping manifest 或随机名称。

## 6. 允许修改的文件

- `rtl_obfuscator/source_set.py`；
- `rtl_obfuscator/project.py`，仅在必须提取无行为变化 discovery helper 时允许；
- `tests/fixtures/refactor_source_set/**`；
- `tests/test_source_set.py`；
- 对应的活动任务单；
- 本计划和总重构计划，仅用于记录实际偏差。

不得修改 `rtl_obfuscator/inventory.py`、`rtl_obfuscator/rewrite.py`、现有 RTL 样例、旧 mapping
validator、Formal 脚本或历史测试 oracle。

## 7. 简化验收命令

只运行以下命令：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_source_set -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py tests/test_source_set.py
git diff --check
```

不运行全量 unittest、RISC-V-Vector、Yosys、Verible 或 Icarus。原因是本任务只建立输入数据合同，
不解析重命名对象，也不产生 rewritten RTL。

## 8. 子 Agent 完成标准

只有同时满足以下条件才可设为 `READY_FOR_REVIEW`：

- 目标测试全部通过；
- 没有修改允许列表外文件；
- 没有改变现有 encrypt/decrypt 行为；
- filelist 顺序没有被排序；
- project-root 只是 SourceSet adapter，没有新增独立 inventory 分支；
- 所有错误在写 artifact 前发生；
- 任务单记录实际命令、退出码、测试数和未覆盖边界；
- Formal 记录为 `N/A: no rewritten RTL is produced`。

## 9. 主 Agent 验收

主 Agent 只需：

1. 检查实际 diff 是否符合允许文件；
2. 独立执行第 7 节三条命令；
3. 对比 single/filelist/project-root 的 normalized report；
4. 确认没有新增 mapping/profile/legacy 分支；
5. 通过后设置 `ACCEPTED`，再创建 R2 任务。

不得为了“更完整”临时增加 RISC Formal、全量回归或历史 mapping 数量验收。

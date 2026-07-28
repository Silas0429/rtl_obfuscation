# T059：公共 Python 脚本入口与分层使用说明

- 状态：ACCEPTED
- 合同版本：1.1
- 设计时间：2026-07-28
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T058 `ACCEPTED`
- 起始 HEAD：`0da0ab27a151d6fc0e2165877cb5df03d580a3f6`
- 任务类型：公共 Python adapter + 用户文档

## 1. 变更说明

合同 v1.0 曾错误地把公共入口定义为 `pyproject.toml` console scripts。用户在实现尚未提交、
尚未进入主 Agent 验收前明确否决该方案。v1.0 现已撤回，其安装、wheel、entry-point
metadata 要求全部作废，相关临时文件和测试不得保留。

本合同只新增仓库根目录两个 Python 薄封装：

```sh
python rtl_encrypt.py ...
python rtl_decrypt.py ...
```

用户无需安装本项目；默认其 Python 环境已经安装 PySlang。项目内部验收仍按 `AGENTS.md`
使用 Conda 环境。

## 2. 单一目标

将现有加密、恢复函数通过两个简洁 Python 脚本暴露给用户，并把 README 改为：

1. 先解释单文件、filelist、project-root 三种输入模式的范围；
2. 再依次给出每种模式的基础格式、必填参数、示例架构和可复制命令；
3. 最后说明解密与完整加密选项。

本任务只新增公共适配层并复用现有实现，不修改 category、SymbolGraph、mapping、gate、
restore、rate、metrics 或 Formal 语义。

## 3. 公共脚本合同

### 3.1 `rtl_encrypt.py`

根目录脚本必须是薄封装，只导入并调用：

```python
rtl_obfuscator.rewrite.rtl_encrypt_main
```

其命令行直接接受现有 `encrypt-vnext` 的参数，但用户不得再提供 operation positional
argument。帮助页不得出现 `encrypt-vnext`、`decrypt-vnext` 或要求用户理解 vNext。

参数校验、稳定错误码、stdout JSON、原子发布和持久化 schema 必须与现有实现完全相同。
不得复制 `_encrypt_vnext`、orchestration 或 parser 语义。

### 3.2 `rtl_decrypt.py`

根目录脚本必须是薄封装，只导入并调用：

```python
rtl_obfuscator.rewrite.rtl_decrypt_main
```

公共恢复脚本要求 `--map`、`--gate-dir`、`--source-root`、`--output-dir`、`--report`
全部必填。它必须复用现有 `_decrypt_vnext` 路径，不得复制 hydration、audit、restore 或
publish 逻辑。

### 3.3 共享实现

`rtl_obfuscator/rewrite.py` 可以做且只可以做以下适配重构：

- 把 encrypt/decrypt 参数注册抽成内部共享函数；
- 增加 `rtl_encrypt_main()` 和 `rtl_decrypt_main()`；
- 把 operation 分派后的执行与错误处理抽成共享函数；
- 保持 `python -m rtl_obfuscator.rewrite encrypt-vnext|decrypt-vnext` 行为兼容。

不得在根目录脚本内实现参数解析、加密、恢复或错误处理逻辑。

### 3.4 明确禁止

- 最终工作区不得存在本任务新增的 `pyproject.toml`；
- 不增加 pip 安装步骤、console scripts、wheel 测试、shell wrapper、alias 或 PATH 修改；
- README 只展示 `python rtl_encrypt.py ...` 和 `python rtl_decrypt.py ...`；
- vNext report/schema 名称保持不变，本任务不迁移持久化格式；
- 内部 module operation 暂时保留给兼容测试，但不得出现在用户文档中。

## 4. README 固定信息架构

README 开头用不超过两段说明本项目加密 SystemVerilog 标识符，并说明：

- 从仓库根目录运行；
- 用户 Python 环境已安装 PySlang；
- 可用 `python rtl_encrypt.py --help`、`python rtl_decrypt.py --help` 查看帮助；
- 不要求安装本项目，不解释 vNext、内部 pipeline、Formal 或历史任务。

在任何具体运行示例之前，用表格比较：

| 模式 | 输入范围 | `--top` | 普通名称范围 | ABI 范围 |
| --- | --- | --- | --- | --- |
| 单文件 | 一个 `.sv` 及其 include | 可选 | 该输入文件 | 只有提供 top 且显式授权时 |
| filelist | `.f` 中全部 `.sv/.svh` | 可选 | 全部清单文件 | 仅 top 闭包内显式授权对象 |
| project-root | 自动发现的 top 闭包 | 必填 | 自动发现闭包 | 仅闭包内显式授权对象 |

表后必须直接澄清：

- `--filelist` 支持可选 `--top`；
- filelist 中所有 physical files 都进入普通名称加密范围；
- `--top` 只确定 ABI 分析边界，不把普通名称加密限制为 top closure；
- selected top 自身的外部端口边界保持不变；
- 未提供 `--category` 时使用默认 13 类；
- 一旦显式提供 `--category`，默认类别不会自动追加；
- `all` 等于默认 13 类，不包含额外 ABI 类；
- module、port、interface 等额外类型必须用 `--category` 显式选择；
- 跨模块 ABI 名称还必须逐类使用 `--abi-category` 授权；只选择 category 不代表 ABI
  名称会被替换；
- 详细类型链接到 `docs/systemverilog_renaming_table.md`。

### 4.1 三种加密方式

每种方式严格按以下小节顺序：

1. **基础命令格式**：使用 `python rtl_encrypt.py` 和占位参数；
2. **必填参数**：只解释该模式真正必填的参数；
3. **项目示例**：说明使用仓库中的哪个样例；
4. **示例架构**：简要说明文件/module 关系；
5. **运行示例**：提供从仓库根目录可直接复制的命令。

固定样例：

- 单文件：`rtl_samples/11_supported_obfuscation.sv`；
- filelist：`rtl_samples/example_fifo/design.f`，并演示可选 `--top fifo_top`；
- project-root：`rtl_samples/example_fifo`，`--top fifo_top` 必填。

单文件和 filelist 示例保持基础、可读，使用默认 13 类；filelist 示例仍必须提供可选
`--top fifo_top`，用于直观说明 top 不会缩小普通名称的 filelist 输入范围。

project-root 运行示例承担一次“当前支持范围完整选择”的演示，必须同时包含：

```text
--category all --category modules --category ports --category interface
--abi-category parameters --abi-category typedefs
--abi-category struct_types --abi-category struct_fields --abi-category union_fields
--abi-category modules --abi-category ports
--abi-category interfaces --abi-category interface_instances
--abi-category interface_ports --abi-category modports
```

文档必须准确说明：

- `--category all` 补入默认 13 类，另外三个 category 补入默认外的 6 类；
- `--abi-category` 列表授权闭包内允许变化的跨模块名称；
- selected top 名称及其外部端口仍按 ABI 边界保留；
- `fifo_bus` 虽属于 `interface_instances`，但当前实现把 selected top 内声明的该实例标为
  `selected_top_boundary`，所以即使 category 与 ABI category 都选择也仍会保留；文档必须
  如实标注该当前边界，不得暗示本任务已经修复；
- 即使完整选择，也不得宣称所有词法标识符都会被替换。

三个示例使用互不重叠、父目录已创建的临时输出路径，不依赖已有输出。

### 4.2 解密和选项

- 在三种加密方式之后给出 `python rtl_decrypt.py` 基础格式；
- 解释五个必填参数；
- 给出一个消费前述 project-root 产物的可复制示例；
- 文档末尾保留 `rtl_encrypt.py` 的完整参数表；
- 不展示内部 `python -m rtl_obfuscator.rewrite ...-vnext`。

## 5. 开发文档同步

- `docs/project_structure.md`：产品入口改为根目录两个 Python 脚本；
- `docs/formal_verification.md`：用户侧命令使用根目录脚本，schema 名称不变；
- `docs/systemverilog_renaming_table.md`：完整用户命令使用根目录脚本；
- 不改历史任务合同中的历史命令。

## 6. 测试合同

新增/更新测试，至少覆盖：

1. 两个根目录脚本存在，且只作为共享 main 函数的薄封装；
2. 用实际 `python rtl_encrypt.py --help`、`python rtl_decrypt.py --help` 执行帮助页；
3. help 不出现内部 operation 或 vNext；
4. 脚本分别完成 single、filelist + optional top、project-root 三种黑盒运行；
5. `rtl_decrypt.py` 消费公共加密产物并恢复全部 physical files byte-identical；
6. 缺少必填参数时无 traceback、无部分输出；
7. README 顺序、脚本命令和固定样例受测试保护；
8. project-root 完整选择示例的实际 report 包含闭包内 interface 类型、成员、module 和
   port 等 ABI rename 记录，同时包含 `fifo_bus` 的 `interface_instances` +
   `selected_top_boundary` preserve 记录；
9. filelist actual gate 执行 compact Formal 正例；
10. actual gate 复制后只增加一个固定 `~` 的功能负例，strict compile 通过，Formal 非零且
   包含 `unproven`、`equiv_status -assert`；
11. 内部 operation 仍只有两个，公共 main 与内部实现共享且不引入 legacy module。

测试不得读取或构建 `pyproject.toml`，不得构建 wheel，不得模拟 console entry point。

## 7. 允许修改的文件

```text
rtl_encrypt.py
rtl_decrypt.py
rtl_obfuscator/rewrite.py
tests/test_public_cli.py
tests/test_vnext_product_surface.py
README.md
docs/project_structure.md
docs/formal_verification.md
docs/systemverilog_renaming_table.md
docs/tasks/T059_public_cli_and_guided_readme.md
```

`pyproject.toml` 是撤回方案产生的未跟踪临时文件，只允许删除，不允许出现在最终 diff 中。
不允许修改 fixture、核心语义模块、RISC 脚本、历史任务合同或其他测试。

## 8. 明确不包含

- 不修复或重新分类 selected-top 内部 `interface_instances`；
- 不修复用户此前指出的局部变量/实例名 category 归属；
- 不删除内部 `encrypt-vnext/decrypt-vnext`；
- 不改 stdout/report 中的 vNext schema 名；
- 不改 category/default/ABI/top-boundary 行为；
- 不运行 RISC-V-Vector Formal。

## 9. 子 Agent 验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_public_cli tests.test_vnext_product_surface -v
```

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext -v
```

```sh
conda run -n rtl_obfuscation python -m py_compile rtl_encrypt.py rtl_decrypt.py rtl_obfuscator/rewrite.py tests/test_public_cli.py tests/test_vnext_product_surface.py
```

```sh
git diff --check HEAD
```

```sh
test ! -e pyproject.toml
```

```sh
rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T059_public_cli_and_guided_readme.md
```

## 10. Formal verification

本任务的公共脚本产生 rewritten RTL，`tests/test_public_cli.py` 必须从实际
`python rtl_encrypt.py` filelist 输出执行：

```text
gold: tests/fixtures/refactor_symbol_graph_parameters
gate: temporary public script output
top: parameter_top
seq: 5
positive: exit 0 and formal_equivalence=pass
negative: exactly one inserted '~'; strict compile PASS; nonzero and contains unproven plus equiv_status -assert
```

不得使用身份比较代替，也不得运行 RISC-V-Vector Formal。

## 11. 恢复执行要求

当前工作区包含 v1.0 中断时的未提交改动。子 Agent 必须：

1. 先核对所有改动均属于 T059 中断实现；
2. 将本合同状态从 `READY` 改为 `IN_PROGRESS`；
3. 保留符合 v1.1 的共享 parser/执行函数重构与 README 信息结构；
4. 删除 `pyproject.toml` 及安装/wheel/entry-point 测试；
5. 新增根目录薄脚本并按本合同收敛文档；
6. 在执行记录中明确列出“保留、删除、重写”的 v1.0 内容。

不得通过重置、checkout 或清理命令丢弃未审计内容。

## 12. 执行记录

- 初始开始时间：2026-07-28
- 实际起始 HEAD：`0da0ab27a151d6fc0e2165877cb5df03d580a3f6`
- v1.0 中断时未执行 add、commit、push，未进入主 Agent 验收。
- v1.0 撤回原因：用户要求的是 Python 脚本封装函数接口，不是安装型 console entry point；
  主 Agent 对公共入口形态做了过度设计。
- v1.1 恢复执行开始：2026-07-28
- 恢复前核对：
  - HEAD 为 `0da0ab27a151d6fc0e2165877cb5df03d580a3f6`；
  - 工作区仅包含 T059 v1.0 中断产生的 README、三份当前开发文档、
    `rtl_obfuscator/rewrite.py`、两份 T059 测试、当前合同和未跟踪
    `pyproject.toml`；
  - 未发现合同允许范围之外的改动。
- v1.0 内容处置计划：
  - 保留并重新审计 `rewrite.py` 的共享参数注册、共享执行和 public main 重构；
  - 保留 README 的三模式优先信息结构，移除安装段并改写全部公共命令；
  - 删除 `pyproject.toml`；
  - 删除 wheel、`tomllib`、entry-point metadata 相关测试；
  - 把 `python -c` 模拟入口测试重写为实际根目录 Python 脚本子进程测试。
- v1.1 验收证据：以下结果全部来自本轮恢复执行，未复用 v1.0 中断前结果。
- 实现期间合同修订复核：
  - 主 Agent 明确单文件和 filelist 示例只使用默认 13 类；
  - project-root 示例使用 19 类完整 category selection 和全部
    `MODULE_ABI_CATEGORIES` 授权；
  - 依据主 Agent 独立实际运行结果，冻结 `modified_tokens=268`，闭包内 interface 类型、
    interface members、module 和 port 存在 ABI rename；
  - `fifo_bus` 的实际记录为 `category=interface_instances`、`action=preserve`、
    `reason=selected_top_boundary`，README 和测试均按当前边界记录，没有修改核心分类。
- v1.0 内容实际处置：
  - 保留并审计 `rewrite.py` 的共享参数注册、共享执行、两个 public main；
  - 保留并修订 README 的三模式分层结构；
  - 删除未跟踪 `pyproject.toml`；
  - 删除 wheel、`tomllib`、entry-point metadata 和 `python -c` 模拟入口测试；
  - 新增根目录 `rtl_encrypt.py`、`rtl_decrypt.py` 薄封装；
  - 公共入口黑盒测试全部改为实际 `python rtl_encrypt.py` /
    `python rtl_decrypt.py` 子进程。
- 实际修改文件：
  - `rtl_encrypt.py`
  - `rtl_decrypt.py`
  - `rtl_obfuscator/rewrite.py`
  - `tests/test_public_cli.py`
  - `tests/test_vnext_product_surface.py`
  - `README.md`
  - `docs/project_structure.md`
  - `docs/formal_verification.md`
  - `docs/systemverilog_renaming_table.md`
  - `docs/tasks/T059_public_cli_and_guided_readme.md`
- 专项测试：
  - 命令：
    `conda run -n rtl_obfuscation python -m unittest tests.test_public_cli tests.test_vnext_product_surface -v`
  - 首轮：12 tests 中 11 通过；唯一失败是 README 测试把说明文字中的
    “不提供 `--category`”误判为命令行参数；
  - 修正：仅把断言收紧为禁止命令块中的 `\n  --category`，未改变产品行为；
  - 最终：12 tests，全部通过，exit 0。
- 兼容回归：
  - 命令：
    `conda run -n rtl_obfuscation python -m unittest tests.test_cli_vnext_encryption tests.test_restore_vnext tests.test_project_root_vnext -v`
  - 结果：15 tests，全部通过，exit 0。
- 编译检查：
  - 命令：
    `conda run -n rtl_obfuscation python -m py_compile rtl_encrypt.py rtl_decrypt.py rtl_obfuscator/rewrite.py tests/test_public_cli.py tests/test_vnext_product_surface.py`
  - 结果：exit 0。
- 差异检查：`git diff --check HEAD`，exit 0。
- 撤回方案守卫：`test ! -e pyproject.toml`，exit 0。
- 公共 project-root 完整选择黑盒结果：
  - origin=`project-root`，top=`fifo_top`，4 physical files；
  - `modified_tokens=268`；
  - `interfaces:fifo_if`、interface members、modports、`modules:fifo_ctrl` 和 ports
    存在 `abi=module_abi` rename；
  - `fifo_bus` 唯一记录为 `interface_instances` +
    `preserve:selected_top_boundary`；
  - strict compile 通过，restore 后 4 files byte-identical。
- 独立 Formal 证据：
  - acceptance root：`/tmp/t059-v11-formal.ZfhHsR`；
  - gold：`tests/fixtures/refactor_symbol_graph_parameters`；
  - actual gate：`/tmp/t059-v11-formal.ZfhHsR/gate`；
  - top：`parameter_top`，seq=`5`；
  - 加密命令：
    `conda run -n rtl_obfuscation python rtl_encrypt.py --filelist design.f --source-root tests/fixtures/refactor_symbol_graph_parameters --top parameter_top --category signals --category parameters --category genvars --abi-category parameters --encryption-rate 0.35 --name-length 16 --output-dir /tmp/t059-v11-formal.ZfhHsR/gate --map /tmp/t059-v11-formal.ZfhHsR/mapping.json --metrics /tmp/t059-v11-formal.ZfhHsR/metrics.json`；
  - 加密结果：exit 0，31 mapping records，25 modified tokens，strict compile 通过，
    restore byte-identical；
  - Formal 命令：
    `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/refactor_symbol_graph_parameters/design.f --gold-root tests/fixtures/refactor_symbol_graph_parameters --gate-filelist /tmp/t059-v11-formal.ZfhHsR/gate/design.f --gate-root /tmp/t059-v11-formal.ZfhHsR/gate --top parameter_top --seq 5`；
  - 正例：exit 0，
    `{"formal_equivalence":"pass","gate":"/tmp/t059-v11-formal.ZfhHsR/gate","gold":"tests/fixtures/refactor_symbol_graph_parameters","seq":5,"top":"parameter_top"}`；
  - 负例：复制 actual gate 到 `/tmp/t059-v11-formal.ZfhHsR/negative`，仅把
    `assign data_o = ...` 改为 `assign data_o = ~...`，确认只增加一个固定 `~`；
  - 负例 strict compile：
    `catalog=0/0`、`top_overlay=0/0`；
  - 负例使用同一 Formal 命令，只替换 gate root/filelist 为 `negative`，exit 1，输出包含
    `unproven` 和 `equiv_status -assert`。
- 未覆盖边界：
  - 本任务不修复 selected-top 内部 `interface_instances` 分类/边界；
  - 不迁移 stdout/report 中的 vNext schema 名；
  - 不删除内部 `encrypt-vnext/decrypt-vnext` 兼容 operation；
  - 未运行 RISC-V-Vector Formal；
  - 未增加项目安装、console entry point、wheel 或 PATH 机制。
- Git：未执行 add、commit、push；未设置 `ACCEPTED`；未创建 T060。
- 主 Agent review 退回：2026-07-28
  - 原因：README 已说明 selected top 内 `fifo_bus` 的
    `interface_instances + selected_top_boundary` 保留边界，但
    `docs/systemverilog_renaming_table.md` 未同步这一例外；
  - 修正范围冻结为 `docs/systemverilog_renaming_table.md`、
    `tests/test_public_cli.py` 和本执行记录；
  - 状态已退回 `IN_PROGRESS`，不修改核心实现或其他文档。
- 主 Agent review 小修结果：
  - `docs/systemverilog_renaming_table.md` 的 `interface_instances` 行已明确：
    双重 category/ABI 授权适用于闭包内其他符合条件的对象，selected top 内声明的实例当前
    仍按 `selected_top_boundary` 保留；
  - 表后新增 FIFO `fifo_bus` 例外说明，与 README 保持一致；
  - `tests/test_public_cli.py` 新增跨文档一致性守卫，要求 README 和类型表同时包含
    `interface_instances`、`fifo_bus`、`selected_top_boundary` 以及双重授权后仍保留的说明；
  - 本轮除类型表、公共 CLI 测试和本执行记录外，未修改核心实现或其他文档。
- review 小修复验：
  - 专项命令：
    `conda run -n rtl_obfuscation python -m unittest tests.test_public_cli tests.test_vnext_product_surface -v`；
  - 结果：12 tests，全部通过，exit 0；
  - 编译命令：
    `conda run -n rtl_obfuscation python -m py_compile rtl_encrypt.py rtl_decrypt.py rtl_obfuscator/rewrite.py tests/test_public_cli.py tests/test_vnext_product_surface.py`；
  - 结果：exit 0；
  - `git diff --check HEAD`：exit 0；
  - `test ! -e pyproject.toml`：exit 0；
  - 未执行 add、commit、push，未设置 `ACCEPTED`，未创建 T060。

## 13. 主 Agent 验收

主 Agent 必须独立审查：

- 最终 diff 中不存在 `pyproject.toml` 或安装机制；
- 两个根目录脚本确为薄封装；
- README 从模式影响范围开始，再按固定顺序介绍三种方式；
- README 全部用户命令使用 `python rtl_encrypt.py` / `python rtl_decrypt.py`；
- filelist `--top` 语义与当前实现一致；
- 三模式、恢复、错误边界和 compact Formal 正负例。

主 Agent 复跑第 9 节全部命令并独立核对 Formal 证据后，才可设为 `ACCEPTED`、提交和推送。

### 验收结果

- 验收时间：2026-07-28
- 变更范围：仅包含第 7 节允许文件；撤回方案的 `pyproject.toml` 不存在。
- 公共脚本与产品表面：12/12 tests 通过。
- 内部 CLI、restore、project-root 兼容回归：15/15 tests 通过。
- `py_compile`、`git diff --check HEAD`、无 `pyproject.toml` 守卫：全部 exit 0。
- 两个根目录脚本经逐行审查，只调用共享 public main；没有 parser 或产品逻辑副本。
- README 的三模式范围、固定小节顺序、filelist `--top` 说明、project-root 完整选择、
  decrypt 和选项表均与 actual report 一致。
- 类型表与 README 一致记录 `fifo_bus` 当前为
  `interface_instances + preserve:selected_top_boundary`；本任务未暗中改变核心分类。
- 主 Agent 独立 actual gate：
  `/tmp/t059-main-formal.nznunY/gate`，31 mapping records，25 modified tokens，
  strict compile 通过，restore byte-identical。
- 主 Agent Formal 正例：top=`parameter_top`、seq=`5`、exit 0、
  `formal_equivalence=pass`。
- 主 Agent 固定负例：仅在 actual gate 的 `assign data_o = ...` 增加一个 `~`；
  catalog/top-overlay 均为 0/0；Formal exit 1，包含 `unproven` 和
  `equiv_status -assert`。
- RISC-V-Vector Formal 未运行，符合合同边界。
- 验收结论：`ACCEPTED`。

# T060：简化 `rtl_encrypt.py` 用户工作流

- 状态：ACCEPTED
- 合同版本：1.0
- 设计时间：2026-07-28
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T059 `ACCEPTED`
- 起始 HEAD：`3a4f050`
- 任务类型：公共 CLI 简化 + 用户文档重构

## 1. 起始工作区

起始分支为 `main...origin/main [ahead 1]`。用户已修改 `README.md` 的“加密模式”部分，
将原有内部实现术语改写成数字 IC 设计工程师能够直接理解的模式说明。

该 README 修改属于用户输入，必须保留并在此基础上编辑；不得 reset、checkout、clean 或
覆盖恢复到 HEAD。

## 2. 单一目标

让不了解本项目软件架构的数字 IC 设计工程师只通过 `python rtl_encrypt.py` 即可完成：

1. 选择单文件、filelist 或 project-root；
2. 省略报告路径时得到固定位置的 mapping/metrics；
3. 在提供 `--top` 时自动一致地加密子模块端口、接口和跨模块引用；
4. 用 `--encryption-rate` 控制加密比例；
5. 从 README 和类型表快速知道命令、范围及可加密内容。

不得要求普通用户理解 ABI、vNext、mapping pipeline、policy、closure、semantic owner 或
Formal 等内部术语。

## 3. 公共 CLI 行为

以下规则只冻结根目录 `rtl_encrypt.py` 的公共用户表面。内部兼容命令
`python -m rtl_obfuscator.rewrite encrypt-vnext` 保持 T059 行为，不作为 README 用户入口。

### 3.1 必填输出

`--output-dir` 继续必填且目标必须不存在。

`--map` 和 `--metrics` 改为可选：

| 参数 | 省略时位置 | 显式指定 |
| --- | --- | --- |
| `--map` | `<output-dir>/mapping.json` | 只写入指定文件，不生成默认副本 |
| `--metrics` | `<output-dir>/metrics.json` | 只写入指定文件，不生成默认副本 |

默认报告与 RTL 必须作为同一次原子发布写入 `--output-dir`。显式报告路径必须保持既有
fail-closed、路径冲突和失败清理行为。允许一个报告使用默认路径、另一个显式指定。

默认输出目录因此可以包含：

```text
<rewritten RTL files>
design.f
mapping.json
metrics.json
```

restore/audit 必须允许并校验这两个固定报告文件，但仍拒绝任意未知附加文件。默认
`metrics.json` 必须与 mapping report 内嵌的 metrics 对象一致。

### 3.2 默认加密范围

公共 CLI 的无 `--category` 行为：

| 输入模式 | 未提供 `--top` | 提供 `--top` |
| --- | --- | --- |
| single | 默认 13 类内部名称 | 仍为默认 13 类，不自动扩大跨模块范围 |
| filelist | 全部清单文件的默认 13 类内部名称 | 全部清单文件先处理默认内部名称，并自动处理 top 影响范围内支持的全部跨模块类型 |
| project-root | 不允许 | 自动发现 top 使用的文件，并自动处理支持的全部内部和跨模块类型 |

“全部跨模块类型”在实现中等价于：

- selected categories 为 19 个 canonical categories；
- permitted cross-module categories 为全部 `MODULE_ABI_CATEGORIES`；
- top module 名称和对外端口继续保留；
- 当前实现仍保留 top module 内直接声明的 interface instance，例如 `fifo_bus`。

上述内部字段只用于实现和测试，禁止直接复制到 README 的普通用户说明中。

### 3.3 手动 `--category`

用户一旦显式提供 `--category`：

- 只处理用户选择的类型，不自动追加默认集合；
- filelist/project-root 有 `--top` 时，工具自动为所选类型处理跨模块一致改名；
- 用户无需再提供 `--abi-category`；
- 公共 help 不展示 `--abi-category`；
- 公共 `--category all` 选择当前支持的全部 19 类；
- 内部兼容 operation 的 `all` alias 和显式 `--abi-category` 行为不得改变。

### 3.4 加密率

公共 CLI 保持并测试：

```text
--encryption-rate RATE
```

- 合法范围为 `0 < RATE <= 1`；
- 省略表示处理当前范围内全部可加密名称；
- `1` 表示全部；
- 小于 `1` 时按可加密有效代码行选择接近目标比例的名称；
- 不得向用户承诺“精确替换同等比例的标识符个数”。

## 4. 实现边界

允许在 `rtl_obfuscator/rewrite.py`：

- 区分 public parser 与内部兼容 parser 的报告必填、category `all` 和跨模块自动选择行为；
- 为默认报告路径增加明确的内部 resolution/publish metadata；
- 继续复用唯一 `_encrypt_vnext`、orchestration、rate 和错误处理路径。

允许在 `rtl_obfuscator/restore_vnext.py`：

- audit 时识别位于 gate 内的固定 `mapping.json` 和 `metrics.json`；
- 校验默认 metrics 与主 report 的内嵌 metrics 一致；
- 保持未知额外文件、篡改报告和 gate 仍 fail-closed。

禁止：

- 修改 SymbolGraph、category registry、rewrite policy、rate 算法或 top-boundary 语义；
- 为 public CLI 复制第二套加密流程；
- 修改 RTL fixture；
- 删除内部兼容 operation；
- 修复 `fifo_bus` 分类；
- 运行 RISC-V-Vector Formal。

## 5. README 信息结构

README 面向数字 IC 设计工程师，固定为：

1. 项目用途、Python + PySlang 前提和 help；
2. **加密模式**：保留用户已写的四列表格和简洁说明，按实际新行为校正；
3. **输出文件和加密率**：说明 `--output-dir`、默认 reports、`--encryption-rate`；
4. **单文件加密**：基础命令 + 合并后的“示例与架构”；
5. **Filelist 多文件加密**：基础命令 + 合并后的“示例与架构”；
6. **Project-root 项目加密**：基础命令 + 合并后的“示例与架构”；
7. **解密**：使用默认 `<output-dir>/mapping.json`；
8. **常用可选参数**：只保留 include、define、category、rate、name length、map、metrics；
9. 链接 `docs/systemverilog_renaming_table.md`。

README 所有基础命令只写真正必填参数；`--map`、`--metrics` 不得继续出现在必填格式中。

禁止使用这些面向实现的词语：

```text
ABI
vNext
physical files
top closure
selected_top_boundary
semantic
mapping pipeline
```

允许使用数字 IC 常用词：module、port、interface、parameter、top、filelist。

必须用普通语言说明当前 `fifo_bus` 边界：

> 当前版本会保留 top module 内部直接声明的 interface 实例名；interface 类型和成员仍会加密。

## 6. 可加密类型表

`docs/systemverilog_renaming_table.md` 面向用户重写，不再使用 ABI 列和实现术语。

至少包含：

- 19 个 `--category` 值；
- 中文“加密内容”；
- 是否属于默认 13 类；
- 无 top 与有 top 时的直观行为；
- `struct`、`interface`、public `all` 快捷值；
- top module 名称/端口保留；
- top 内 interface instance 当前保留；
- 两至三个可复制的 `--category` 示例。

## 7. 黑盒验收

公共测试必须通过实际 `python rtl_encrypt.py` / `python rtl_decrypt.py` 子进程验证：

1. help 显示 `--encryption-rate`，`--map/--metrics` 为可选，不显示
   `--abi-category`；
2. single 无 top、无 category：默认 13 类、无跨模块改名、默认 reports；
3. filelist 无 top：全部清单文件处理默认 13 类；
4. filelist + top、无 category：19 类选择、全部跨模块权限、清单外 top 范围不扩大；
5. project-root、无 category：19 类选择、全部跨模块权限、top 名称与对外端口保留；
6. project-root 显式 `--category signals --category ports`：只选择这两类，ports 自动跨模块
   一致改名；
7. public `--category all` 选择 19 类；
8. reports 均默认、均显式和一默认一显式三种发布组合；
9. default mapping 能由 `rtl_decrypt.py` 跨进程恢复全部源文件 byte-identical；
10. 默认 reports 可被 restore audit 接受，metrics 不一致和未知附加文件被拒绝；
11. `--encryption-rate 0.35` 产生 rate-enabled report，合法范围与失败清理通过；
12. 内部 operation 仍要求 `--map/--metrics`，保留显式 `--abi-category` 和旧 `all` 语义；
13. README 没有禁止词，章节顺序、基础命令和固定样例正确；
14. 类型表 19 类、默认 13 类和 top 行为与 actual report 一致。

## 8. Formal

本任务改变公共默认 rewritten RTL，必须从实际公共 filelist + top + 默认 reports +
`--encryption-rate 0.35` 产物执行 compact Formal：

```text
gold: tests/fixtures/refactor_symbol_graph_parameters
gate: actual <output-dir>
top: parameter_top
seq: 5
positive: exit 0 and formal_equivalence=pass
negative: copy actual gate, add exactly one '~', strict compile 0/0,
          Formal nonzero with unproven and equiv_status -assert
```

负例复制 gate 时必须连同默认 reports 保留；strict compile 只读取 design.f 中的 RTL。

## 9. 允许修改

```text
rtl_obfuscator/rewrite.py
rtl_obfuscator/restore_vnext.py
tests/test_public_cli.py
tests/test_restore_vnext.py
tests/test_vnext_product_surface.py
README.md
docs/systemverilog_renaming_table.md
docs/tasks/T060_simplified_rtl_encrypt_workflow.md
```

不允许修改其他产品模块、fixture、历史任务合同或计划文档。

## 10. 子 Agent 验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_public_cli tests.test_restore_vnext tests.test_vnext_product_surface -v
```

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_cli_vnext_encryption tests.test_project_root_vnext -v
```

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_encrypt.py rtl_decrypt.py rtl_obfuscator/rewrite.py \
  rtl_obfuscator/restore_vnext.py tests/test_public_cli.py \
  tests/test_restore_vnext.py tests/test_vnext_product_surface.py
```

```sh
git diff --check HEAD
```

```sh
rg -x -- '- 状态：READY_FOR_REVIEW' \
  docs/tasks/T060_simplified_rtl_encrypt_workflow.md
```

## 11. 执行记录

- 状态变化：`READY -> IN_PROGRESS`。
- 实际起始 HEAD：`3a4f050`。
- 实际起始分支：`main...origin/main [ahead 1]`。
- 实际起始工作区：

  ```text
   M README.md
  ?? docs/tasks/T060_simplified_rtl_encrypt_workflow.md
  ```

- 起始差异归属：`README.md` 为用户已修改内容；T060 合同为主 Agent 新建文件。实现将在
  README 用户版本上继续编辑，不执行 reset、checkout 或 clean。
- 已完整读取 T060 合同、README 起始 diff、T059 合同与公共脚本实现，以及第 9 节全部
  允许文件。
- 状态变化：实现和自验完成后为 `IN_PROGRESS -> READY_FOR_REVIEW`。

### 11.1 README 与实际修改

- 保留用户将入口章节命名为“加密模式”、使用“模式/输入/加密范围/加密内容”四列表格，
  以及用数字 IC 工程师常用语言解释三种模式的意图。
- 按实际公共行为校正 filelist + top、project-root、默认 13/19 类、默认报告和加密率，
  合并原“项目示例/示例架构”为“示例与架构”。
- README 和类型表不再出现普通用户无需理解的实现术语；基础命令不要求 `--map` 或
  `--metrics`。
- 实际修改文件仅为：

  ```text
  README.md
  docs/systemverilog_renaming_table.md
  rtl_obfuscator/rewrite.py
  rtl_obfuscator/restore_vnext.py
  tests/test_public_cli.py
  tests/test_vnext_product_surface.py
  docs/tasks/T060_simplified_rtl_encrypt_workflow.md
  ```

### 11.2 公共行为证据

- public help：`--map`、`--metrics` 为可选，包含 `--encryption-rate`，不包含
  `--abi-category`。
- reports 发布矩阵全部通过：

  | map | metrics | gate 内文件 |
  | --- | --- | --- |
  | 默认 | 默认 | `mapping.json`、`metrics.json` |
  | 显式 | 显式 | 无默认副本 |
  | 默认 | 显式 | 仅 `mapping.json` |
  | 显式 | 默认 | 仅 `metrics.json` |

- 每种组合的 metrics 文件均与主报告内嵌 metrics 对象相等；预先存在的显式报告路径会
  fail-closed，gate 和另一默认报告均不产生。
- actual selection：

  | 模式 | selected categories | permitted cross-module categories |
  | --- | ---: | ---: |
  | single 默认 | 13 | 0 |
  | filelist 无 top 默认 | 13 | 0 |
  | filelist + top 默认 | 19 | 11 |
  | project-root 默认 | 19 | 11 |
  | project-root 显式 signals + ports | 2 | 1（ports） |
  | public `--category all` | 19 | 依输入模式自动确定 |
  | internal operation `--category all` | 13 | 保持显式参数行为 |

- README 最简 project-root 命令 actual summary：4 files、81 mapping records、
  268 modified tokens、strict compile PASS；top 名称和对外 ports 保留，默认两个报告存在。
- project-root 跨进程 restore：4 files 全部 byte-identical。
- 默认报告可通过共享 gate audit；默认 metrics 与主报告不一致时返回
  `RESTORE_VNEXT_REPORT_INVALID`，增加未知 JSON 时返回
  `RESTORE_VNEXT_GATE_INVALID`，均无部分恢复输出。
- `--encryption-rate 0.35` actual report 为 rate enabled；`0`、`1.01`、`nan` 均返回
  `CLI_VNEXT_RATE_INVALID` 且无 gate。

### 11.3 验收命令与结果

执行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_public_cli tests.test_restore_vnext tests.test_vnext_product_surface -v
```

最终结果：21 tests，全部通过，exit code 0。

执行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_cli_vnext_encryption tests.test_project_root_vnext -v
```

结果：10 tests，全部通过，exit code 0。

执行：

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_encrypt.py rtl_decrypt.py rtl_obfuscator/rewrite.py \
  rtl_obfuscator/restore_vnext.py tests/test_public_cli.py \
  tests/test_restore_vnext.py tests/test_vnext_product_surface.py
```

结果：exit code 0。

执行 `git diff --check HEAD`：exit code 0。
执行 READY_FOR_REVIEW 状态守卫：匹配成功，exit code 0。

中间偏差：

1. 首轮专项测试为 19/21；一项测试错误地把 `owner_module` 当作 module 原名，另一项快捷值
   文档格式不够直接。未修改产品语义，修正测试判定和文档后通过。
2. 增加默认 gate audit 覆盖后的首轮为 20/21；原因是 audit 内部把已校验主报告复制到临时
   路径，和默认 `mapping.json` 的固定身份校验冲突。保持身份校验不变，改为复用原始报告
   路径后通过。

### 11.4 Formal

- gold：`tests/fixtures/refactor_symbol_graph_parameters`
- actual gate：`/tmp/t060-formal-acceptance-20260728/gate`
- top：`parameter_top`
- seq：5
- public 生成命令：filelist + top + 默认 reports + `--encryption-rate 0.35` +
  `--name-length 16`
- actual report：4 files、19 selected categories、11 permitted cross-module categories、
  31 mapping records、25 modified tokens、6 selected rate entries。
- 正例命令：

  ```sh
  conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
    --gold-filelist tests/fixtures/refactor_symbol_graph_parameters/design.f \
    --gold-root tests/fixtures/refactor_symbol_graph_parameters \
    --gate-filelist /tmp/t060-formal-acceptance-20260728/gate/design.f \
    --gate-root /tmp/t060-formal-acceptance-20260728/gate \
    --top parameter_top --seq 5
  ```

  结果：exit code 0，`formal_equivalence=pass`。
- 负例复制 actual gate，确认 `mapping.json`、`metrics.json` 均保留，只在
  `rtl/child.sv` 的固定 `assign data_o = ` 后增加一个 `~`。
- 负例 strict compile：catalog 0/0、top overlay 0/0。
- 负例执行同一 Formal 命令（gate 改为 `negative`）：exit code 1，包含 `unproven` 和
  `equiv_status -assert`。

### 11.5 边界与 Git

- 按合同未修改 top module 内 `fifo_bus` 的当前保留行为，未修改 graph、policy、rate
  算法或 fixture。
- 未运行 RISC-V-Vector Formal。
- 未执行 `git add`、commit 或 push，未设置 `ACCEPTED`，未创建 T061。
- 最终工作区：

  ```text
  ## main...origin/main [ahead 1]
   M README.md
   M docs/systemverilog_renaming_table.md
   M rtl_obfuscator/restore_vnext.py
   M rtl_obfuscator/rewrite.py
   M tests/test_public_cli.py
   M tests/test_vnext_product_surface.py
  ?? docs/tasks/T060_simplified_rtl_encrypt_workflow.md
  ```

## 12. 主 Agent 验收

主 Agent 必须独立执行第 10 节命令，另用 README 中可复制的最简 project-root 命令确认：

- 只要求 `--project-root`、`--top`、`--output-dir`；
- 自动产生 `mapping.json`、`metrics.json`；
- 自动跨模块一致改名；
- top 对外端口保持；
- rate 参数在 public help 和 README 中可发现；
- decrypt 使用默认 mapping 恢复 byte-identical。

主 Agent独立复跑第 8 节 Formal 后才可设为 `ACCEPTED`。

### 12.1 验收结果

- 验收时间：2026-07-28。
- 用户起始 README 修改已保留并扩展为面向数字 IC 设计工程师的完整使用流程。
- 专项测试：21/21 通过。
- 内部兼容回归：10/10 通过。
- `py_compile`、`git diff --check HEAD`：exit code 0。
- public help：`--map`、`--metrics` 可选，`--encryption-rate` 可见，内部授权参数不显示。
- 主 Agent README project-root 最简命令：
  - 只提供 `--project-root`、`--top`、`--output-dir`；
  - 4 files、81 mapping records、268 modified tokens；
  - 19 selected categories、11 cross-module categories；
  - 子 module `fifo_ctrl` 改名，top 名称和对外 ports 保留；
  - `mapping.json`、`metrics.json` 位于 output-dir，且 metrics 内容一致；
  - decrypt 使用默认 mapping 恢复 4 files byte-identical。
- 主 Agent Formal actual gate：
  `/tmp/t060-main-formal.jG1n6o/gate`，public filelist + top + 默认 reports +
  `--encryption-rate 0.35`，31 mapping records、25 modified tokens。
- Formal 正例：top=`parameter_top`、seq=`5`、exit 0、`formal_equivalence=pass`。
- 固定负例：复制 actual gate 和默认 reports，只增加一个 `~`；catalog/top-overlay 均
  0/0；Formal exit 1，包含 `unproven` 和 `equiv_status -assert`。
- 未运行 RISC-V-Vector Formal，符合合同边界。
- 验收结论：`ACCEPTED`。

# T019：多文件项目组合回归与 `all` / 显式 ABI 类别边界

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T018 已达到 `ACCEPTED`

## 1. 单一目标

在不新增重命名类别的前提下，完成当前多文件 project pipeline 的组合回归，冻结并验证：

1. `--category all` 只展开 13 个安全 category；
2. `modules`、`ports`、`interfaces`、`interface_instances`、`interface_ports` 和 `modports`
   必须显式指定；
3. `--category all` 可以和显式 ABI category 组合使用；
4. 每个 project 都能完成 encrypt、mapping/metrics、decrypt、前端检查和 Yosys formal；
5. 已验收的 T015—T018 fixture 在同一回归任务中保持行为不变。

本任务是 project-level 集成回归，不实现 `type_parameters`，不新增 category，不修改
任何固定 fixture。

## 2. 固定安全类别和输入矩阵

`all` 必须严格展开为：

```text
signals parameters enum_values genvars functions tasks arguments instances
generate_blocks typedefs struct_types struct_fields union_fields
```

固定回归矩阵如下。所有输入 fixture 只读：

| Case | filelist / source-root | top | categories | 预期摘要 |
| --- | --- | --- | --- | --- |
| T015-all | `tests/fixtures/t015_multi_file` | `t015_top` | `all` | files=2, entries=4, tokens=10 |
| T016-abi | `tests/fixtures/t016_module_port` | `t016_top` | `modules`, `ports` | files=2, entries=3, tokens=8 |
| T017-all | `tests/fixtures/t017_interface` | `t017_top` | `all` | files=3, entries=1, tokens=1；唯一 category 为 `instances` |
| T017-interface | `tests/fixtures/t017_interface` | `t017_top` | `interfaces` | files=3, entries=1, tokens=3 |
| T018-combined | `tests/fixtures/t018_interface_member` | `t018_top` | `all`, `interface_instances`, `interface_ports`, `modports` | files=3, entries=9, tokens=24 |

T017-all 的 1 个 entry 必须是普通 module instance `u_child`；不得出现
`interfaces` entry，且 gate 中 `t017_bus_if` interface definition/type references 保持不变。

T018-combined 的 9 个 entry category 计数必须为：

```text
instances            = 1
interface_instances  = 1
interface_ports      = 5
modports             = 2
```

其中 `interface_ports` 的 `clk`、`rst_n` named connection 左侧仍必须分别收集
`top.sv:[167,170)` 和 `top.sv:[186,191)`；右侧 top ports 不得改写。

## 3. 固定输出目录

每个 case 使用独立目录：

```text
/tmp/rtl_obfuscation_t019/t015_all/
/tmp/rtl_obfuscation_t019/t016_abi/
/tmp/rtl_obfuscation_t019/t017_all/
/tmp/rtl_obfuscation_t019/t017_interface/
/tmp/rtl_obfuscation_t019/t018_combined/
```

每个目录必须包含输入 filelist 的镜像、所有 gate `.sv` 文件、`mapping.json` 和
`metrics.json`。mapping 必须为 v2，`files` 使用相对 source-root 的规范路径，`top`
保持不变。

## 4. 统一输出约束

每个 case 的 stdout 必须精确匹配第 2 节摘要。每个 mapping entry 必须满足：

- declaration/reference range 的 source bytes 等于 `original_name`；
- entry 按 `(declaration.file, declaration.start, category)` 稳定排序；
- 不出现该 case 未请求的 ABI category；
- 所有 gate 文件中 mapping 描述的 occurrence 均被替换；
- decrypt 后所有文件与 gold 逐字节一致。

每个 case 的 metrics 必须满足：

```text
symbols.coverage = 1.0
occurrences.coverage = 1.0
plaintext_leakage_rate = 0.0
effective_coverage = 1.0
```

`affected_lines` 记录实际值，不设置虚构的固定值。

## 5. 固定 CLI 验收命令

所有命令从仓库根目录运行，并通过 `conda run -n rtl_obfuscation` 执行。

### 5.1 Encrypt

每个 case 使用同一命令模板：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist <fixture>/design.f \
  --source-root <fixture> \
  --output-dir /tmp/rtl_obfuscation_t019/<case>/gate \
  --map /tmp/rtl_obfuscation_t019/<case>/mapping.json \
  --metrics /tmp/rtl_obfuscation_t019/<case>/metrics.json \
  --top <top> \
  --category <category> [--category <category> ...] \
  --name-length 8
```

实际执行参数必须分别对应第 2 节矩阵，不得用同一 fixture 冒充全部 case。

### 5.2 Decrypt and byte round-trip

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/rtl_obfuscation_t019/<case>/gate \
  --source-root <fixture> \
  --map /tmp/rtl_obfuscation_t019/<case>/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t019/<case>/restored
```

对每个 mapping file 执行逐文件 `cmp -s`。T017-all 的 gate 仍可包含普通
`u_child` 的重命名，但 interface definition/type 名必须保持 gold 文本。

### 5.3 Frontend checks

- PySlang 对每个 case 的全部 gate 文件建立一个 Compilation，error 数必须为 0；
- Verible 对每个 gate `.sv` 文件退出码必须为 0；
- Icarus 对 T015/T016 case 必须通过；T017/T018 的 ANSI-style interface port
  已知限制允许 gold/gate 均退出码 2，但必须记录实际 stderr，不能把单侧失败当作通过。

### 5.4 Formal

五个 case 都必须分别运行多文件 formal：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist <fixture>/design.f \
  --gold-root <fixture> \
  --gate-filelist design.f \
  --gate-root /tmp/rtl_obfuscation_t019/<case>/gate \
  --top <top>
```

每次退出码必须为 0，stdout JSON 必须包含 `"formal_equivalence": "pass"`、
`"seq": 5` 和对应 top。任何一个 case formal 失败都不得申请验收。

## 6. Regression test

新增 `tests/test_project_regression.py`，使用黑盒 subprocess 覆盖第 2 节五个 case，
至少断言：摘要、mapping category 计数、source ranges、metrics、decrypt byte round-trip
和 `all` 不隐式包含 ABI category。测试不得修改 fixture，不得依赖随机名称的具体值。

完整回归命令：

```sh
conda run -n rtl_obfuscation python -m unittest discover -s tests -v
```

新增测试和既有测试必须全部通过；实际测试数量写入执行记录。

## 7. 本任务明确不包含

- `type_parameters`；T006 继续保持 `DRAFT`；
- 新增任何重命名 category；
- `modport_ports` 独立 entry；
- virtual interface、clocking block、DPI、bind、package/class scope；
- 修改 fixture、formal 脚本、mapping schema 或单文件 mapping v1；
- include/define/library/嵌套 filelist 自动发现；
- 更新规划文档、交接文档或支持矩阵；这些由主 Agent在验收后维护；
- commit、push、amend、rebase 或 force-push。

## 8. 允许修改的文件

```text
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
tests/test_project_regression.py
docs/tasks/T019_project_regression.md
```

`tests/fixtures/t015_multi_file/`、`tests/fixtures/t016_module_port/`、
`tests/fixtures/t017_interface/` 和 `tests/fixtures/t018_interface_member/` 是主 Agent
冻结的只读输入，不得修改。

## 9. 子 Agent 文档流程

1. 开始前将状态从 `READY` 改为 `IN_PROGRESS`，填写执行记录。
2. 发现矩阵、类别边界或 PySlang API 与本合同不一致时，记录最小复现并停止，不得自行扩大范围。
3. 完成后记录四个 fixture、五组 CLI、五组 formal、前端检查、完整 unittest 的实际命令、输出、退出码和未覆盖边界。
4. formal verification 必须记录五组 gold/gate/top/command/exit_code/JSON。
5. 全部门禁通过后设置为 `READY_FOR_REVIEW`；不得设置 `ACCEPTED`，不得 commit 或 push。

## 10. Formal verification

```text
formal_verification: PENDING
reason: T019 尚未由子 Agent 执行；完成后必须记录五组 project formal PASS 证据。
```

## 11. 执行记录（子 Agent 更新）

- 尚未开始。

## 12. 偏差或阻塞（子 Agent 更新）

- 无。

## 13. 交付证据（子 Agent 更新）

- 尚未交付。

## 14. 主 Agent 验收结果

- 尚未验收。

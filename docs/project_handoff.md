# RTL obfuscation 项目交接入口

本文记录新主 Agent 接手时必须保持的当前目标、真实状态和恢复步骤。功能范围与
验收规则仍以本文链接的各事实来源为准；本文不替代任务合同。

## 1. 当前暂停点

- 分支：`main`。
- 已验收能力停在 T019。
- T001—T005、T007—T019 状态均为 `ACCEPTED`。
- T006 是暂缓的 `DRAFT`，不得启动。
- T020 任务合同已创建并处于 `READY`，尚未启动；当前没有 `IN_PROGRESS` 或
  `READY_FOR_REVIEW` 任务。
- 新 Agent 接手后不得直接编辑实现；先完成第 7 节的恢复检查，再由主 Agent/子 Agent
  按唯一的 T020 合同继续工作。

## 2. 不变目标

- 只处理 SystemVerilog `.sv`。
- 使用 PySlang semantic AST 判断符号身份和引用绑定，不做字符串全局替换。
- 新名称由显式 `--name-length` 控制，长度至少为 4；示例统一使用 8。
- 使用 `secrets` 生成合法且不与现有标识符、关键字或本次新名称冲突的名字。
- 单文件 mapping 使用 schema v1，并能将 gate 恢复为与 gold 字节完全一致的文件。
- rewritten RTL 必须通过 PySlang、Verible、Icarus 和 Yosys formal。
- 不引入当前任务不需要的兼容层、fallback、框架或额外配置。

## 3. 环境和真实测试入口

所有项目命令通过 Conda 环境 `rtl_obfuscation` 执行：

```sh
conda run -n rtl_obfuscation <command>
```

已核对版本：Python 3.12.13、PySlang 11.0.0、Pyverilog 1.3.0、Yosys
0.53、Icarus Verilog 12.0、Verible v0.0-3946-g851d3ff4。当前环境没有
`pytest`；完整回归使用：

```sh
conda run -n rtl_obfuscation python -m unittest discover -s tests -v
```

Pyverilog 只保留为已安装工具。当前产品实现以 PySlang 为语义和 source range
事实来源。

## 4. 当前已支持能力

单文件 rewrite 支持十三个安全 category：

```text
signals parameters enum_values genvars functions tasks arguments instances
generate_blocks typedefs struct_types struct_fields union_fields
```

`rewrite encrypt --category all` 是一次解析、一次全局分配名称、一次应用全部 edits
的直接输出模式，不是按 category 串联中间 RTL。单 category 仅作为 debug 入口。

综合样例 `rtl_samples/11_supported_obfuscation.sv` 的固定结果为 23 个 mapping
entries、63 个 modified tokens；metrics 为 41/61 个有效代码行、23/23 个符号、
63/63 个 occurrences、原名残留率 0、有效覆盖率 1。该样例覆盖九类；
`instances` 由 `rtl_samples/06_module_instance.sv` 单独验收。

T012 的 `instances` 和 `generate_blocks` 目前只支持无层次引用的 declaration-only
边界，mapping 中允许 `references=[]`。这不代表完整层次路径已支持。

T013 的 `typedefs` 和 `struct_types` 支持普通 typedef 名和 typedef struct/union
类型名的声明及类型引用（通过 `declaredType.typeSyntax.sourceRange` 收集）。
不支持 struct_fields、union_fields、package/class scope、port 类型引用或 cast 表达式。

T014 的 `struct_fields` 和 `union_fields` 支持 struct/union 内部字段名的声明及
引用（通过 `structType.field` 收集）。不支持 packed struct、tagged union 或
package/class scope。

T015 建立多文件基础设施：filelist 驱动的 Compilation、per-file edits、mapping v2
（含 `files` 和 `top` 字段）、project-level formal equivalence。

T016 在多文件基础上实现 `modules` 和 `ports` 端到端改写。module 定义名、port
声明和 port body 内引用全部收集。mapping v2 增加 `top` 字段以支持 decrypt-project
排除 top module。

T017 实现多文件 `interfaces` category：interface 定义名及其 type 引用（instance
type 和 InterfacePort header）。`interfaces` 不加入 `all` 的展开集合。

T018 实现多文件 `interface_instances`、`interface_ports` 和 `modports`。其中
interface instance named connection 左侧归属 `interface_ports`；`modport_ports`
不生成独立 entry。

当前多文件 project fixture 已全部通过对应任务验收：T015、T016、T017、T018。

## 5. 仍未实现的类别

```text
type_parameters
```

多文件 Compilation、per-file edits、mapping v2 和 project formal 已在 T015 完成。
T016 已实现非 top module 和 child port 端到端改写；T017 已实现 interface 定义名；
T018 已实现 interface instance/member/modport 端到端改写。`modport_ports` 按设计归入
`interface_ports`，不是遗漏类别。

T019 已验证现有 category 的 project-level 组合、`all` 的安全集合和显式 ABI category
边界，不新增 category。当前实现的 `all` 已排除 `modules`、`ports`、`interfaces`、
`interface_instances`、`interface_ports` 和 `modports`。

## 6. 强制角色和 Git 流程

主 Agent 负责范围、fixture、输入输出、边界和黑盒验收；子 Agent 只实现唯一活动
任务。状态固定流转为：

```text
DRAFT -> READY -> IN_PROGRESS -> READY_FOR_REVIEW -> ACCEPTED
```

子 Agent 不得设置 `ACCEPTED`、commit 或 push。主 Agent 独立重跑任务合同中的
全部命令和 Yosys formal，验收通过后才执行：

```sh
git add .
git commit -m "[TYPE] concise description"
git push
```

不得在失败或未验收状态提交，不得自行 amend、rebase、force-push 或改写历史。

## 7. 新主 Agent 的恢复检查

从仓库根目录依次执行：

```sh
git status --short --branch
conda run -n rtl_obfuscation python -m unittest discover -s tests -v
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input rtl_samples/11_supported_obfuscation.sv \
  --output /tmp/rtl_obfuscation_handoff/gate.sv \
  --map /tmp/rtl_obfuscation_handoff/mapping.json \
  --metrics /tmp/rtl_obfuscation_handoff/metrics.json \
  --category all \
  --name-length 8
conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("/tmp/rtl_obfuscation_handoff/gate.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'
conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv /tmp/rtl_obfuscation_handoff/gate.sv
conda run -n rtl_obfuscation iverilog -g2012 -t null \
  -s sample11_supported_obfuscation \
  /tmp/rtl_obfuscation_handoff/gate.sv
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold rtl_samples/11_supported_obfuscation.sv \
  --gate /tmp/rtl_obfuscation_handoff/gate.sv \
  --top sample11_supported_obfuscation
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input /tmp/rtl_obfuscation_handoff/gate.sv \
  --output /tmp/rtl_obfuscation_handoff/restored.sv \
  --map /tmp/rtl_obfuscation_handoff/mapping.json
cmp -s rtl_samples/11_supported_obfuscation.sv \
  /tmp/rtl_obfuscation_handoff/restored.sv
```

预期：25 tests 全部通过；encrypt/decrypt 均报告 `23/63`；三个前端检查退出码
均为 0；formal JSON 为 `formal_equivalence=pass`；`cmp` 退出码为 0。

## 8. 当前下一任务

T020 [example FIFO/per-file mapping](tasks/T020_example_fifo_per_file_mapping.md) 已冻结为
`READY`，只允许子 Agent 实现四文件 FIFO 样例的 per-file mapping 输出和既有 FIFO
array source-range 边界修复。T019 已由主 Agent 独立验收：

- 五组 project 组合回归；
- `all` 与显式 ABI category 边界；
- 五组 decrypt、前端检查和 Yosys formal；
- 完整回归共 25 tests。

T006 `type_parameters` 继续保持 `DRAFT`。当前 Yosys 0.53 无法解析
`tests/fixtures/t006_type_parameter.sv` 中的 `parameter type`，不得通过跳过 formal
的方式实现它。

## 9. 事实来源

- `AGENTS.md`：环境、角色、任务和 Git 强制规则。
- `docs/systemverilog_renaming_table.md`：唯一类别范围。
- `docs/renaming_implementation_plan.md`：架构、边界、指标和任务顺序。
- `docs/formal_verification.md`：Yosys 强制流程。
- `docs/tasks/README.md`：任务状态流程。
- `docs/current_supported_features.md`：已经验收的黑盒能力和演示命令。
- `docs/multifile_interface_port_struct_design.md`：后续多文件和类型/interface 设计。
- `docs/tasks/TNNN_*.md`：每个历史任务的合同和验收证据。

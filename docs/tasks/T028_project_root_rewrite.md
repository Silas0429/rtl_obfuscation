# T028：`project-root + top` 五组对象加密闭环

- 状态：`READY`
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T027 `ACCEPTED`
- 起始提交：`d343e26`
- 路线图：[`docs/project_root_top_roadmap.md`](../project_root_top_roadmap.md)
- Formal verification：必须 `PASS`

## 1. 单一目标

基于 T027 已验收的 `project-root + top` 发现、依赖闭包、严格 compilation、AST inventory 和
source ranges，一次交付下面五个用户概念组的工程级改写闭环：

```text
signals
ports
instances
struct
interface
```

本任务必须在同一张合同中完成：

1. `encrypt-project --project-root`；
2. 五组对象单独选择和组合选择；
3. mapping v3、compile context、closure manifest 和 preserved 清单；
4. 只输出 top 闭包并保持同文件不可达 module 不变；
5. gate 使用原编译上下文重新执行 `inspect-project` 严格编译；
6. metrics 和 per-file mapping；
7. mapping v3 驱动的 `decrypt-project` 字节恢复；
8. project-root 五组 debug matrix；
9. `rtl_samples/example_fifo` 的 project-root 改写和 Yosys formal 正负例；
10. 原 filelist/mapping v2 工作流完全回归兼容。

T028 不改写 parameter，不改 top module 或 top ports，不实现 RISC-V-Vector 的 synthesis/formal
view。RISC-V-Vector 真实工程改写和 assertion 处理属于 T029。

## 2. 子 Agent 角色

子 Agent 是实现者和自测者，不是需求制定者、fixture 维护者或最终验收者。

子 Agent 必须：

- 完整阅读 `AGENTS.md`、`docs/tasks/README.md`、T027 合同、本合同、路线图、
  `docs/formal_verification.md` 和 `docs/systemverilog_renaming_table.md`；
- 确认 T028 是唯一 `READY` 任务，然后先把本文件状态改为 `IN_PROGRESS`；
- 在执行记录中写明开始时间、HEAD、首条命令和当前工作区状态；
- 只修改第 18 节允许文件；
- 按第 15 节阶段顺序实现，每个阶段门禁失败时停止后续阶段；
- 使用固定 T027 fixtures 和固定 FIFO，不得修改输入来适配实现；
- 对每个产生重写 RTL 的正式验收运行 PySlang gate 检查、解密和指定 FIFO formal；
- 记录所有命令、退出码、JSON、hash 和 formal 结果；
- 全部门禁通过后只设置 `READY_FOR_REVIEW`；
- 不得设置 `ACCEPTED`，不得 commit、push 或创建 T029。

主 Agent负责独立重跑黑盒门禁、解释合同、同步用户文档、设置 `ACCEPTED` 和 Git 交付。

## 3. 已知起点和本任务授权修正

T027 对固定 integration fixture 的 32/107 oracle 已验收，不得改变。T028 准备阶段发现：

- 当前 `inspect-project` 对 `rtl_samples/example_fifo` 报告 49 entries / 193 occurrences；
- 已验收的 legacy collector 对本任务五组实际 category 报告 50/195；
- 差异来自 project inventory 未保留 module-scoped union typedef `fifo_view_t`，并把部分
  module-scoped aggregate scope 误规范为 `$unit`；
- `struct_types` 的既有产品语义包含 typedef struct/union 类型名，而 `struct` 用户组虽不启用
  `union_fields`，仍必须包含 `fifo_view_t` 这个类型名。

本任务明确授权最小修正：

- compilation-unit aggregate 继续使用 T027 的 `$unit` / `$unit::<type>` scope；
- module-scoped struct/union type 和 struct field 必须保留 module semantic scope；
- FIFO project inventory 修正为 50/195，并与 legacy mapping 的 category/name/ranges 一致；
- 不得借此扩展到 package/class scope、union_fields、tagged union 或其他未来类别。

该修正必须增加 T028 回归，不能修改 T027 integration 的 32/107 固定预期。

## 4. 用户可见 CLI 合同

### 4.1 project-root 加密

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root <rtl-project> \
  --top <top-module> \
  --output-dir <gate-dir> \
  --map <mapping-v3.json> \
  --metrics <metrics.json> \
  [--file-map-dir <directory>] \
  [--include-dir <directory>]... \
  [--define <NAME-or-NAME=VALUE>]... \
  [--category <group>]... \
  --name-length <integer>
```

project-root mode输入规则：

- `--project-root` 与 legacy `--filelist` 互斥；
- `--source-root` 只属于 legacy filelist mode，与 `--project-root` 同时出现时 argparse 退出 2；
- `--include-dir`、`--define` 只属于 project-root mode；
- project-root mode 的 category choices 只允许
  `signals/ports/instances/struct/interface`；
- 省略 `--category` 时默认启用全部五组；不接受 `all`、`parameters` 或底层实际 category；
- `--output-dir`、`--debug` 和 `--file-map-dir` 不得等于或位于 project-root 内；
- `--map`、`--metrics` 不得覆盖任何输入 RTL；
- gold 文件不得被原地修改。

legacy mode 保持原命令不变：

```sh
encrypt-project --filelist <design.f> --source-root <root> ...
```

legacy category、debug、mapping v2、per-file mapping、stdout 和错误行为不得改变。

### 4.2 project-root debug

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root <rtl-project> \
  --top <top-module> \
  --debug <debug-dir> \
  --name-length 8
```

debug 从同一 gold 独立运行，固定顺序：

```text
signals
ports
instances
struct
interface
```

每组输出：

```text
<debug>/<group>/gate/
<debug>/<group>/mapping.json
<debug>/<group>/metrics.json
<debug>/<group>/maps/
```

`--debug` 不得与 `--category`、`--output-dir`、`--map`、`--metrics`、`--file-map-dir`
混用。stdout summary 必须为 `mode=project-root`、`category_count=5`，runs 顺序固定。

### 4.3 mapping v3 解密

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir <gate-dir> \
  --map <mapping-v3.json> \
  --output-dir <restored-dir>
```

- mapping v3 不要求 `--source-root`；
- mapping v2 继续要求 `--source-root`，现有行为不变；
- 解密前必须校验 mapping schema、gate manifest、所有 gate files 和 target occurrence；
- hash 或 occurrence 不一致时退出 1，不得写出成功恢复结果；
- v3 entries 为空时仍复制全部 closure files 并成功返回 0/0 summary。

## 5. category 展开和保护规则

固定展开：

```text
signals   -> signals
ports     -> ports
instances -> instances
struct    -> struct_types, struct_fields
interface -> interfaces, interface_instances, interface_ports, modports
```

mapping 中只写右侧实际 category。组合选择去重，`selected_groups` 和
`selected_categories` 使用上面的固定规范顺序，不受用户参数顺序影响。

始终禁止进入 mapping entries：

- top module；
- top 普通 ports；
- top ABI interface/struct 闭包；
- parameter/localparam；
- macro-generated identifier；
- top 闭包外对象；
- 同文件中不可达 module 的对象。

被选组中的 top port、top ABI 和宏生成对象必须进入 mapping v3 `preserved` 并带 T027 固定
reason；未被选择的 category 不需要复制到 preserved。

## 6. project analysis 复用要求

- T028 必须直接复用 T027 的 discovery、dependency closure、compile order、selected top traversal
  和 inventory；不得重新写第二套 project resolver。
- `project.py` 应提供不强制写 report 文件的可复用 analysis API；`inspect-project` 的 schema、
  stdout、退出码和确定性保持不变。
- encrypt 开始前必须取得一个 `status=pass` analysis；失败时退出 1，不产生 map/metrics，
  gate 目录必须不存在或为空。
- gate 完成后必须用相同 top/include/define/category context 再分析一次；gate 有 parse/
  semantic error 时加密命令失败，不得交付 mapping。
- compile context、closure 和 source ranges 均来自同一次 gold analysis，不得重新扫描全部项目
  后改变闭包。

## 7. mapping v3 固定 schema

顶层字段必须精确为：

```json
{
  "version": 3,
  "mode": "project-root",
  "name_length": 8,
  "top": "project_top",
  "selected_groups": [],
  "selected_categories": [],
  "files": [],
  "source_files": [],
  "header_files": [],
  "compile_context": {
    "compilation_unit": "single",
    "include_dirs": [],
    "defines": [],
    "compile_order": []
  },
  "closure": {
    "modules": [],
    "interfaces": [],
    "files": []
  },
  "input_manifest_sha256": "",
  "gate_manifest_sha256": "",
  "entries": [],
  "preserved": []
}
```

不得增加绝对 project-root、临时目录、时间戳或随机 run id。

### 7.1 entries

每个 entry 字段固定为：

```json
{
  "category": "signals",
  "scope": "project_top",
  "original_name": "top_signal",
  "renamed_name": "Ab3CdEf4",
  "declaration": {"file":"rtl/top_bundle.sv","start":0,"end":10},
  "references": [],
  "occurrences": 1
}
```

- `(category,scope,original_name,declaration,references,occurrences)` 必须与 gold T027 eligible entry
  精确一致；
- `occurrences=1+len(references)`；
- ranges 使用 gold bytes 坐标；
- entries 按 `(declaration.file,declaration.start,category,scope,original_name)` 排序；
- renamed name 长度等于 `name_length`，首字符 ASCII letter，其余为 ASCII letter/digit/`_`；
- 所有 renamed name 全局唯一，避开 SystemVerilog keyword、gold 现有 identifier、original name
  和同轮其他新名称；
- 同名但不同 semantic symbol 必须得到不同 mapping entry 和不同 renamed name。

### 7.2 preserved

字段与 T027 report preserved entry一致：

```json
{
  "category": "ports",
  "scope": "project_top",
  "name": "top_clk",
  "declaration": {},
  "references": [],
  "occurrences": 1,
  "reason": "top_port"
}
```

preserved 按 T027 固定规则排序。mapping entries 与 preserved 不得包含同一 semantic object。

### 7.3 manifest hash

`files` 是排序后的 closure files。对每个文件生成一行：

```text
<sha256(file-bytes)><two spaces><relative-posix-path><newline>
```

按路径排序连接全部行，对该 UTF-8 manifest bytes 再做 SHA-256：

- gold 结果写 `input_manifest_sha256`；
- gate 结果写 `gate_manifest_sha256`；
- 解密结果必须重新得到 `input_manifest_sha256`；
- hash 固定为 64 位小写十六进制。

## 8. gate 输出和 source edit

- 只复制 `closure.files`，保持 project-root 相对路径；
- `.svh` 即使无 edit 也必须复制；
- 不复制 candidate 但不可达的 RTL；
- 每个 file 的 edits 按 byte offset 降序应用；
- 每次 edit 前核对 gold bytes 等于 original name；
- ranges 不得重复、重叠或越界；
- 未发生 edit 的 closure file 字节不变；
- gate 根目录生成 `design.f`，内容是 `compile_context.compile_order`，每行一个 `.sv` 相对路径，
  顺序和末尾换行固定；
- `design.f` 不计入 mapping `files` 或 manifest；
- gate 重新运行 `inspect-project` 后，reachable module/interface 集合和文件闭包必须与 gold
  相同，eligible 对象变为对应 renamed names，occurrences 不变。

同文件不可达 module 的验证不是简单比较原 offset：其他 module 改名可能移动后续 bytes。
必须提取 `module same_file_unused` 到文件末尾的完整 bytes，与 gold 对应 module bytes 比较，结果
必须完全一致。

## 9. metrics 和 per-file mapping

project-root metrics 继续使用现有 schema：

```json
{
  "affected_lines": {},
  "symbols": {"renamed":0,"eligible":0,"coverage":1.0},
  "occurrences": {"renamed":0,"eligible":0,"coverage":1.0},
  "plaintext_leakage_rate": 0.0,
  "effective_coverage": 1.0
}
```

对非空选择必须满足：

- symbols renamed = eligible = mapping entries；
- occurrences renamed = eligible = mapping occurrence 总数；
- symbol coverage = occurrence coverage = effective coverage = 1.0；
- plaintext leakage rate = 0.0；
- affected line 数可以由实际 edits 计算，不在合同中冻结浮点值。

`--file-map-dir` 复用已验收 per-file schema。所有 per-file occurrence 的集合并集必须等于
global mapping occurrences，且不得包含 header 的空映射占位文件。

## 10. 固定 integration 改写 oracle

gold：

```text
tests/fixtures/t027_project_root/integration
top = project_top
name_length = 8
```

固定 closure：6 files / 5 source files / 1 header；3 reachable modules / 1 interface。

五组精确结果：

| Group | Actual categories | Entries | Tokens |
| --- | --- | ---: | ---: |
| signals | `signals` | 7 | 27 |
| ports | `ports` | 12 | 37 |
| instances | `instances` | 2 | 2 |
| struct | `struct_types,struct_fields` | 3 | 13 |
| interface | `interfaces,interface_instances,interface_ports,modports` | 8 | 28 |
| combined | 全部五组 | 32 | 107 |

combined stdout 必须精确解析为：

```json
{"files":6,"mapping_entries":32,"modified_tokens":107}
```

允许 stdout 使用标准 `json.dumps` 空格，但 key 集合、插入顺序和值必须相同，且只输出一行。

combined mapping 硬约束：

- entries 的非 renamed 字段与 T027 integration eligible oracle 精确相等；
- selected groups/categories 使用第 5 节规范顺序；
- preserved 精确为六个 `project_top` ports，reason=`top_port`；
- 不含 `parameters`、`same_file_secret`、`unused_i/o`、`u_missing`、`value_i`；
- `rtl/unused/unrelated.sv` 不在 files 且不出现在 gate；
- `include/common.svh` 在 files/gate 中且 bytes 不变；
- `same_file_unused` module bytes 不变；
- gate inspect 为 32 eligible symbols / 107 occurrences、0 parse/semantic error；
- gate reachable 拓扑与 gold 相同；
- decrypt stdout 为 6/32/107，六个 restored closure files 与 gold 逐字节相同。

## 11. 固定 top ABI、宏和损坏 gate 验收

### 11.1 top ABI

输入：`tests/fixtures/t027_project_root/top_abi`，top=`abi_top`，默认五组。

- encryption 成功，stdout 为 files=3、entries=0、tokens=0；
- mapping v3 entries 为空；
- preserved 精确为 T027 固定八个对象；
- gate 三个文件与 gold bytes 相同；
- gate inspect 0 error；
- decrypt 成功并逐文件相同。

### 11.2 macro identifier

输入：`tests/fixtures/t027_project_root/macro_identifier`，top=`macro_top`，默认五组。

- encryption 成功，stdout 为 files=2、entries=0、tokens=0；
- `macro_signal` 为 `preserved/macro_expansion`，declaration=null；
- gate 与 gold bytes 相同；
- decrypt 成功并逐文件相同。

### 11.3 manifest 和 occurrence 损坏

在 combined gate 中修改任一 closure file byte 后：

- `decrypt-project` 必须因 gate manifest 不匹配退出 1；
- 不得产生完整 restored tree；
- 删除一个 mapped port/struct field/interface member/instance occurrence 后，gate strict inspect
  必须失败，或 mapping occurrence audit 必须失败；不能仍报告成功。

## 12. 固定 FIFO project-root 和 formal oracle

gold：

```text
project-root = rtl_samples/example_fifo
top          = fifo_top
name_length  = 8
groups       = signals,ports,instances,struct,interface
```

### 12.1 project inventory 和 mapping

- candidate/closure files：4；
- reachable modules：`fifo_ctrl`、`fifo_storage`、`fifo_top`；
- reachable interface：`fifo_if`；
- compile order/design.f：

```text
fifo_if.sv
fifo_storage.sv
fifo_ctrl.sv
fifo_top.sv
```

精确 mapping：

| Actual category | Entries | Tokens |
| --- | ---: | ---: |
| signals | 14 | 67 |
| ports | 17 | 59 |
| instances | 2 | 2 |
| struct_types | 2 | 5 |
| struct_fields | 2 | 4 |
| interfaces | 1 | 2 |
| interface_instances | 1 | 15 |
| interface_ports | 9 | 39 |
| modports | 2 | 2 |
| total | 50 | 195 |

`struct_types` 必须包含 `fifo_entry_t` 和 `fifo_view_t`；struct fields 为 `valid/payload`，不启用
union_fields。project-root mapping 的 category/name/ranges 必须与同组 legacy filelist mapping
一致；scope 使用 T027 project semantic scope，不要求与 legacy schema 的历史字符串完全相同。

FIFO encrypt stdout：

```json
{"files":4,"mapping_entries":50,"modified_tokens":195}
```

metrics 固定硬约束：symbols 50/50、occurrences 195/195、三个 coverage=1.0、leakage=0.0。

### 12.2 formal 正例

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist rtl_samples/example_fifo/design.f \
  --gold-root rtl_samples/example_fifo \
  --gate-filelist /tmp/rtl_obfuscation_t028/fifo/gate/design.f \
  --gate-root /tmp/rtl_obfuscation_t028/fifo/gate \
  --top fifo_top
```

必须退出 0，stdout JSON 包含：

```json
{"formal_equivalence":"pass","seq":5,"top":"fifo_top"}
```

不得使用 gold/gate 同一目录或同一文件冒充改写证明。

### 12.3 formal 功能负例

复制 gate 到独立 negative 目录，从 mapping 找到
`category=signals, original_name=count` 的 renamed name，将 gate `fifo_ctrl.sv` 中唯一：

```text
<renamed> <= <renamed> + 1'b1;
```

改为：

```text
<renamed> <= <renamed> + 2;
```

使用同一 gold/top/seq 运行 formal，必须退出非 0。不得通过修改 formal 脚本、assumption 或 gold
制造结果。

### 12.4 formal 边界记录

T027 integration 的 compilation-unit struct + internal interface 组合会使当前 Yosys 0.53 前端在
`genrtlil.cc` 触发断言，因此不把该 fixture 作为 formal gold。它仍必须通过 PySlang gate
重编译、mapping 和解密。FIFO 覆盖同一五组实际 category 且已具备非空洞 formal 正负基线，
是 T028 唯一正式 formal gold/gate。不得为 integration 运行 identity formal 后宣称通过。

## 13. mapping v2 和 legacy 回归

- 现有单文件 mapping v1、project mapping v2 schema 和 decrypt 行为保持不变；
- legacy `encrypt-project --filelist --source-root` 的现有 19 category/debug/per-file mapping 不变；
- mapping v2 decrypt 仍必须提供 `--source-root`；
- v2 validator 仍拒绝空 entries，v3 validator允许空 entries；
- 现有 FIFO 全类别 79/299、formal 正负例和全部 T001—T027 测试继续通过；
- 不得把 legacy output 自动升级成 v3。

## 14. 错误处理和原子性

- project analysis error：退出 1，不写 mapping/metrics，不留下非空 gate；
- invalid mode/category/path combination：argparse 退出 2；
- mapping schema/hash/range/occurrence error：decrypt 退出 1；
- gate recompile error：encrypt 退出 1，不得把 mapping 当成功交付；
- 所有错误只能写 stderr，stdout 不输出成功 JSON；
- 不得捕获所有异常后静默复制 gold；
- 输入、gate、map、metrics、restored 路径冲突时必须在写文件前拒绝。

## 15. 子 Agent 内部执行方案

### 阶段 A：开始、基线和 API

1. 更新任务为 `IN_PROGRESS` 并记录 HEAD/首条命令。
2. 重跑 T027 16 项测试、integration 32/107、FIFO legacy 50/195 和 FIFO formal 正例。
3. 记录现有 project analysis API、mapping v2 validator/decrypt 和 per-file edit API。
4. 确认固定 fixtures、FIFO、RISC 相对 `d343e26` 无变化。

阶段门禁：全部基线与合同一致；不一致时记录阻塞并停止。

### 阶段 B：project inventory兼容修正和 mapping v3

1. 最小修正 FIFO module-scoped aggregate/union type inventory到 50/195。
2. 提取可复用、不强制写 report 的 project analysis API。
3. 实现五组展开、mapping v3、manifest 和严格 validator。
4. 完成 integration 五组单独和 combined mapping tests。

阶段门禁：T027 integration 保持 32/107；FIFO project inventory 50/195；mapping 非 renamed 字段
与 gold report 精确相等。

### 阶段 C：gate edits、重编译、metrics 和 debug

1. 只复制 closure files并生成 design.f。
2. 应用 ranges、校验 source bytes、输出 metrics/per-file maps。
3. 用相同 context 重跑 gate inspect。
4. 实现五组 debug matrix。

阶段门禁：五组单独、combined、top ABI、macro、同文件不可达、损坏 occurrence 全部通过。

### 阶段 D：mapping v3 decrypt

1. 版本分派 v2/v3 validator。
2. 校验 gate manifest并用 gate semantic inventory定位 renamed occurrences。
3. 逆向 edits、恢复 closure、验证 input manifest。
4. 支持 empty entries，保持 v2 required source-root 行为。

阶段门禁：integration、top ABI、macro 和 FIFO 全部逐文件 byte-identical；损坏 gate 拒绝。

### 阶段 E：formal 和完整交付

1. 运行 FIFO project-root encryption、gate inspect、decrypt。
2. 运行第 12.2 节 formal 正例和第 12.3 节功能负例。
3. 运行第 17 节全部命令和 67 项完整回归。
4. 填写执行记录、偏差、formal 和交付证据。
5. 全部通过后设置 `READY_FOR_REVIEW`，不 commit/push。

## 16. 固定新增测试

新增 `tests/test_project_root_rewrite.py`，正好包含以下 18 个 unittest：

```text
test_integration_signals_group
test_integration_ports_group
test_integration_instances_group
test_integration_struct_group
test_integration_interface_group
test_integration_combined_mapping_v3_exact_oracle
test_integration_gate_reinspect_matches_renamed_inventory
test_integration_decrypt_is_byte_identical
test_unreachable_same_file_module_unchanged_and_unrelated_absent
test_top_abi_zero_entry_round_trip
test_macro_generated_identifier_zero_entry_round_trip
test_mapping_v3_rejects_mutated_gate_manifest
test_project_root_debug_runs_five_groups
test_fifo_project_inventory_matches_legacy_category_semantics
test_fifo_project_root_mapping_exact_oracle
test_fifo_project_root_formal_positive
test_fifo_project_root_formal_functional_negative
test_legacy_mapping_v2_and_cli_mode_validation
```

测试不得修改固定 fixture。临时 gate、negative mutation 和 restored tree 只写
`TemporaryDirectory` 或 `/tmp`。精确 mapping oracle 来自 T027 report和本合同表格，不得在测试
中从 gate 结果反向生成“预期值”。

## 17. 固定验收命令

### 17.1 语法和目标测试

```sh
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project.py \
  rtl_obfuscator/inventory.py \
  rtl_obfuscator/rewrite.py \
  tests/test_project_root_rewrite.py

conda run -n rtl_obfuscation python -m unittest \
  tests.test_project_root_rewrite -v
```

固定结果：`Ran 18 tests`、`OK`。

### 17.2 integration combined encrypt

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root tests/fixtures/t027_project_root/integration \
  --top project_top \
  --output-dir /tmp/rtl_obfuscation_t028/integration/gate \
  --map /tmp/rtl_obfuscation_t028/integration/mapping.json \
  --metrics /tmp/rtl_obfuscation_t028/integration/metrics.json \
  --file-map-dir /tmp/rtl_obfuscation_t028/integration/maps \
  --category signals \
  --category ports \
  --category instances \
  --category struct \
  --category interface \
  --name-length 8
```

必须退出 0、summary 6/32/107，满足第 7—10 节。

### 17.3 gate inspect

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite inspect-project \
  --project-root /tmp/rtl_obfuscation_t028/integration/gate \
  --top project_top \
  --report /tmp/rtl_obfuscation_t028/integration/gate-report.json
```

必须退出 0，0 error、3 modules、1 interface、6 files、32/107 renamed inventory。

### 17.4 integration decrypt

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-project \
  --gate-dir /tmp/rtl_obfuscation_t028/integration/gate \
  --map /tmp/rtl_obfuscation_t028/integration/mapping.json \
  --output-dir /tmp/rtl_obfuscation_t028/integration/restored
```

必须退出 0、summary 6/32/107；独立 hash assertion 检查 mapping `files` 全部 byte-identical。

### 17.5 FIFO encrypt 和 formal

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --project-root rtl_samples/example_fifo \
  --top fifo_top \
  --output-dir /tmp/rtl_obfuscation_t028/fifo/gate \
  --map /tmp/rtl_obfuscation_t028/fifo/mapping.json \
  --metrics /tmp/rtl_obfuscation_t028/fifo/metrics.json \
  --category signals \
  --category ports \
  --category instances \
  --category struct \
  --category interface \
  --name-length 8

conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold-filelist rtl_samples/example_fifo/design.f \
  --gold-root rtl_samples/example_fifo \
  --gate-filelist /tmp/rtl_obfuscation_t028/fifo/gate/design.f \
  --gate-root /tmp/rtl_obfuscation_t028/fifo/gate \
  --top fifo_top
```

固定 encryption 4/50/195，formal 退出 0 且 `formal_equivalence=pass`。功能负例按第 12.3 节
生成并必须退出非 0。

### 17.6 完整回归和输入不可变

```sh
conda run -n rtl_obfuscation python -m unittest discover -s tests -v
git diff --exit-code d343e26 -- tests/fixtures/t027_project_root
git diff --exit-code d343e26 -- rtl_samples/example_fifo
git diff --exit-code d343e26 -- rtl_samples/RISC-V-Vector
git diff --check
git status --short
```

固定完整回归：T027 后 49 项 + T028 新增 18 项 = `Ran 67 tests`、`OK`。

## 18. 允许修改的文件

子 Agent只允许修改：

```text
rtl_obfuscator/project.py
rtl_obfuscator/inventory.py
rtl_obfuscator/rewrite.py
rtl_obfuscator/__init__.py                # 仅公开 API 确有需要时
tests/test_project_root_rewrite.py         # 新文件
docs/tasks/T028_project_root_rewrite.md
```

固定只读输入：

```text
tests/fixtures/t027_project_root/**
rtl_samples/example_fifo/**
rtl_samples/RISC-V-Vector/**
tests/formal/**
scripts/formal_equivalence.py
```

不得修改旧测试、旧 mapping fixture、README、路线图、重命名表、formal 文档、依赖配置或其他
任务合同。对外文档由主 Agent验收后同步。

## 19. 严格行为规范和禁止事项

1. 不得实现或启动 T029。
2. 不得在 project-root mode 开放 parameter、module、union_fields 或 legacy 其他 category。
3. 不得修改 top module、top ports 或 top ABI。
4. 不得编译全部 candidate 后过滤 gate diagnostics；gold/gate 都必须使用 T027 closure。
5. 不得重新实现第二套 resolver、用正则替代 PySlang identity 或文本全局替换 identifier。
6. 不得用 original name 文本搜索代替 mapping range；每次 edit 都必须核对 gold bytes。
7. 不得修改 fixed oracle、fixture、FIFO、RISC 或旧测试来制造通过。
8. 不得把 project mapping v2 改成 v3，或让 v2 decrypt 不再要求 source-root。
9. 不得跳过 gate strict compilation、manifest、decrypt 或 plaintext leakage 门禁。
10. 不得为 integration 运行 gold=gate identity formal 并称为改写等价。
11. 不得修改、弱化或绕过 `equiv_status -assert`。
12. FIFO formal 正例失败时不得设置 `READY_FOR_REVIEW`；功能负例通过同样视为失败。
13. 不得以 PySlang 通过代替 Yosys formal，也不得以 Yosys 通过代替 source range/hash。
14. 不得增加第三方依赖、网络下载工具或调用 Conda base/system EDA 工具。
15. 所有 Python、parser、HDL、test、Yosys 命令必须通过
    `conda run -n rtl_obfuscation`。
16. 不得 commit、push、amend、rebase、reset 或删除用户变更。
17. 不得设置 `ACCEPTED`，不得创建下一任务。
18. 若 schema、CLI、fixture、exact counts 或 formal 输入需要变化，先记录“偏差或阻塞”并停止，
    等待主 Agent 修订合同；不得自行放宽测试。

## 20. 子 Agent 执行记录

开始时填写：

```text
start_time:
starting_head:
first_command:
confirmed_unique_active_task:
baseline_49_tests:
t027_integration_baseline:
fifo_legacy_baseline:
fifo_formal_baseline:
project_api_probe:
```

## 21. 偏差或阻塞

无偏差填写 `None`。有偏差时填写：

```text
observed_behavior:
minimal_reproduction:
contract_conflict:
proposed_minimal_resolution:
status:
```

记录后不得继续扩大范围。

## 22. Formal verification 记录

必须填写：

```text
formal_verification: PASS | FAIL | BLOCKED
gold: rtl_samples/example_fifo + design.f
gate: /tmp/rtl_obfuscation_t028/fifo/gate + design.f
top: fifo_top
command:
exit_code:
result:
negative_gate:
negative_command:
negative_exit_code:
negative_result:
```

只有正例 PASS、功能负例非 0 时才能申请验收。

## 23. READY_FOR_REVIEW 交付证据

完成后填写：

```text
changed_files:
exact_commands:
exit_codes:
integration_group_summaries:
integration_combined_summary:
mapping_v3_schema_result:
manifest_result:
gate_reinspect_result:
same_file_unreachable_result:
top_abi_result:
macro_result:
decrypt_hash_result:
debug_matrix_result:
fifo_inventory_result:
fifo_mapping_result:
fifo_metrics_result:
formal_result:
formal_negative_result:
legacy_v2_result:
target_unittest_result:
full_unittest_result:
fixed_input_diff_result:
git_diff_check:
uncovered_boundaries:
```

## 24. 主 Agent 独立验收

主 Agent 必须独立执行，不以代码阅读或子 Agent 日志代替：

1. 18 项目标 unittest 和 py_compile；
2. integration 五组单独 summary 和 combined 32/107；
3. mapping v3 exact schema、gold ranges、manifest 和全局唯一新名称；
4. gate inspect renamed inventory、拓扑、0 errors；
5. same-file unreachable module bytes、unrelated absent、header bytes；
6. top ABI / macro 0-entry round trip；
7. manifest/occurrence 损坏负例；
8. integration/FIFO decrypt逐文件 SHA-256；
9. FIFO project inventory 和 mapping 50/195，与 legacy category/name/ranges 比较；
10. FIFO formal 正例和功能负例；
11. 完整 67 项 unittest；
12. fixed fixtures/FIFO/RISC 不可变、允许文件和 `git diff --check`。

全部通过后才能设置 `ACCEPTED`。T028 产生重写 RTL，因此 formal 失败、跳过或不支持时均不能
接受，也不能以预算、任务规模或 T029 会处理为由接受部分实现。

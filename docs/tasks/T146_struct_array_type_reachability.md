# T146：固定 struct 数组的类型可达性与真实类型引用

- 状态：`ACCEPTED`
- Main Agent：当前主 Agent；实现：独立子 Agent。
- 起点：`984e8cbd7f85aa1889e160ff2e6db2d190455465`，T145 ACCEPTED、提交并推送；工作区干净。
- 第一轮覆盖率第 3 项；验收类型 rewrite/mapping。此项接受后再创建嵌套字段类型任务。

## 单一目标与冻结设计

沿 PySlang 直接类型关系补齐固定 packed/unpacked struct/union 数组，以及 typedef-array alias 链。
区分活跃性传播和物理类型引用，不能靠 canonical shape 或名称推断身份。

1. 活跃使用的 declaredType 或显式 conversion 为起点，沿 TypeAliasType.targetType.type 与
   PackedArrayType / FixedSizeUnpackedArrayType.elementType 到达物理 aggregate typedef。
   此项到 struct/union 本体即止，不递归 FieldSymbol 类型（留给下一项）。
2. TypeAliasType 声明本身不作为活跃使用根。Main 前置实测发现未使用 scalar alias 目前也会使
   payload_t 误变 eligible；本合同明确授权纠正为 outside_top_closure。未使用 array alias 继续
   outside_top_closure。此规则不缩减 catalog inventory 或真实 occurrence 收集。
3. 泛化 declaredType 入口保持可扩展，不引入变量/端口节点白名单。同步扩展 occurrence/top
   workset 投影，仍每 root 只 visit 一次；T143 同 tuple 成功事实复用与失败重试必须保持。
4. 物理类型引用只剥离外围固定数组，在第一个 TypeAliasType 停止，复用现有 NamedType/token
   逐字节证明。`payload_t[1:0] word` 和 `typedef payload_t array_t[0:1]` 写出的 payload_t
   必须真正记录并改写；`array_t word` 只写出 array_t，不得伪造 payload_t occurrence。
   array_t 不是物理 typedef struct/union，不能新增为 struct 改名记录。
5. 遍历去重只复用本次构建的成功语义事实，保留 wrapper 强引用；不能只按 physical key 跳过
   不同参数特化类型。getter 缺失/异常仍 unknown，不缓存为 False，不以名称或猜测兜底。
6. 完整 CST 分母、source binding、宏/冲突、死源码、top/只读/root、rate、输出 schema 不变。
   不新增动态/关联数组、queue、匿名类型类别，不实现下一项嵌套 aggregate 字段类型传播。

## 固定输入与机器预期

新测试内构建临时 SystemVerilog 输入，不修改既有 RTL fixtures：

- 活跃 `payload_t word[2]`、`payload_t[1:0] word`、多维固定包装及两级 typedef-array alias：
  payload_t/字段从 outside_top_closure 转为 eligible（其他真实保护原因除外）；真实类型 token
  和直接字段使用处完整，all/struct 两种选择均验证字节范围、无重叠及实际 rewrite/strict restore。
- 两个物理不同的同名类型不合并；参数特化和同构不同 typedef 不按 canonical shape 合并。
- 未使用 array/scalar alias 不能激活 payload_t；selected top 外类型仍保留；仅 signals 不增加
  struct 记录。嵌套 named field 的未补齐问题仍保留，不在本任务顺带放行。
- header readonly 和外部 rewrite-root 的真实类型引用继续保留整条记录。
- 外围 elementType / targetType getter 首次失败后恢复、跨 build 重算、未知节点 declaredType
  入口及同/异 top tuple 事实边界得到测试。异常不能制造引用或让缺少 source token 的类型改名。
- 现有 scalar/cast、T144/T145、T142/T143 回归保持。先记录修复前目标失败。

## 冻结实际 gate Formal 样例

```systemverilog
`default_nettype none
module top(input logic [3:0] a, b, output logic [3:0] y);
typedef struct packed {logic [3:0] field;} payload_t;
typedef payload_t array_t[0:1];
array_t word;
assign word[0] = a;
assign word[1] = b;
assign y = word[0] ^ word[1] ^ 4'ha;
endmodule
```

公共 all CLI 生成 gate；payload_t 的声明与 array_t 声明内引用必须实际改名，field 声明改名，
array_t 不新增记录。manifest/edit 逐字节对账，strict compile，公开解密恢复所有输入字节。
原始↔actual gate 运行现有 scripts/formal_equivalence.py（filelist、top=top、seq=5），
exit 0 / JSON pass。独立普通向量 oracle `assign y = a ^ b ^ 4'ha` 分别对原始与实际 gate
运行相同 flow，均 pass；gold/gate 的 Yosys read_verilog -sv -formal -defer、prep -top top
-flatten、check -assert 均通过并保留完整警告日志。固定负例只改实际 gate 的 4'ha→4'hb，
重建准确指向 negative 副本的 filelist；strict compile 成功，Formal 非零、unproven、
equiv_status -assert。打印并保留精确命令/路径/JSON 的 evidence.json。

此 typedef-unpacked-array 样例已通过独立 frontend oracle 探针。直接/packed struct 数组等
当前 Yosys 会丢失维度，不能用那些双方同错的结果声称 Formal pass；它们只记录 PySlang
range、strict compile、恢复验证。不得把目标数组改成 scalar 或无关 proof cone。

## 允许文件

- `rtl_obfuscator/rename_index.py`：以上类型遍历、workset 投影和真实引用局部实现。
- `tests/test_t146_struct_array_type_reachability.py`：新目标测试/临时样例/机器证据。
- `docs/systemverilog_renaming_table.md`：固定数组/未使用 alias 的支持边界。
- 本合同：状态/执行记录/偏差，不自行改变冻结目标和白名单。

不修改 Mapping/Rewrite/SourceCatalog/SourceSet/Formal 工具，不修改既有 tests/fixtures。
必读 AGENTS.md、docs/tasks/README.md、refactor_subagent_protocol.md、renaming table、
project_structure.md、formal_verification.md；按 rtl-review-ready-task skill 执行。

## 唯一 baseline 与五条验收

起步核对 HEAD/status 并更新 IN_PROGRESS；唯一 baseline：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t143_workset_fact_reuse tests.test_t115_name_completeness -v
```

冻结验收：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t146_struct_array_type_reachability -v
conda run -n rtl_obfuscation python -m unittest tests.test_t144_port_macro_provenance tests.test_t145_modport_member_references tests.test_t108_pyslang_rename_index tests.test_t115_name_completeness tests.test_t142_pending_name_proofs tests.test_t143_workset_fact_reuse -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py tests/test_t146_struct_array_type_reachability.py
git diff --check HEAD
conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T146_struct_array_type_reachability.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t146_ready_for_review=pass")'
```

子 Agent 自修范围内失败；边界差异记录后提交 Main，不扩大范围。只到 READY_FOR_REVIEW，
不得 commit/push/ACCEPTED/新建任务；不 blanket/RISC/历史大型验收。Main 独立复验含实际 gate
Formal，接受后提交推送。

## 子 Agent 执行记录

2026-09-20 开始。已核对 HEAD 为 `984e8cbd7f85aa1889e160ff2e6db2d190455465`；
`main...origin/main`，唯一未提交文件为 Main 新建的本合同，无已有实现修改。
已阅读必读规范及 rtl-review-ready-task 技能；只修改四个允许文件，不提交或推送。
首条验收命令为下述唯一 baseline；先添加目标失败证据，再最小实现。

### 实现与范围

- `rtl_obfuscator/rename_index.py`：现有两次有序投影接纳 fixed-array declared type，
  同 tuple 成功读取事实继续复用、缺失/异常继续重试；类型声明不作为 top 活跃根。
  活跃使用沿 alias target / fixed-array element 传播，到 aggregate 本体即止；真实引用仅剥离
  外围数组并在首个 alias 停止。每条遍历以 wrapper identity 和强引用阻止循环，不新增跨节点
  负结果缓存，也不按 physical key 或 canonical shape 省略不同特化。没有新增 root.visit。
- `tests/test_t146_struct_array_type_reachability.py`：11 项测试，包括 fixed packed/unpacked、
  多维、union、两级 alias 的 all/struct 实际 roundtrip、参数特化与同名物理定义隔离、
  top/category/nested 边界、只读/root、未知节点和 getter 重试、源码缺失保留，以及实际 gate Formal。
  特别验证 scalar 活跃根成功但数组 elementType 失败时，payload_t 仍精确报告
  `incomplete_name_coverage`，而不是被 outside_top_closure 掩盖。
- `docs/systemverilog_renaming_table.md`：记录固定数组与未使用 alias 的支持边界。
- 本合同：状态及机器证据。未修改白名单外文件，未 commit/push。

### 命令与结果

唯一 baseline `conda run -n rtl_obfuscation python -m unittest tests.test_t143_workset_fact_reuse tests.test_t115_name_completeness -v`：
exit 0，23 tests / 0.731s / OK。

修复前新增目标测试：同一目标 unittest 命令 exit 1，两个方法共 9 个失败子例；
四种活跃数组 × all/struct 均为 `outside_top_closure`，未使用 scalar alias 原错误为 eligible；
未使用 array alias 原保留通过。实现后全部通过。

| 冻结验收 | 实际结果 |
| --- | --- |
| 目标 unittest 模块 | exit 0，11 tests / 0.547s / OK；`/tmp/t146-sub-target.log` |
| 六模块回归命令 | exit 0，55 tests / 2.747s / OK；`/tmp/t146-sub-regression.log` |
| py_compile 两个允许 Python 文件 | exit 0 |
| `git diff --check HEAD` | exit 0，无输出 |
| 精确 READY_FOR_REVIEW 守卫 | exit 0，`t146_ready_for_review=pass` |

### Actual gate Formal

`formal_verification: PASS`。唯一证据根为
`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t146-evidence-wv0_xmr1`；
下列命令使用该根下 gold/gate/negative/oracle 的真实文件。
`evidence.json` 保留所有精确命令数组、退出码、JSON、CLI、strict compile、manifest、
restore 和完整 frontend 日志路径。内部测试由 Conda Python 调用同一 `sys.executable`。

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t146-evidence-wv0_xmr1/gold/design.f --gold-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t146-evidence-wv0_xmr1/gold --gate-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t146-evidence-wv0_xmr1/gate/design.f --gate-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t146-evidence-wv0_xmr1/gate --top top --seq 5
```

exit 0，JSON：

```json
{"formal_equivalence":"pass","gate":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t146-evidence-wv0_xmr1/gate","gold":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t146-evidence-wv0_xmr1/gold","seq":5,"top":"top"}
```

all CLI actual gate 的 payload_t 声明、array_t typedef 中的 payload_t 引用和 field 声明确实改名；
array_t 不新增记录。全部物理 edit 与原字节逐一对账，严格编译和公开解密恢复通过。
普通向量 oracle 分别比较 gold 和 actual gate：两次 exit 0 / JSON pass；gold/gate
`read_verilog -sv -formal -defer; prep -top top -flatten; check -assert` 两次 exit 0，本样例无警告。

固定负例复制 actual gate，只把唯一 `4'ha` 改为 `4'hb`；design.f 重建后经 SourceSet 断言仅指向
negative/design.sv。严格编译 catalog/top-overlay 的 parse_errors、semantic_errors 全为 0。
Formal 使用同一 gold，将上述命令 gate-filelist/root 改为该根下 negative：exit 1，输出同时含
`unproven` 与 `equiv_status -assert`；完整命令及输出存于 evidence.json / negative.stdout / negative.stderr。

### 偏差与未覆盖边界

没有扩大合同。最初测试样例误用了 SV 保留字 `small`，改为普通标识符后编译通过；
源码 range 返回 None 的负例按现有更具体的 `source_binding_incomplete` 断言，getter 失败遗漏
token 的独立负例仍要求 `incomplete_name_coverage`。这两者均未放宽产品保护。
直接、packed、多维及 union 数组只报告 PySlang range/strict compile/restore 证据；
Formal 只覆盖冻结的 typedef-unpacked struct-array 样例，不声称当前 Yosys 支持其他数组形态。
动态/关联数组、queue、嵌套 aggregate 字段类型传播不在本项；无服务器覆盖率或性能结论。

## 主 Agent 独立验收

2026-09-20 Main 独立执行冻结五条：先核实 READY_FOR_REVIEW，目标 11 tests / 0.576s、
指定回归 55 tests / 2.755s、py_compile、git diff --check HEAD 均 exit 0。
日志 `/tmp/t146-main-target.log`、`/tmp/t146-main-regression.log`。

Main 重新生成公共 all CLI actual gate，证据根为
`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t146-evidence-mb3rjzzy`。
`evidence.json` 记录独立本次全部 argv、gold/gate/top/seq 与 JSON；payload_t 声明和真实
alias 引用、field 声明确实改名，manifest/edit 字节对账、strict compile 和公开解密恢复通过。
Main actual gate Formal、oracle↔gold、oracle↔gate 均 exit 0 / pass；gold/gate frontend
check -assert 均通过且无警告；准确指向 negative 副本的 4'ha→4'hb 负例 strict compile 成功，
Formal exit 1，报告 unproven / equiv_status -assert。

Main 与独立只读 reviewer 均未发现阻塞项。固定数组身份、真实 token 边界、unknown/retry 和
只读/root/完整 CST 保护保持；未使用 scalar alias 的收紧为合同明确授权的活跃性修正。
本次无服务器覆盖率或性能结论，其他数组形态仅报告合同所述 PySlang 证据。
据此 ACCEPTED，按项目 Git 流程提交并推送；提交结果见主 Agent 交付记录。

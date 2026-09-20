# T144：端口连接标签的真实宏来源

- 状态：`ACCEPTED`
- Main Agent：当前任务主 Agent；实现：独立子 Agent。
- 起点：`d8ea7a385b0046d76414a34689d58fd5f0674715`，main 工作区干净；2026-09-20 fetch 后与 origin/main 一致。
- 前置：T143 ACCEPTED。第一轮覆盖率修复第 1 项；本项接受后才创建下一合同。
- 验收类型：rewrite/mapping，按 `docs/development/process/refactor_subagent_protocol.md`。

## 单一目标

named port connection 标签保留由 PySlang SourceManager 证明的普通/宏正文/宏实参来源，
让真实宏共享冲突走现有 macro_origin_conflict 规则，避免错误触发 ports 整类保留。
同一宏物理 token 对应不同实际端口时仍不得改写；无关且完整绑定的端口应继续接受其余安全检查。

## 固定输入与预期行为

测试使用新目标测试模块内固定 SystemVerilog 字符串及临时文件，不修改既有 RTL fixture。

1. 两个不同 cell 各有 Q/CLK/CEN；同一个宏正文 `.Q(O), .CLK(clk), .CEN(en)` 分别实例化二者。
   cell 与 wrapper 放在 lib/，普通 own_leaf 和 top 放在 own/，rewrite-root=own/。
   top 中显式 named connections 连接 own_leaf 的 own_input/own_output，所有模块功能参与输出。
   预期 6 个 cell 端口仍 macro_origin_conflict/unsupported；own_input/own_output 为 rename；
   selected top 两个端口保持边界；lib/ 字节不变。不得存在该宏引起的 cross_record_range_conflict。
2. 宏只展开到同一物理 cell 的多个实例，且全部授权可写：声明仅一个对象，完整绑定标签可改名，
   physical range 不重复；宏正文和传入 `.PORT(...)` 的实参标签分别断言准确 provenance 与字节。
3. 嵌套宏应依 SourceManager 的真实原始标签位置分类，不能基于名字/路径或整个表达式猜来源。
4. 普通显式 named connection 仍为 semantic_port_connection；普通 `.p` 简写产生的未知跨对象
   共享范围仍沿用原来的跨记录整类保留规则，不能顺便修改冲突传播策略。
5. SourceManager 的来源 getter 缺失/异常不得猜成已解释宏冲突或静默漏掉引用：相关记录保留
   source_binding_incomplete 或整次明确拒绝；精确测试该失败边界。
6. 公共 all CLI 对第 1 项（或包含全部该项结构的固定合并样例）产出实际 gate；必须确认
   own_input/own_output 的真实字节编辑落地、完整 physical manifest/range、strict compile、
   public decrypt 或既有直接 restore 对全部物理输入逐字节相同。
7. 对同一实际 gate 运行项目 Formal 正例；gold/gate 是不同输入且目标端口实际改名。
   固定负例只改变 gate 中唯一的功能表达式（例如 top 输出 XOR 改 OR），保持 strict compile，
   Formal 必须非零且包含 unproven / equiv_status -assert。不得用无关 cone 或 identity 代替。

## 允许文件与禁止范围

- `rtl_obfuscator/rename_index.py`：只修改 named port connection 的来源获取/错误处理及必要局部助手。
- `tests/test_t144_port_macro_provenance.py`：新目标测试；允许临时创建上述 compact RTL 和记录 JSON 证据。
- `docs/systemverilog_renaming_table.md`：补充 named port 标签沿用宏来源规则的精确说明。
- `tests/test_t108_pyslang_rename_index.py`：仅修复 baseline 已存在的 macro interface 断言，
  精确断言 macro_if/value 为 readonly_include_file，if0/if_array 为前缀边界；保留原异常测试。
- `tests/test_t111_record_scope_preserve.py`、`tests/test_t115_name_completeness.py`：仅修复
  固定功能负例复制 gate 后 filelist 仍指向原 gate 的缺陷；将已知单文件负例 filelist 明确绑定
  negative/formal_cone.sv，并断言实际解析文件属于 negative。不得降低负例判据或改 RTL fixture。
- 本合同：子 Agent 仅更新状态、执行记录、偏差与实际证据，不自行修改冻结目标/命令/允许文件。

不修改 `_resolve_range_claims`、Mapping/Rewrite/rate、宏展开语义、top/root/readonly/completeness，
不处理 modport 或 struct 后续任务，不新增类别/依赖/框架；除上述 baseline 验证缺陷外不改已有测试，
不改历史合同。此附带修复仅恢复冻结回归的有效性，不改变其他产品行为。
Sources of truth：AGENTS.md、docs/tasks/README.md、docs/systemverilog_renaming_table.md、
docs/development/project_structure.md、docs/formal_verification.md 及 refactor_subagent_protocol.md。

## 子 Agent 起步与唯一 baseline

阅读上述文档；核对 HEAD/status；将本合同改为 IN_PROGRESS 并记录起点后，先执行：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t111_record_scope_preserve -v
```

随后新增目标测试，先记录修复前与本问题对应的失败，再实现。普通实现/测试失败在合同内自行修正；
实际 API/所需文件超出合同则记录并交主 Agent 决策。子 Agent 不 commit/push/ACCEPTED。

## 冻结验收（五条）

1. 目标模块必须输出机器可读的 actual gate / strict compile / byte restore / Formal 正负证据：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t144_port_macro_provenance -v
```

2. 回归原有宏、多重 claimant、逐记录保留和完整性边界：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t111_record_scope_preserve tests.test_t115_name_completeness -v
```

3. 语法检查：

```sh
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py tests/test_t144_port_macro_provenance.py
```

4. diff：`git diff --check HEAD`

5. 子 Agent 完成后状态守卫：

```sh
conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T144_port_macro_provenance.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t144_ready_for_review=pass")'
```

禁止 blanket discovery、RISC-V-Vector 和历史大型 acceptance driver。

## 子 Agent 执行记录

- 开始：2026-09-20；starting HEAD=`d8ea7a385b0046d76414a34689d58fd5f0674715`。
- 起始工作区：仅主 Agent 新建的本合同未跟踪，为授权输入；其余干净，无用户修改重叠。
- 已阅读 AGENTS、sources of truth、refactor_subagent_protocol 和 rtl-review-ready-task 技能；
  只修改主 Agent 授权的白名单文件，不提交、不推送、不设置 ACCEPTED。
- 首条 baseline：`conda run -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t111_record_scope_preserve -v`；exit 1，23 tests / 2 failures（未改实现时）。
  - T108 `test_macro_backed_interface_declaration_and_invalid_typed_token_are_fail_closed`：既有 preserve exact count 期望 2，实际 4。
  - T111 `test_actual_gate_formal_positive_and_fixed_functional_negative`：正例 pass；既有负例期望非零，实际 exit 0。
- 偏差已提交主 Agent：失败均在冻结白名单之外的历史测试；T111 复制的 `design.f` 含原 gate 的绝对路径，疑似没有验证 mutated 文件。
  主 Agent 已独立核实并扩展三处旧测试白名单；按下方裁定修复，不改变冻结验收命令。
- 目标修复前复现：`conda run -n rtl_obfuscation python -m unittest tests.test_t144_port_macro_provenance -v`，exit 1；
  5 tests / 8 subtest failures / 1 test setup error。正文、实参、嵌套宏标签均误标 semantic_port_connection；
  isMacroArgLoc 故障未保留；own_input/own_output 仍 cross_record_range_conflict。
  setup error 为新测试把 gate 放进 source root，被输出路径保护正确拒绝，将调整测试临时目录层次。
- 变更文件（均在主 Agent 最终白名单内）：`rtl_obfuscator/rename_index.py`、
  `tests/test_t144_port_macro_provenance.py`、`docs/systemverilog_renaming_table.md`、本合同；
  以及三处限定 baseline 修复 `tests/test_t108_pyslang_rename_index.py`、
  `tests/test_t111_record_scope_preserve.py`、`tests/test_t115_name_completeness.py`。
- 实现：named port 标签在物理 range 恢复前，以标签原始 location 调用 `isMacroLoc/isMacroArgLoc`；
  不读取连接表达式来猜来源。来源获取异常转为相关记录 `source_binding_incomplete`；
  原来的范围字节校验、claim、宏冲突规则、未知跨记录整组保留规则未改。
- 冻结验收实际结果：
  1. `conda run -n rtl_obfuscation python -m unittest tests.test_t144_port_macro_provenance -v`：exit 0，5 tests，0.465s；
     含 5 种普通/宏正文/实参/嵌套来源及 6 种 getter 异常/缺失子场景。完整模块首轮通过后，
     为精确覆盖 getter 缺失而加强故障注入，再跑此最终结果。
  2. `conda run -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t111_record_scope_preserve tests.test_t115_name_completeness -v`：exit 0，34 tests，1.293s；
     T111、T115 正例均 exit 0/pass，修复输入指向后的真实功能负例均 exit 1，包含 unproven / equiv_status -assert。
  3. `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py tests/test_t144_port_macro_provenance.py`：exit 0。
  4. `git diff --check HEAD`：exit 0。
  5. 冻结 READY_FOR_REVIEW 状态守卫：exit 0，输出 `t144_ready_for_review=pass`。
- 机器证据：`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/evidence.json`。
  测试输出同一份 `T144_EVIDENCE` JSON；该临时目录保留供主 Agent 独立重跑。
- actual gate：四个物理文件全部进入 manifest，所有映射范围均逐字节核对且无重复/重叠；
  public all CLI 的 strict_compile=true、byte_restore=true；公开 decrypt 的四个文件全部与 gold 相同；
  `lib/cells.sv`、`lib/wrapper.sv` 字节不变。六个 cell 端口均 unsupported/macro_origin_conflict，
  own_input/own_output 实际改名为 `SX_dAHOVzYi6BLX60NAG` / `uXv2FgoNrrUL2euni16D`，
  声明、body 引用、top named connection 标签均已在 gate 验证；top 两端口仍 selected_top_boundary。
- formal_verification：PASS。gold=`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/gold`；
  gate=`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/gate`；top=`top`；seq=5。
  以下命令由目标 unittest 在 Conda 环境内以同一 `sys.executable` 子进程实际执行：

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/gate/original_design.f --gold-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/gold --gate-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/gate/design.f --gate-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/gate --top top --seq 5
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/gold/design.f --gold-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/gold --gate-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/negative/design.f --gate-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/negative --top top --seq 5
```

- 正例 exit 0，JSON：`{"formal_equivalence":"pass","gold":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/gold","gate":"/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-e738wadi/gate","top":"top","seq":5}`。
- 负例仅把 actual gate `own/top.sv` 唯一 XOR 改为 OR；negative filelist 明确指向复制文件，实际
  SourceSet 四条路径均已断言。negative strict compile 四项 errors 都为 0；Formal exit 1，
  `ERROR: Found 1 unproven $equiv cells in 'equiv_status -assert'.`，未证明对象为输出 `result`。
  完整 stdout/stderr 保存在同一证据目录的 `formal-negative.stdout` / `formal-negative.stderr`。
- 剩余边界：不新增宏展开策略，不放行共享 token，不修改 root/top/include/completeness/未知冲突；
  modport、struct 与统一改名属后续任务；服务器收益尚未测量。cleanup_candidates：无。
- review_request：子 Agent 已完成实现与自测，停止在 READY_FOR_REVIEW；未 commit/push/ACCEPTED。

## 主 Agent 独立验收

2026-09-20 baseline 偏差裁定：主 Agent 确认 T108 的 4 条保留来自已生效的 include-only 只读
防火墙（macro_if/value 的物理引用位于 macro_interface.svh），旧断言未同步；只准更新精确原因集。
T111 与 T115 的单文件 negative 复制绝对 design.f 后仍指向未变 gate，必须改正实际输入并保留
strict compile + nonzero/unproven/equiv_status 判据。此处按主 Agent 权限扩展上述三个测试文件白名单，
冻结验收命令不变，禁止通过放宽断言解决。

待执行；必须先核对 READY_FOR_REVIEW，独立复跑上述黑盒命令及其生成的实际 gate Formal，
检查 diff 后才 ACCEPTED、commit、push。服务器真实收益不属于本地已验证结论。


### 主 Agent 验收完成（2026-09-20）

状态守卫通过后独立复跑五条冻结命令：目标 5 tests / 0.432s、回归 34 tests / 1.302s 均 exit 0；
py_compile 与 git diff --check HEAD 均 exit 0。独立只读审查无阻塞：目标功能依赖三个输入，
所有模块参与；原冲突传播/边界/完整性不变。已审阅全部七个白名单文件，历史测试仅修复已裁定的验证缺陷。

本轮 Main 自己生成 actual gate，并在第一条命令中独立调用项目 Formal：

```text
gold: /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/gold
gate: /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/gate
top: top; seq: 5
positive command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/gate/original_design.f --gold-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/gold --gate-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/gate/design.f --gate-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/gate --top top --seq 5
positive exit: 0
positive JSON: {"formal_equivalence": "pass", "gate": "/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/gate", "gold": "/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/gold", "seq": 5, "top": "top"}
negative command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/gold/design.f --gold-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/gold --gate-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/negative/design.f --gate-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/negative --top top --seq 5
negative exit: 1; strict compile pass; unproven / equiv_status -assert
```

目标 own_input/own_output 的声明和标签均真实编辑；六个共享宏 cell 端口仍 unsupported；
四个物理文件 manifest/range 审计、lib 字节不变、公开解密逐字节恢复均通过。
证据：/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t144-evidence-_zwb07zo/evidence.json；原始 Main 日志 /tmp/t144-main-target.log、/tmp/t144-main-regression.log。
本任务 ACCEPTED；实际服务器覆盖率尚未测量。

# T147：嵌套具名 aggregate 类型的活跃性与字段类型引用

- 状态：`ACCEPTED`
- Main Agent：当前主 Agent；实现：独立子 Agent。
- 起点：`7564afe1b29e4e9269dd1b79409edeaa53dd7ba4`，T146 ACCEPTED、提交并推送；工作区干净。
- 第一轮覆盖率第 4 项，也是本轮最后一项；验收类型 rewrite/mapping。

## 单一目标与冻结边界

补齐通过 aggregate 字段类型间接使用的具名 struct/union typedef，同时收集字段声明里实际
写出的类型 token。必须同时证明活跃性和真实改写范围，不能只去掉 outside_top/incomplete 原因。

- 在 T146 的活跃类型关系上，沿真实 aggregate 的 FieldSymbol.declaredType.type 继续到达
  alias/固定数组/aggregate；类型声明自身仍不作为根。支持嵌套具名类型、多层与固定数组组合。
  内联 aggregate 可作为载体到达具名类型，但不为匿名 aggregate 新建改名类别或伪记录。
- 真实字段类型引用必须由该 FieldSymbol 绑定的 alias 决定。PySlang FieldSymbol 的
  declaredType.typeSyntax 可能为 None；仅此时可使用该字段自己的 DeclaratorSyntax.parent
  的 StructUnionMemberSyntax.type（NamedType）提供物理范围，继续复用唯一 token/字节校验。
  getter 抛错、ErrorType、source-less、非 NamedType 或无法证明的范围均不得猜测绑定。
- 物理引用沿用 T146 的规则：只剥固定数组，到首个写出的 alias 停止，不将 alias 的目标名
  伪造为该位置源码。多个 declarator 共享类型 token 只计一个真实 occurrence。
- occurrence 必须包含完整 catalog 的真实字段类型引用（包括只读/root 外），不能只收集 top。
  保持每 semantic root 一次 visit、未知 declaredType 扩展、成功事实复用与未知重试；遍历
  保留 wrapper 强引用，不按名字/canonical shape/仅物理 key 合并不同参数特化。
- 完整 CST 分母、reference attribution、source-binding/冲突、宏、死源码、top/只读/root、
  rate、Mapping/Rewrite 和 schema 不变。不新增动态/关联数组、queue、参数类型或 module 类别。

## 固定输入与目标机器预期

新测试内创建临时 SystemVerilog，不修改既有 RTL fixtures：

1. inner 类型仅经 outer 字段使用、没有独立 inner 变量：inner/outer typedef 及其真实字段
   均 eligible；声明、字段类型 token 和所有直接字段表达式引用完整且 byte verified。
2. 多层嵌套、固定数组字段/数组载体、内联载体、多 declarator、同名不同物理类型/参数特化：
   有直接证据的引用归属正确、不重复、不重叠，all/struct 真实 rewrite/strict compile/restore。
3. 未使用 nested/alias 定义不能激活类型；选中 top 外、readonly header/root 外真实字段类型
   引用继续保留。signals-only 不产生 struct 记录。未支持形态不靠名称 fallback 放行。
4. 缺失/异常 getter 或字段 typeSyntax/parent 的失败路径不伪造 occurrence；至少有一个
   已活跃 inner 类型却故意漏字段引用的负例，必须由 incomplete/source-binding 守卫拦住。
   保持同一次成功语义事实、失败后重试、强引用去重与跨构建重算边界。

## 既有测试的精确授权更新

Main 已保存修复前机器基线 `/tmp/t147-main-baseline.json`。T108=42 records/70 occurrences，
digest `0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f`；
T115=56/125，digest `dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78`。

- T115 原 fixture 仅新增 `design.sv:40` 的 t115_inner_t 范围 [1880,1892) 的真实类型引用。
  原声明 [1757,1769)、变量类型 [2085,2097) 不变；仅该 struct_type 从
  preserved/incomplete_name_coverage 到 eligible/rename。cmd/inner/wide、word_t、其他记录
  和全部身份不变；records=56、occurrences=126，相关 outcome 仅按这一条变化更新。
- `test_t115_name_completeness.py` 的自然缺陷旧预期替换为正常三 token 真改（旧名零次）与
  精确 fault 两条路径：包装 _claim_occurrence 仅截掉 [1880,1892)，不删语义节点、不改
  CST 分母/归属规则/fixture。fault index 仅该类型 incomplete，claim 2/总 token 3，
  unattributed 恰 1；shape2 与字段仍 eligible。fault 保留 gate 发布/恢复/audit clean且
  旧名3次；由此 fault index 强制该记录 rename 但仍漏引用，必须严格编译
  REWRITE_GATE_COMPILE_FAILED 且无输出。正常 CLI 该类型rename，fault mapping仍报告原因。
  更新必要说明/辅助方法，不删除原安全判据、独立字节 oracle、无死源码、四类改名、range、
  strict compile、restore、audit 或既有 Formal/功能负例。
- T128/T129 只更新 T115 occurrences 125→126 与经逐项 diff 核实的新 T115 digest。
  T108 counts/digest 和 T141 全部 mapping digest/34-6-2-42 汇总必须保持，不授权修改T141。
- T146 的 test_top_selection_category_and_nested_field_boundaries 仅将已实现的 nested
  payload_t/field 预期改为 eligible 并断言新增真实 token；unused other_t/other_field 与
  signals-only 等剩余检查不变。其他 T146 测试不改。

## 冻结 actual-gate Formal

```systemverilog
module top(input logic [3:0] a, output logic [3:0] y);
typedef struct packed {logic [3:0] field;} payload_t;
typedef struct packed {payload_t inner;} envelope_t;
envelope_t word;
assign word.inner.field = a;
assign y = word.inner.field ^ 4'ha;
endmodule
```

公共 all CLI 生成 actual gate，明确 payload_t、envelope_t、inner、field 的声明及真实引用
全改且非 identity；不把 nested 结构展开或换成无关 cone。manifest/edit 对账、strict compile、
公开解密逐字节恢复。原始↔actual gate 运行 scripts/formal_equivalence.py（filelist、top=top、
seq=5），exit 0 / JSON pass。普通 vector oracle y=a^4'ha 分别对原始和实际 gate 也须 pass；
gold/gate read_verilog -sv -formal -defer、prep -top top -flatten、check -assert 均成功并
保留完整 frontend 日志。固定负例复制 actual gate 仅改4'ha→4'hb，重建指向副本的filelist，
先 strict compile，Formal 要求非零/unproven/equiv_status -assert。输出精确命令/路径/JSON。
此 compact nested named 样例已由前置 oracle 探针验证，其他新形态仅报告实际已执行的验证范围。

## 允许文件

- `rtl_obfuscator/rename_index.py`：本项类型关系与字段真实引用局部实现。
- `tests/test_t147_nested_aggregate_type_references.py`：新增目标测试/临时样例/证据。
- `tests/test_t115_name_completeness.py`：上文精确授权的正常/fault 安全测试更新。
- `tests/test_t128_rename_index_range_cache.py`、`tests/test_t129_ordered_semantic_workset.py`：仅上述 T115 count/digest。
- `tests/test_t146_struct_array_type_reachability.py`：仅上述 nested 边界测试。
- `docs/systemverilog_renaming_table.md`：更新嵌套字段类型支持边界。
- 本合同：状态/记录/偏差，不自行扩大冻结范围。

不修改既有 RTL fixtures、T141、历史任务、Mapping/Rewrite/SourceCatalog/Formal 工具。
必读项目 AGENTS、tasks README、refactor_subagent_protocol、renaming table、project_structure、
formal_verification；按 rtl-review-ready-task skill 执行。

## 唯一 baseline 与冻结验收

核对 HEAD/status，更新 IN_PROGRESS；唯一 baseline（输出保留原 digest）：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t115_name_completeness tests.test_t128_rename_index_range_cache tests.test_t129_ordered_semantic_workset tests.test_t141_semantic_name_reuse tests.test_t146_struct_array_type_reachability -v
```

先新增修复前失败测试，再实现与更新已授权旧预期。冻结五条：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t147_nested_aggregate_type_references -v
conda run -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t115_name_completeness tests.test_t128_rename_index_range_cache tests.test_t129_ordered_semantic_workset tests.test_t141_semantic_name_reuse tests.test_t142_pending_name_proofs tests.test_t143_workset_fact_reuse tests.test_t144_port_macro_provenance tests.test_t145_modport_member_references tests.test_t146_struct_array_type_reachability -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py tests/test_t147_nested_aggregate_type_references.py tests/test_t115_name_completeness.py tests/test_t128_rename_index_range_cache.py tests/test_t129_ordered_semantic_workset.py tests/test_t146_struct_array_type_reachability.py
git diff --check HEAD
conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T147_nested_aggregate_type_references.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t147_ready_for_review=pass")'
```

子 Agent 到 READY_FOR_REVIEW 即止，不 commit/push/ACCEPTED/新任务，不 blanket/RISC/历史大型
验收。范围内普通失败自行修正，API/范围偏差先记录并交Main。Main 独立执行五条及 actual gate
Formal、逐项核对 T108/T115 基线差异，接受后提交推送。

## 子 Agent 执行记录

- 2026-09-20 开始：HEAD=`7564afe1b29e4e9269dd1b79409edeaa53dd7ba4`，main 与 origin/main 同步；仅本合同未跟踪，无其他修改。
- 已读取项目规范、冻结合同与 rtl-review-ready-task 技能；只修改上列八个文件，停止于 READY_FOR_REVIEW。
- 首条核验为 `git status --short --branch` / `git rev-parse HEAD`；接下来运行唯一 baseline 并先建立目标失败。


### 实现与边界记录

- 2026-09-23 从限额中断处恢复，HEAD/原八文件改动保持；未重做 baseline、未扩大范围。
- 唯一 baseline：上列五模块命令，exit 0，43 tests / OK；日志 `/tmp/t147-sub-baseline.log`。
- 修复前目标命令 `conda run -n rtl_obfuscation python -m unittest tests.test_t147_nested_aggregate_type_references -v`
  exit 1，首个 nested 用例在 all/struct 均为 outside_top_closure；日志 `/tmp/t147-sub-before.log`。
- `rename_index.py`：在已有 workset 的 catalog 投影中收集直接类型关系里的 FieldSymbol；
  活跃类型沿 alias、固定数组和 aggregate 字段传播。类型遍历只按持有强引用的 wrapper 身份去重，
  getter 失败不作为已验证负事实保存；不新增 semantic root visit、类别、schema 或放行规则。
  FieldSymbol 仅在成功读取的 typeSyntax 确为 None 时使用其 Declarator.parent 的
  StructUnionMember.type，并继续 NamedType/唯一 token/源码字节验证。getter 失败或范围不明不猜测。
- 新测试覆盖两类 category、多层 named aggregate、packed/unpacked 字段数组、array alias 字段、
  数组/内联载体、共享类型 token、多物理同名类型与参数特化、无活跃用法、selected top、只读与
  root 外真实引用；所有可改正例均做 range、strict compile、restore。source-less/非 NamedType/
  typeSyntax 和 parent getter 失败、强引用去重、成功边复用、未知边重试及跨构建重算有专门断言。
- T115 正常路径断言 [1757,1769)、[1880,1892)、[2085,2097) 全改，gate 旧名零次、audit clean。
  fault 仅截掉中间 `_claim_occurrence`，完整 CST 与语义树保持；仅 inner 类型 incomplete，
  两个 claimed / 三个总 token、恰一个 unattributed，其他记录保持。fault gate 三次旧名、restore/
  audit clean，mapping 唯一 incomplete 记录精确为 SHAPE_ONE/preserve；强制该记录 rename 但漏
  引用时 REWRITE_GATE_COMPILE_FAILED 且无输出。原四类、死源码、字节 oracle、range 和 Formal
  正负例保留。
- 对 `/tmp/t147-main-baseline.json` 的逐项比较保存于 `/tmp/t147-sub-after.json`：T108 42/70
  与 digest 完全不变；T115 56/126，仅第 7 个 inner 类型新增 [1880,1892) semantic_type，
  该记录及 decision 从 preserve/incomplete 到 eligible/rename，struct outcome rename 4→5、
  preserve 1→0、去掉该 issue；旧 [2085,2097) 因排序移到 occurrences[1]，内容未变。
  新 T115 digest `1099de8c3ec0ffa69fc6a082aa65ddda31e76df31e3d95c24e55483fa6f311c1`。
  T128/T129 仅按此更新；T141 文件未改，digest 仍
  `e4bea7aee2502f833053859bf9b34a21adf81a17530aaf5faa18f9ae3b2831da`，34/6/2/42 汇总回归通过。
- T146 仅更新已授权 nested 边界为 eligible 与真实 payload_t token；其余预期不动。
  类型表说明具名 nested 支持、匿名载体与仍保留的动态/关联数组、queue 边界。
- 改动文件正好为冻结允许的八个文件；没有 fixture、T141、Mapping/Rewrite、SourceCatalog 或
  Formal 工具修改。无实现范围偏差；过程中两处测试编辑定位错误已在最终验收前修复。

### 最终五条验收（2026-09-23）

1. 冻结目标 unittest 命令：exit 0，9 tests / 0.675s / OK，
   `/tmp/t147-sub-target.log`；包含以下本轮新生成 actual gate Formal。
2. 冻结十模块回归命令：exit 0，88 tests / 4.113s / OK，
   `/tmp/t147-sub-regression.log`；T108/T115 精确输出、T141 汇总/digest、T142/T143 复用与
   T144/T145/T146 既有边界全部通过，没有运行 blanket discovery 或 RISC。
3. 冻结六文件 py_compile 命令：exit 0，无输出。
4. `git diff --check HEAD`：exit 0，无输出；最终记录完成后已再次核验。
5. 精确 READY_FOR_REVIEW 状态守卫：exit 0，输出 `t147_ready_for_review=pass`。

### Actual gate Formal 与公开恢复

- formal_verification: PASS；固定 nested 原始结构保持，没有展开或换无关 cone。
- top=`top`，seq=`5`。公共 all CLI 对 payload_t、envelope_t、inner、field 的声明及所有真实
  引用全部改名；assert 非 identity、原名零次、manifest/edit 全量字节对账、PySlang strict compile
  与公开解密逐字节恢复均通过。
- 证据目录：`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3`；`evidence.json` 保存精确命令/JSON，所有 frontend/stdout/stderr 留存。
- gold：`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold/design.sv`；gate：`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate/design.sv`。
- 以下子进程由冻结目标命令在 Conda `rtl_obfuscation` 环境内实际执行，命令保留实际解释器路径：

公开加密（exit 0）：

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/rtl_encrypt.py --filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold/design.f --top top --rewrite-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold --category all --output-dir /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate --quiet
```

公开解密（exit 0）：

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/rtl_decrypt.py --gate-dir /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate --map /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate/mapping.json --output-dir /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/restore
```

原始 ↔ actual gate（exit 0）：

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold/design.f --gold-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold --gate-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate/design.f --gate-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate --top top --seq 5
```

```json
{"formal_equivalence": "pass", "gate": "/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate", "gold": "/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold", "seq": 5, "top": "top"}
```

独立 vector oracle ↔ 原始（exit 0）：

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/oracle/design.f --gold-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/oracle --gate-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold/design.f --gate-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold --top top --seq 5
```

```json
{"formal_equivalence": "pass", "gate": "/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold", "gold": "/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/oracle", "seq": 5, "top": "top"}
```

独立 vector oracle ↔ actual gate（exit 0）：

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/oracle/design.f --gold-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/oracle --gate-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate/design.f --gate-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate --top top --seq 5
```

```json
{"formal_equivalence": "pass", "gate": "/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate", "gold": "/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/oracle", "seq": 5, "top": "top"}
```

Frontend check（exit 0，本样例无 warning；完整日志 `/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold-frontend.log`）：

```sh
yosys -p 'read_verilog -sv -formal -defer "/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold/design.sv"; prep -top top -flatten; check -assert'
```

Frontend check（exit 0，本样例无 warning；完整日志 `/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate-frontend.log`）：

```sh
yosys -p 'read_verilog -sv -formal -defer "/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gate/design.sv"; prep -top top -flatten; check -assert'
```

固定功能负例：仅 actual gate 的 `4'ha` → `4'hb`，复制后重建 filelist 指向 mutated 文件，
PySlang catalog/top 均 0 parse / 0 semantic error；Formal exit 1，stderr 含 `unproven`
与 `equiv_status -assert`，完整 negative.stdout / negative.stderr 保留。

```sh
/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python /Users/lufengchi/Desktop/workspace/rtl_obfuscation/scripts/formal_equivalence.py --gold-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold/design.f --gold-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/gold --gate-filelist /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/negative/design.f --gate-root /private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-pi6a7ls3/negative --top top --seq 5
```

未覆盖边界：以上 Formal 仅证明固定 compact named nested 样例；数组、union、内联载体等其他
新形态只报告已执行的 PySlang/range/restore 验证，不声称有 Yosys 证明。实际服务器覆盖率与运行
时间尚未复测；本任务不包含并行或性能承诺。子 Agent 未 commit/push/ACCEPTED/创建后续任务。

## 主 Agent 独立验收

2026-09-23 Main 恢复任务后刷新 origin，确认 HEAD 与 origin/main 为 0/0，修改仍精确限定于
八个允许文件。子 Agent 完成交审后，Main 先通过精确 READY_FOR_REVIEW 守卫，再独立执行
全部冻结命令：目标 9 tests / 0.689s、十模块回归 88 tests / 4.136s、六文件 py_compile、
git diff --check HEAD 均 exit 0。日志 `/tmp/t147-main-target.log`、
`/tmp/t147-main-regression.log`；没有 blanket/RISC 验收。

Main 独立运行预先冻结的 `/tmp/t147-main-verify-delta.py`，对比修复前完整机器基线，exit 0。
T108 全部记录/引用/决定/outcome 完全不变，42/70、原 digest 保持；T115 仅指定的
`struct:design.sv:1757:1769` 新增 [1880,1892) semantic_type occurrence、转 eligible/rename，
struct outcome 相应变为 rename=5/preserve=0。没有其他记录变化，56/126，新 digest 为
`1099de8c3ec0ffa69fc6a082aa65ddda31e76df31e3d95c24e55483fa6f311c1`。
T141 独立回归确认原 mapping digest 与汇总保持。精确差异结果保留于
`/tmp/t147-main-delta-result.json`，修改后完整投影为 `/tmp/t147-main-after.json`。

Main 重新由公共 all CLI 生成实际 gate，证据目录
`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t147-evidence-_jjlpggo`。
`evidence.json` 保存本次全部精确 argv、gold/gate/top/seq、JSON 和 negative/frontend 结果。
四个目标 payload_t/envelope_t/inner/field 的声明和引用实际改名，strict compile、manifest/edit
字节对账与公开解密恢复通过。Main 独立重跑 gold↔actual gate、oracle↔gold、oracle↔gate，
均 exit 0 / formal_equivalence=pass / top=top / seq=5；gold/gate frontend check -assert
均 exit 0 且无警告。复制此 gate 后仅改4'ha→4'hb，negative filelist 指向副本，严格编译
成功，Formal exit 1，并出现 unproven / equiv_status -assert。

Main 完成代码与测试检查，独立只读 reviewer 对八文件亦无阻塞项；正常、精确漏引用保留、
强制不完整改名严格拒绝三条路径均有非空实证。故 ACCEPTED，按 Git 流程提交推送。
本轮四项覆盖修复至此完成；服务器真实覆盖率和耗时留待用户用同一输入复跑，未作提升承诺。

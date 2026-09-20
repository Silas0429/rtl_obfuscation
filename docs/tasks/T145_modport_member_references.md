# T145：简单 modport 成员使用处的直接绑定

- 状态：`ACCEPTED`
- Main Agent：当前主 Agent；实现：独立子 Agent。
- 起点：`9145ff538963ecdaf365edb3102e2a01f126e2eb`，T144 ACCEPTED、提交并推送；工作区干净。
- 第一轮覆盖率第 2 项；验收类型 rewrite/mapping。每次仅此合同活动，接受后再创建下一项。

## 单一目标与边界

表达式的 PySlang target 为简单 ModportPortSymbol 时，只有直接 internalSymbol 存在、名称一致、
指向唯一物理 interface_member 声明，才作为该成员的别名绑定引用。记录身份仍为实际成员，
不新增 modport member 记录或 category，不以名称查找代替 direct target。
沿用原语义表达式范围、宏来源和字节校验；不能通过完整性归属“解释掉”本应真正改写的引用。
未知/异常/不同名/表达式式 modport（如 .rx(req)、.rx(req[0])）不得被套用为简单别名。
保留 source-binding、冲突、死源码、完整 CST 分母、top/root/include、实例前缀和 rate 规则。

## 固定测试与机器可读预期

新测试模块内固定 SystemVerilog 字符串，写临时输入；不改变既有 RTL fixtures。

1. 普通命名连接与位置连接的 `If.Master bus`，req/ack 通过 bus 引用：两成员均 eligible，
   声明、modport 声明中的成员 token、实际使用处及直连实例成员均完整归入同一真实声明。
2. interface 数组/array port 的 `bus[0].req`/ack，同样 direct alias 绑定；向量切片/选择及非 ANSI
   modport 端口声明用真实 PySlang case 验证有依据的范围，无法证明的形态保留而不猜测。
3. 同名但不同物理 interface/成员不得合并；无关 module 内部同名 signal 在 all 下不再因为
   本项简单 modport 遗漏而保留。比较 all 与 signals-only，保留后者既有行为。
4. `.rx(req)`、`.rx(req[0])` 作为明确负例：rx 不被当 req token 改写，内部成员不足以证明时继续保留。
   getter 缺失/异常、source-less 或不同名 target 负例不得让记录产生伪造 occurrence；逐字节/range
   和完整性保护必须生效。readonly/header、rewrite-root 外引用仍保留相关成员。
5. 不改变现有 macro-origin、unknown cross-record 和 interface_instance 前缀保留；ordinary
   interface port 的实际改写、non-interface targets 以及仅 signals 选择行为应保持正确。
6. 正例全部检查无重复/重叠范围、original_name 字节、owner/物理声明正确；代表性 all CLI 输出
   req/ack 的真实改名、strict compile、manifest/edit 对账与公开解密逐字节恢复。

## 固定 actual-gate Formal 样例（不得去掉目标语义）

```systemverilog
interface bus_if;
logic [3:0] req;
logic [3:0] ack;
modport sink(input req, output ack);
endinterface
module consumer(bus_if.sink bus);
assign bus.ack = bus.req ^ 4'ha;
endmodule
module top(input logic [3:0] a, output logic [3:0] y);
bus_if link();
consumer u(.bus(link));
assign link.req = a;
assign y = link.ack;
endmodule
```

Main 和只读前置 Agent 已验证此命名连接形态可由当前 Yosys 0.53 正确处理。
测试必须由公共 all CLI 生成实际 gate，明确 req/ack 声明和 bus 使用处改名；同一 gate 运行
scripts/formal_equivalence.py（filelist、top=top、seq=5）正例 exit 0 / JSON pass。
固定负例复制 gate 后仅把 `4'ha` 改为 `4'hb`，准确重建指向 negative 的 filelist；先 strict compile，
再 require 非零、unproven、equiv_status -assert。

额外 frontend 可信性守卫：独立普通 vector oracle `assign y = a ^ 4'ha` 分别与原始复杂语法 gold
及实际 gate 按相同现有 Formal flow 比较，均需 pass；gold/gate 还需 Yosys read_verilog -sv -formal
-defer、prep -top top -flatten、check -assert 成功。保留 parser 警告于证据，不隐藏它们。
oracle 是附加核验，不替代原始↔actual gate。不得采用已证实会产生假通过的位置连接 Formal，
不得将 array-port PySlang 正例误报为 Yosys 已覆盖。记录精确命令/路径/JSON/验证范围。

## 允许文件

- `rtl_obfuscator/rename_index.py`：仅简单 modport target 的必要规范化/使用处绑定与局部安全助手。
- `tests/test_t145_modport_member_references.py`：新目标测试及临时样例、机器证据。
- `docs/systemverilog_renaming_table.md`：直接别名及未支持形态的说明。
- 本合同：执行记录/状态/偏差。不得自行更改冻结设计和白名单。

不修改 Mapping/Rewrite/rate/SourceCatalog/SourceSet/Formal 工具或既有 tests/fixtures，不实现 struct。
必读 AGENTS.md、docs/tasks/README.md、docs/development/process/refactor_subagent_protocol.md、
docs/systemverilog_renaming_table.md、docs/development/project_structure.md、docs/formal_verification.md。
只读前置证据 `/tmp/rtl-formal-preflight-20260920/REPORT.md` 只用于能力边界，不代替本任务 actual gate。

## 起步与唯一 baseline

核对 HEAD/status，更新 IN_PROGRESS 并记录，执行：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t108_pyslang_rename_index tests.test_t115_name_completeness -v
```

先增加目标测试并记录修复前失败，再实现；在范围内自行修正普通失败，超范围偏差提交 Main。

## 冻结验收（五条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t145_modport_member_references -v
conda run -n rtl_obfuscation python -m unittest tests.test_t144_port_macro_provenance tests.test_t108_pyslang_rename_index tests.test_t115_name_completeness tests.test_t142_pending_name_proofs -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rename_index.py tests/test_t145_modport_member_references.py
git diff --check HEAD
conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T145_modport_member_references.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t145_ready_for_review=pass")'
```

目标模块打印 JSON actual-gate 证据并保留临时证据目录。禁止 blanket/RISC/历史大型验收。
子 Agent 只到 READY_FOR_REVIEW，不 commit/push/ACCEPTED；Main 独立复验上述命令和 Formal 后接受。

## 子 Agent 执行记录

2026-09-20 子 Agent 起步：HEAD=`9145ff538963ecdaf365edb3102e2a01f126e2eb`，main 与 origin/main 同步；唯一未跟踪文件为 Main 新建的本合同。已读取合同与 rtl-review-ready-task 技能，范围限定四个白名单文件，不提交/推送。先执行冻结唯一 baseline，再新增失败测试。

- Baseline：合同唯一命令 exit 0，22 tests / 0.811s。
- 修复前新增 `test_simple_named_and_positional_members_are_complete`：exit 1，两个子例均由 `req: preserved/incomplete_name_coverage` 触发失败，未改产品代码时已记录。
- API/范围证据：简单成员为 `ModportNamedPortSyntax`，`internalSymbol=VariableSymbol`；显式 `.rx(req)` / `.rx(req[0])` 为 `ModportExplicitPortSyntax`，`internalSymbol=None`。数组 port 与 non-ANSI 简单引用可用相同 direct binding；向量选取 `bus.req[0]` / `[3:1]` 和 `bus.ack[3:0]` 的现有范围解析仍不足，保持 `incomplete_name_coverage`，按合同第 2 条不猜测、不扩范围。已报告 Main。
- Main 裁定：只扩展表达式 target 规范化，保留既有 modport 声明收集路径；新表达式分支的缺失/异常 getter 均不能产生伪造 occurrence，已有声明证据使完整性保留生效。另注入全局 modport 声明 `internalSymbol` getter 抛错，要求构建中止，禁止吞异常后返回成功。全局属性缺失与 getter 抛错并不等同；本项不声称修复既有声明路径的所有缺失 API 形态。

### 交审记录

- status：`READY_FOR_REVIEW`；starting_head：`9145ff538963ecdaf365edb3102e2a01f126e2eb`。
- changed_files：本合同、`rtl_obfuscator/rename_index.py`、`tests/test_t145_modport_member_references.py`、`docs/systemverilog_renaming_table.md`。没有白名单外仓库修改。
- schema_or_behavior：仅新增值 target 的局部规范化助手；简单 ModportNamedPort 的直接 internalSymbol 经名称一致、物理声明和唯一 interface_member 校验后，仍使用既有表达式范围与 provenance 路径。非 modport targets 原样走原解析器；没有新增 category、record、schema、缓存、名称 fallback、完整性豁免或保护放宽。
- 冻结命令 1：exit 0，8 tests / 0.573s；日志 `/tmp/t145-target-acceptance.log`，目标内含独立实际 gate/负例/oracle/前端检查。
- 冻结命令 2：exit 0，35 tests / 2.169s；日志 `/tmp/t145-regression-acceptance.log`，包含既有 macro-origin、unknown cross-record、完整 CST 分母及未修改类别行为。
- 冻结命令 3：`py_compile` exit 0。
- 冻结命令 4：`git diff --check HEAD` exit 0，无输出；冻结命令 5：精确状态守卫 exit 0，`t145_ready_for_review=pass`。
- boundaries：向量 select/slice 和显式 modport alias req 继续 `incomplete_name_coverage`；可证明 ack 独立改名。只读 header/outside root、实例 prefix、source-less/异名/表达式 getter 不明仍保留。数组、位置连接、non-ANSI 只记 PySlang 绑定/range/strict compile/restore；没有将它们误报 Yosys Formal 已支持。全局声明 getter 抛错中止构建；未新增全局缺失属性的恢复策略。
- cleanup_candidates：无。未运行 blanket/RISC，未 commit/push/ACCEPTED，未创建下一任务。
- review_request：请 Main 独立复跑冻结五条及实际 gate Formal 后裁定。

### Formal 精确证据

- formal_verification：PASS；证据根目录 `E=/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t145-evidence-spve1kpz`。
- gold：`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t145-evidence-spve1kpz/gold/design.sv`；gate：同一根目录的 `gate/design.sv`，由公共 `--category all` CLI 实际生成；top=`top`，seq=5。
- 实际 gate：`req -> jTqPJ2KL3mx0ZGkQ7TD3`、`ack -> uUqnGX7iquinbqQzaO5L`；各自 declaration + 3 occurrences（modport 列表、consumer.bus、top.link）逐字节对账，manifest/edit 无遗漏，严格编译与公开解密 byte identity 通过。
- 正例 exact argv、全部 JSON、oracle 及 negative exact argv 保存在 `E/evidence.json`；同环境中子进程 Python 是 `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python`。

可复制的等价命令（E 为上面固定目录；所有命令均在 `rtl_obfuscation` 环境执行）：

```sh
E=/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t145-evidence-spve1kpz
conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist "$E/gold/design.f" --gold-root "$E/gold" --gate-filelist "$E/gate/design.f" --gate-root "$E/gate" --top top --seq 5
conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist "$E/oracle/design.f" --gold-root "$E/oracle" --gate-filelist "$E/gold/design.f" --gate-root "$E/gold" --top top --seq 5
conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist "$E/oracle/design.f" --gold-root "$E/oracle" --gate-filelist "$E/gate/design.f" --gate-root "$E/gate" --top top --seq 5
conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist "$E/gold/design.f" --gold-root "$E/gold" --gate-filelist "$E/negative/design.f" --gate-root "$E/negative" --top top --seq 5
```

前三项均 exit 0，JSON `formal_equivalence=pass, top=top, seq=5`（完整 gold/gate 路径在 evidence.json）。
第四项在复制实际 gate 并仅改 `4'ha -> 4'hb`、重建 negative 专用绝对 filelist 后，PySlang parse/semantic errors 均 0，
Formal exit 1，报告 `unproven`、`equiv_status -assert`。原始/gate 各自的
`yosys -p 'read_verilog -sv -formal -defer "<实际 design.sv 路径>"; prep -top top -flatten; check -assert'`
均 exit 0；完整日志为 `E/gold-frontend.log`、`E/gate-frontend.log`，每份保留了 5 个临时 implicit/interface
警告；独立 4-bit oracle 同时排除了双方同错假通过，未隐藏警告或修改 Formal 工具。

## 主 Agent 独立验收

2026-09-20 Main 独立执行全部五条冻结命令：状态守卫先通过，目标 8 tests / 0.577s、
指定回归 35 tests / 2.164s、py_compile、diff check 均 exit 0。日志为
`/tmp/t145-main-target.log` 和 `/tmp/t145-main-regression.log`。

Main 重新由公共 all CLI 生成 actual gate，证据目录为
`/private/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t145-evidence-c54skbn7`。
该目录 `evidence.json` 保存 Main 的全部精确命令、gold/gate/top 与 JSON；
req/ack 声明和 3 处引用实际改名，strict compile、manifest/edit 对账、公开解密 byte identity 通过。
Main 本次 gold↔actual gate、oracle↔gold、oracle↔gate 三组 Formal 均 exit 0 / pass；
复制该 actual gate 后仅 `4'ha -> 4'hb` 的负例严格编译成功、Formal exit 1，
命中 unproven / equiv_status -assert；gold/gate frontend check -assert 均 exit 0，警告保留。

Main 审阅四文件修改，独立只读 reviewer 亦无阻塞项；声明路径和完整性保护未放宽。
验收仅涵盖合同范围，不将数组/位置连接/切片声明为 Yosys 已支持，不承诺服务器覆盖提升数量。
据此设置 ACCEPTED，按项目 Git 流程提交并推送；提交结果见主 Agent 交付记录。

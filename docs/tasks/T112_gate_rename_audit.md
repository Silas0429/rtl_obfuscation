# T112：上线前的 gate 漏改引用检查（只读）

- 状态：`ACCEPTED`
- 主 Agent：Claude Fable 5
- 起始 HEAD：`4926831`（T111 已 `ACCEPTED`）
- 任务类型：只读验证工具 + 确定性测试；**不修改产品代码**
- 依据：[`T111 §12.4`](T111_record_scope_preserve.md) 记录的未闭合风险

## 0. 为什么在上线前必须做这件事

用户决定先跑扫描再上线。主 Agent 已用实验证明该风险真实存在且现有证据无法排除。

模拟"漏改引用"——被实例化模块的端口已改名为 `a_new`，但父模块的连接仍写
`.a_new(old_signal_name)`，而 `old_signal_name` 从未声明：

```text
诊断总数: 0                                       ← PySlang 严格编译完全干净
NetSymbol name='old_signal_name' isImplicit=True  ← 但隐式 net 被明确暴露
```

结论两条：

1. **风险真实**。SystemVerilog 在缺省 `default_nettype` 下把未声明标识符变成隐式 wire，
   所以漏改一个引用会**编译干净但功能错误**。对外售卖的 IP 上这是最坏的失败模式。
2. **现有指标查不出来**。主 Agent 审查 `metrics_vnext.py:_validate_gate_edits` 确认，
   `plaintext_leakage_rate` 只遍历 `execution.edits`，证明"计划的编辑都执行了"，
   不证明"gate 中没有残留旧名"；`occurrence_coverage` 同理只覆盖已识别 occurrence；
   `restored_byte_identical` 也不行——漏改处在原文件与 gate 中都是旧名，反向映射照样逐字节复原。

## 1. 单一目标

提供一个只读检查器，对一次已发布的 gate 回答一个问题并输出机器可读结果：

> gate 中是否存在应当改名却未被改名的引用？

零发现即可作为上线证据。任何发现都必须给出精确的 file/offset/name。
本任务**不修改 `rtl_obfuscator/` 下任何产品代码**，不改写 RTL，不产生 gate。

## 2. 冻结的两项检查

### 2.1 隐式 net 差分（硬门禁，零容忍）

分别编译 gold（原始 SourceSet）与 gate，枚举 `NetSymbol` 中 `isImplicit == True` 的符号，
按 (相对文件路径, 名字) 建集合，输出 `gate − gold` 的差集。

- 必须与 gold 做**差分**，不得只看 gate 绝对值：原始设计本身可能合法地含隐式 net，
  那不是本次改写引入的。
- 差集非空即判定为漏改嫌疑，逐条报告名字、所在文件、所在模块。
- 差集为空即排除"漏改 → 隐式 wire"这条路径。

### 2.2 已改名 range 的 gate 字节验证（取代原文本作用域检查）

**原冻结做法有设计缺陷，主 Agent 实测后更正。**

原措辞是"在 owner module 跨度内统计仍拼写旧名的 token 数，期望为 0"。实测该做法**必然误报**：
在 t110 fixture 的干净 gate 上报出 8 处，其中 `a`、`b` 是 struct 字段名，
设计中另有**别的**符号也叫 `a`/`b`，残留 token 合法地属于那些符号。
纯文本口径无法区分"漏改的旧名"与"同名的另一个符号"，因此不可作为门禁。

更正后的做法利用 `mapping_execution.per_file_mapping` 中每个 range 同时持久化的
`source_range` 与 `gate_range`：

- 对每条 `action == "rename"` 记录的每个 range，读取 gate 文件在 `gate_range` 处的字节；
- 必须等于 `renamed_name`；等于 `original_name` 即为漏改，其他值为 range 错位；
- 这是**精确位置比对**，不依赖名字匹配，因此不会把同名的另一个符号算进来。

该检查与 `metrics_vnext._validate_gate_edits` 的区别：后者在加密进程内用内存中的
edit 列表校验，本检查从**已发布的 gate 文件与持久化 mapping** 独立复算，
能发现落盘后被改动或 mapping 与 gate 不一致的情况。

原文本作用域检查降级为**报告项**（`residual_old_names`），只输出不参与 `verdict`：
它对"意外捕获"（内层符号改名后漏改的引用绑定到外层同名符号）仍有提示价值，
但必须由人判断，不能作为门禁。

## 3. 不包含的内容

- 不修改 `rtl_obfuscator/` 下任何文件；
- 不改写 RTL、不产生 gate、不创建输出目录（除 `--json` 指定的报告文件）；
- 不实现 Formal，不运行 Yosys；
- 不实现层次引用前缀、`NamedType` 等任何绑定规则（那些属 T113）；
- 不修改任何既有测试的断言强度；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 4. 允许修改

- 新增 `scripts/gate_rename_audit.py`
- 新增 `tests/test_gate_rename_audit.py`
- 新增 `tests/fixtures/t112_gate_rename_audit/**`
- 新增本任务单

不得修改其他任何文件。

## 5. 输入与固定接口

```sh
python scripts/gate_rename_audit.py \
  --map <gate>/mapping.json \
  --gate-dir <gate> \
  --gold-filelist <原始 filelist> \
  [--include-dir DIR]... [--define NAME[=VALUE]]... \
  [--json PATH] [--examples N] [--quiet]
```

gold 侧的编译上下文必须与加密时一致；`mapping.json` 内已持久化 SourceSet 与 compile context，
优先从其中读取，`--gold-filelist` 仅作为无法从 mapping 复原时的显式回退。
编译一律复用 `rtl_obfuscator/project_discovery.py` 的 `compile_pyslang_source_set`，
不新建第二套编译配置。

## 6. 机器可读输出

`format=rtl-obfuscation.gate-rename-audit`、`schema_version=1`，至少包含：

- `input`：gate 目录、mapping 路径、gold 来源、source unit 与 header 数；
- `compile`：gold 与 gate 各自的 parse/semantic 错误数（均须为 0，否则直接失败退出）；
- `renamed_records`：mapping 中 `action == "rename"` 的记录数与涉及的不同旧名数；
- `implicit_nets`：`gold`、`gate`、`gate_only` 三个计数，以及 `gate_only` 的明细
  （名字、文件、所在模块）；
- `residual_old_names`：命中数与明细（旧名、新名、owner module、file/offset、
  `shadowed_by_other_declaration` 布尔）；
- `verdict`：`clean` 或 `suspect`。`clean` 的定义是 `implicit_nets.gate_only == 0`
  且 `renamed_range_bytes.mismatched == 0`。`residual_old_names` 是报告项，不参与判决。

不变量：未提供 `--json` 时不得写任何文件；输入缺失或编译有错时以非零退出码与稳定错误码失败。

## 7. 固定 fixture 与必须证明的两个方向

新增 `tests/fixtures/t112_gate_rename_audit/`，测试必须同时证明**能报警**与**不误报**：

- **能报警**：构造一个人为损坏的 gate —— 取真实发布的 gate，把某个已改名端口的一处
  连接实参改回旧名。该 gate 的 PySlang 严格编译必须仍然通过（这是本检查存在的理由），
  而检查器必须报 `verdict=suspect` 且 `implicit_nets.gate_only` 命中该名字。
- **不误报**：对同一 fixture 未经损坏的真实 gate，检查器必须报 `verdict=clean`。
- 另需一例 gold 本身合法含隐式 net 的输入，证明差分逻辑不会把它算作本次引入。

## 8. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_gate_rename_audit -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t111_record_scope_preserve tests.test_t110_binding_fixes \
  tests.test_t108_pyslang_rename_index tests.test_binding_coverage -v

conda run -n rtl_obfuscation python -m py_compile \
  scripts/gate_rename_audit.py tests/test_gate_rename_audit.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T112_gate_rename_audit.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t112_ready_for_review=pass")'
```

## 9. 服务器验收（上线门禁）

在 T111 已验证的 gate 上运行：

```sh
export PROJ=/home/lufengchi/workspace/ChipPlatform
OUT=/home/lufengchi/workspace/test/stcache_all_t111_001

python scripts/gate_rename_audit.py \
  --map "$OUT/mapping.json" \
  --gate-dir "$OUT" \
  --gold-filelist "$PROJ/aic_ss/src/stcache/StCache.f" \
  --include-dir "$PROJ/common/src/StLib/common" \
  --include-dir "$PROJ/common/src/StLib/impl_template/tsmc4" \
  --json /home/lufengchi/workspace/test/stcache_gate_audit_001.json
```

上线条件：`verdict=clean`，即 `implicit_nets.gate_only == 0` 且
`renamed_range_bytes.mismatched == 0`。`residual_old_names` 若非零需人工判读，不阻塞上线。

允许的 preserve 原因集合为：`selected_top_boundary`、`outside_top_closure`、
`macro_origin_conflict`、`hierarchical_prefix_unsupported`、`source_binding_incomplete`，
以及 T113 新增的 `unelaborated_reference`（旧名还写在未被 elaborate 的源码里）。
出现该集合以外的原因需人工判读。

若 `verdict=suspect`，**不得上线**：明细中的每一条都是一个漏改的引用，
须先定性该形状并另立任务修复绑定，然后重新加密并重跑本检查。

## 10. Formal verification

```text
formal_verification: N/A
reason: this task produces no rewritten RTL; the auditor is read-only and emits
        only a JSON verdict over an already published gate
```

## 11. 执行记录

```text
status: ACCEPTED
starting_head: 4926831
```

### 11.1 执行者说明（流程偏差，显式记录）

子 Agent 在本任务上连续两次因 API 鉴权 403 无法启动（本会话累计 5 次）。
用户在被告知代价后选择方案 B：授权主 Agent 本次直接实现。
理由是本任务为**只读审计工具**，§3/§4 明确禁止触碰 `rtl_obfuscator/`，
不存在污染产品的风险，且它是用户正在等待的上线门禁。
代价是本项失去"实现者与验收者分离"的双重检查，已如实记录，不隐藏。

changed_files: scripts/gate_rename_audit.py（新增）；tests/test_gate_rename_audit.py（新增）；
  tests/fixtures/t112_gate_rename_audit/{implicit_gold.f,implicit_gold.sv}（新增）；本任务单
product_code_untouched: `git status --porcelain` 中无 `rtl_obfuscator/` 条目

## 12. 实现过程中发现并更正的两处自身缺陷

主 Agent 在实现中发现**冻结契约与首版实现各有一处缺陷**，均已更正并记录。

### 12.1 §2.2 原措辞必然误报（契约缺陷）

原冻结做法"在 owner module 跨度内统计仍拼写旧名的 token，期望为 0"在 t110 干净 gate 上
报出 8 处误报：`a`、`b` 是 struct 字段名，设计中另有**别的**符号也叫 `a`/`b`，
残留 token 合法地属于那些符号。纯文本口径无法区分"漏改的旧名"与"同名的另一个符号"。

已按 §2.2 更正为**精确位置的 gate 字节验证**：利用 `per_file_mapping` 中每个 range 同时
持久化的 `source_range` 与 `gate_range`，读取 gate 在 `gate_range` 处的字节并要求等于
`renamed_name`。不依赖名字匹配，因此不会把同名的另一个符号算进来。
原文本检查降级为报告项 `residual_old_names`，不参与 `verdict`。

### 12.2 隐式 net 差分未考虑改名（实现缺陷）

首版按 (文件, 名字) 直接做 `gate − gold` 差分。`implicit_gold` fixture 立刻暴露问题：
gold 有 1 个隐式 net `mid_wire`，gate 也有 1 个，但**名字不同**——工具把它一致地改名了
（隐式 net 无声明，但其 occurrence 仍被改写）。原始差分把它误报为新引入。

已更正为**先经改名映射转换 gold 名字再差分**：
`expected_gate = {(file, rename_map.get(name, name)) for file, name in gold_implicit}`。

## 13. 主 Agent 验收记录

```text
reviewed_at: 2026-08-27
gate_1: exit 0；tests.test_gate_rename_audit Ran 6 tests；OK
gate_2: exit 0；T111 + T110 + T108 + binding_coverage Ran 54 tests；OK
gate_3: exit 0；py_compile
gate_4: exit 0；git diff --check HEAD
gate_5: exit 0；t112_ready_for_review=pass
product_untouched: git status 中无 rtl_obfuscator/ 条目，§3/§4 边界守住

三个方向实测（§7 要求）:
  1. 完好 gate            → verdict=clean   exit 0
     implicit_nets.gate_only=0；renamed_range_bytes checked=187 mismatched=0
  2. 人为损坏 gate         → verdict=suspect exit 1
     损坏后 PySlang parse_errors=0 semantic_errors=0（本审计存在的理由）
     检查 1 精确命中：implicit_nets.gate_only=1，名字即被还原的旧名
     检查 2 独立命中同一 offset
  3. gold 自带隐式 net     → verdict=clean   exit 0
     implicit_nets.gold=1、gate_only=0，证明差分不归咎于本次改写

测试内的损坏点选择是**搜索式**的：逐个尝试 semantic_reference 编辑，
取第一个"还原后 gate 仍 0/0 编译"的位置。因为并非所有还原都对编译器不可见——
还原连接标签会命名一个已不存在的端口，编译器会正确报错，而那不是本审计要覆盖的情形。
若某天所有候选都被编译器捕获，该测试会以明确信息失败，提示本审计前提不再成立。

local_result: PASS
server_gate: PENDING —— §9 的上线门禁需在 StCache gate 上运行
```

### 12.3 gold 源码根推导错误（实现缺陷，服务器暴露）

服务器首次运行报：

```text
{"error": "AUDIT_COMPILE_FAILED",
 "message": "gold: No such file or directory:
  '/home/lufengchi/workspace/ChipPlatform/aic_ss/src/stcache/aic_ss/src/stcache/src/Csr'"}
```

路径重复。首版把 `--gold-filelist` 的**父目录**当作源码根，但 `compile_order` 里的条目
是相对更高层的根的。StCache 的 filelist 位于 `<root>/aic_ss/src/stcache/StCache.f`，
其 compile_order 形如 `aic_ss/src/stcache/src/Csr/...`——相对 `<root>`，
因为 `--include-dir` 把 SourceSet 推导出的根抬到了 ChipPlatform。

同时确认：**mapping 不持久化源码根**（`source_set` 只有相对路径，这是可移植性设计），
所以根必须推导，不能从文件里读。

已更正为 `_resolve_gold_root`：从 filelist 所在目录逐级向上，取第一个能让
`compile_order` 全部解析的祖先目录；`--gold-root` 显式指定时优先；
都无法确定时以退出码 2 明确失败并列出尝试过的路径。

本地用 StCache 的真实布局验证：深埋的 `aic_ss/src/stcache/StCache.f` 正确推导出
`ChipPlatform`，且断言"filelist 自身目录是错误答案"。新增 4 条测试
（`GoldRootDerivationTest`），测试总数 6 → 10。

## 14. 服务器上线门禁结果：`suspect`，禁止上线（2026-08-27）

在 T111 已验证的 gate（`stcache_all_t111_001`）上运行 §9 命令：

```text
gold /home/lufengchi/workspace/ChipPlatform   source units 154
renamed records 5931（3347 个不同旧名）
compile: gold 0/0   gate 0/0          ← 严格编译两侧都干净
renamed_range_bytes: checked 21922  leaked 0  misplaced 0  mismatched 0
implicit_nets: gold 17  gate 1526  gate_only 1514
residual_old_names: 5450（报告项）
VERDICT: suspect      exit 1
```

**禁止上线。**审计抓到真实缺陷，正是它被造出来要防的那一类。

### 14.1 为什么这不是误报

三条同时成立只有一个解释：`mismatched=0` 说明计划的编辑全部正确落地；
`gate` 严格编译 0/0 说明编译器查不出问题；而 `gate_only=1514` 说明 gate 里
多出 1514 个隐式 net，其名字全是 `AR_CACHE_CFG0_Ctrl_q` / `_qs` / `_wd` / `_we` / `_addrhit`
这类**生成式 CSR 旧名**，不是随机新名。

即：工具正确改了声明，但某些引用从未被识别，gate 里那些引用仍是旧名 → 未声明 → 隐式 wire。

逐名验证 `AR_CACHE_CFG0_Ctrl_q`：

```text
gold 2 处：  output logic [2:0]  AR_CACHE_CFG0_Ctrl_q,   ← 端口声明（已改名）
             .q  (AR_CACHE_CFG0_Ctrl_q),                  ← 连接实参（未改名）
gate 1 处：  .q  (AR_CACHE_CFG0_Ctrl_q),                  ← 残留
```

该输出端口在 gate 中已悬空。功能确实错误。

### 14.2 根因：死 generate 分支内的连接实参不产生任何引用节点

主 Agent 并排实测三种实例化情形：

| 情形 | errors | `UninstantiatedDefSymbol` | 实参的 AST 引用数 |
| --- | --- | --- | --- |
| A 模块有定义、实例化在活代码 | 无 | 0 | **1**（正常绑定） |
| B 模块无定义（真黑盒） | `UnknownModule`（error） | 1 | **0** |
| **C 模块有定义、实例化在未选中 generate 分支** | **无** | **1** | **0** |

情形 C 与 StCache 完全吻合：编译干净（`semantic_errors=0`）、
`UninstantiatedDefSymbol` 非零（StCache 为 357）、连接实参不可见。
情形 B 会报 error，故 StCache 不是它。

再模拟 gate 状态确认闭环——声明已改名、死分支实参留旧名：

```text
errors = []            ← 严格编译查不出来
隐式 net = ['CFG_q']    ← 旧名以隐式 wire 出现
```

这就是 1514 个 gate-only 隐式 net 的完整机制。

### 14.3 这暴露了一个必须写进判据的结论

**"四组均 rename > 0 且无未解释 preserve 原因" 不足以作为上线判据。**

T111 的服务器数据满足了那个条件，`occurrence_coverage=1.0`、
`plaintext_leakage_rate=0.0`、`restored_byte_identical=true`、`strict_compile_passed=true`
全部为真，而 gate 仍然功能错误。原因是这些指标都只覆盖**工具已识别的** occurrence，
对"从未识别"无能为力。

上线判据必须叠加本审计：`verdict=clean`。

### 14.4 T112 自身的验收结论

审计器**按设计工作**：在真实工程上首次运行即发现了既有指标全部漏掉的功能性缺陷，
且两项检查表现符合预期——`renamed_range_bytes` 证明落盘无误（`mismatched=0`），
`implicit_nets` 差分定位到 1514 处漏改。`residual_old_names` 作为报告项也验证了
降级决定正确：5450 条中混有大量合法项（如 `.clk` 标签指向子模块端口），
若当初作为门禁会淹没真正的信号。

`main_result: ACCEPTED`（审计器本身）
`ship_decision: BLOCKED` —— 修复归 T113，修复后必须重新加密并重跑本审计

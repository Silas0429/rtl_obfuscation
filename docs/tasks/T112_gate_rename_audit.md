# T112：上线前的 gate 漏改引用检查（只读）

- 状态：`READY`
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

### 2.2 残留旧名的作用域检查（报告项，需逐条解释）

`isImplicit` 检查不覆盖**意外捕获**：内层 `sig` 改名后，漏改的引用可能绑定到外层同名 `sig`，
既无隐式 net 也无诊断。因此补一项作用域检查。

对 mapping 中每条 `action == "rename"` 的记录（旧名 `n`，其 `owner_module`）：

- 在 **gate** 中枚举该 owner module 源码跨度内全部 `TokenKind.Identifier` token；
- 统计仍拼写 `n` 的 token 数；
- 期望为 0。非 0 时逐条报告 file/offset，并标注是否存在同名的**其他**声明
  （合法遮蔽）以便区分。

模块跨度沿用 `scripts/binding_coverage.py` 已有的 `_unit_spans` 做法，
不得新增名称搜索、文本扫描或正则解析来判定归属。

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
- `verdict`：`clean` 或 `suspect`。`clean` 的定义是
  `implicit_nets.gate_only == 0` 且 `residual_old_names` 为空。

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

上线条件：`verdict=clean`，即 `implicit_nets.gate_only == 0` 且 `residual_old_names` 为空。

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
status: READY
starting_head: 4926831
```

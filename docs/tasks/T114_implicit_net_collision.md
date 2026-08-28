# T114：修正审计器隐式 net 差分的假 `suspect`

- 状态：`READY`
- 主 Agent：Claude Fable 5
- 起始 HEAD：`cdc21b9`（T113 已 `ACCEPTED`）
- 任务类型：只读审计工具的判定精度修正；**不修改 `rtl_obfuscator/` 下任何产品代码**
- 依据：[`T113 §13`](T113_unelaborated_reference.md) 的实测根因

## 0. 缺陷（已实测，不需重新发现）

`scripts/gate_rename_audit.py` 的检查 1 把 gold 的隐式 net 经改名映射转换后再与 gate 差分。
该映射是一个**全局 `旧名 → 新名` 字典**：

```python
rename_map = {
    str(record.get("original_name")): str(record.get("renamed_name"))
    for record in renamed
    if record.get("original_name") and record.get("renamed_name")
}
```

同一拼写在不同作用域会被改成**不同**新名，字典只留最后一个。
本地 `rtl_samples/RISC-V-Vector` 实测：

```text
206 个旧名被改成多于一个新名     i 有 27 个、clk 有 15 个、valid 有 5 个
```

于是 gold 的隐式 net 被翻译成错误的新名，`expected_gate` 不含 gate 实际的拼写，
报出假 `gate_only`。逐名验证（T113 §13）：

```text
gate_only 名单含 gbaYDyE7cpE3tR3iEW6N —— 一个新混淆名，不是旧名
其旧名为 vmu 模块的 valid；valid 在 vmu.sv 中根本没有声明（8 处全是端口标签与使用），
它本身就是 gold 的一个隐式 net，被改名后在 gate 中仍是隐式 net，只是换了拼写
```

方向是**偏保守**的：产生假 `suspect`，不会产生假 `clean`。所以它从未放行过错误的 gate，
T112 §14 在 StCache 上的 `suspect` 结论不受影响（那 1514 条全是旧名，
且 T113 的机制已独立证实并修复）。

但代价真实：StCache 的 `implicit_nets.gold=17`，其中任何一个若同时是"被改成多个新名"的拼写，
审计就会在一个正确的 gate 上报假 `suspect`，白费一次服务器往返，
更危险的是被误读成绑定修复没生效。

## 1. 单一目标

让检查 1 的 gold→gate 名字转换**按物理位置判定**，不按名字匹配，从而消除该假报，
且不削弱它对真漏改的检出能力。

## 2. 冻结的做法

### 2.1 转换按位置，不按名字

T112 §2.2 已经为检查 2 确立了同一条原则（"精确位置比对不依赖名字匹配，
因此不会把同名的另一个符号算进来"）。本任务把该原则应用到检查 1。

`_View.implicit_nets()` 已经在内部算出每个隐式 `NetSymbol` 的物理 `location`，
只是把 offset 丢掉了。改为同时返回 offset，并按下述规则确定每个 gold 隐式 net
在 gate 中**应有**的拼写：

| 情况 | 期望的 gate 拼写 |
| --- | --- |
| 该 (file, offset) 恰好是 mapping 中某条 `action == "rename"` 记录的一个 `source_range` | 该记录的 `renamed_name` |
| 该位置不属于任何已改名 range | 旧名原样 |

规则按**结果**定义：先尝试位置查表，取不到才回退到旧名。
不得按"观察到的那一个原因"（例如"当该拼写有多个新名时"）写条件——
这是 T108 §14、T110 §2.4 已连续出现两次并记录在
[`token_first_binding.md §6.2`](../development/architecture/token_first_binding.md) 的合同错误。

### 2.2 回退必须可见，不得静默

位置查不到而回退到旧名的次数必须出现在 JSON 报告里（新增计数字段，命名自定但需自解释），
使"审计放过了某个它无法定位的隐式 net"不能被静默吞掉。
该字段是报告项，不参与 `verdict`。

### 2.3 `verdict` 定义不变

`clean` 仍然是 `implicit_nets.gate_only == 0` 且 `renamed_range_bytes.mismatched == 0`。
本任务只提高 `gate_only` 的准确度，不改判决口径、不新增门禁项。

## 3. 不包含的内容

- 不修改 `rtl_obfuscator/` 下任何文件（审计器必须保持只读且与产品实现无关）；
- 不改写 RTL、不产生 gate、不创建输出目录（除 `--json` 指定的报告文件）；
- 不改动检查 2（`renamed_range_bytes`）与 `residual_old_names` 的现有口径；
- 不改动 `_resolve_gold_root`；
- 不改 `verdict` 的定义，不新增或移除门禁项；
- 不实现任何绑定规则；
- 不放宽任何既有断言；
- 不运行 RISC-V-Vector Formal，不使用 blanket `unittest discover`。

## 4. 允许修改

- `scripts/gate_rename_audit.py`
- `tests/test_gate_rename_audit.py`（仅新增用例；既有 10 个用例的断言不得放宽，
  若某条因返回值形状变化必须同步，逐条说明理由）
- `tests/fixtures/t114_implicit_net_collision/**`（新增）
- 本任务单

不得修改其他任何文件。

## 5. 固定 fixture

新增 `tests/fixtures/t114_implicit_net_collision/`，其设计必须同时满足：

- gold 中存在一个**隐式 net**：某个 identifier 从未声明，只作为连接实参或表达式出现，
  由缺省 `default_nettype` 吸收；
- 该拼写在设计中另有**至少两个**可改名的真实符号，且它们会被改成**不同**的新名，
  从而复现全局字典的键冲突；
- 该拼写**不出现在任何死源码里**，否则 T113 会先把它保留掉，冲突就不会发生，
  fixture 也就证明不了任何东西（这一条是本 fixture 成立的前提，必须在测试中断言）;
- 设计严格编译 `parse=0 semantic=0`，即缺陷对编译器不可见。

## 6. 机器可验收结果

测试必须**同时断言两个方向**，与 T112/T113 的做法一致：

- **修复前必假报**：用全局 `旧名 → 新名` 字典的旧口径对该 fixture 的**完好** gate 差分，
  必须得到非空 `gate_only`，且命中的名字是一个**新混淆名**（不是旧名）——
  这就是假报的指纹。旧口径可在测试内局部重建，不必保留产品代码里的旧实现。
- **修复后必干净**：同一个完好 gate 用新口径必须 `verdict=clean`、`gate_only == 0`。
- **不得因此变瞎**：在同一 fixture 上人为把一处已改名引用还原为旧名，
  要求该 gate 严格编译仍 `0/0`，而审计必须 `verdict=suspect` 且 `gate_only` 精确命中该旧名。
  这一条是防止用"扩大 expected_gate"的方式换取 clean。
- 既有 `tests/test_gate_rename_audit.py` 的 10 个用例全部仍通过，
  其中 `test_gold_side_implicit_net_is_not_blamed_on_the_rewrite` 必须仍然 `clean`。

## 7. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_gate_rename_audit -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t113_unelaborated_reference tests.test_t111_record_scope_preserve \
  tests.test_t110_binding_fixes tests.test_t108_pyslang_rename_index \
  tests.test_binding_coverage -v

conda run -n rtl_obfuscation python -m py_compile \
  scripts/gate_rename_audit.py tests/test_gate_rename_audit.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T114_implicit_net_collision.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t114_ready_for_review=pass")'
```

## 8. 本地回归测量（必做，且必须记录实际数字）

在 `rtl_samples/RISC-V-Vector`（project-root，top `vector_top`）上发布一次 gate 并审计，
记录 `verdict`、`implicit_nets` 三个计数、2.2 新增的回退计数、`residual_old_names`。

T113 之后该样本的期望是 `verdict=clean`、`gate_only=0`。本任务**不得让它变差**。
若出现任何变化，先记录实际数字再判断，不得直接调断言。

不运行该样本的 Formal，不运行 `tests.test_risc_v_vector_project_root`。

## 9. Formal verification

```text
formal_verification: N/A
reason: 本任务不产生改写 RTL；审计器为只读，仅对已发布的 gate 输出 JSON 判定。
        第 6 节第三条要求的"人为损坏 gate"是测试内的临时副本，不是本任务发布的 gate。
```

## 10. 执行记录

```text
status: READY
（子 Agent 开工前先改为 IN_PROGRESS 并在此记录 starting_head、tool_form、first_command）
```

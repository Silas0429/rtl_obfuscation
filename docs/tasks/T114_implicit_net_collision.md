# T114：修正审计器隐式 net 差分的假 `suspect`

- 状态：`ACCEPTED`
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
status: READY_FOR_REVIEW
starting_head: 02029cf（工作树干净；上一次启动因 API 认证错误在未改动任何文件前中止，本次为全新开工）
tool_form: 本机 `conda run -n rtl_obfuscation <cmd>` 报 `__conda_exe:6: permission denied`，
           故全程改用解释器绝对路径
           `/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python`
           （与 T110–T113 相同的替换；第 7 节命令语义不变，仅前缀替换）
python: 3.12.13   pyslang: 11.0.0
first_command:
  conda run -n rtl_obfuscation python -c 'print("ok")'
    -> stderr `__conda_exe:6: permission denied:`（因此确认必须替换前缀）
  /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python -c 'import pyslang, sys; ...'
    -> `3.12.13 ... / 11.0.0`
```

### 10.1 变更文件

| 文件 | 变更 |
| --- | --- |
| `scripts/gate_rename_audit.py` | +103 / -20：`_View.implicit_nets()` 返回 (file, offset, name)；新增 `_renamed_name_at()`；检查 1 改为按位置翻译并统计回退；报告与摘要新增回退字段 |
| `tests/test_gate_rename_audit.py` | +316 / -41：新增 `ImplicitNetCollisionTest`（5 个用例）；把损坏点搜索提取为模块级 `_revert_one_renamed_reference()` 并由既有 `_damaged_gate` 委托调用；新增 `T114_FIXTURE` 常量 |
| `tests/fixtures/t114_implicit_net_collision/collision.sv` | 新增，60 行 |
| `tests/fixtures/t114_implicit_net_collision/collision.f` | 新增，1 行 |
| 本任务单 | 状态与本执行记录 |

`git diff --numstat HEAD` 实测：`scripts/gate_rename_audit.py` 103/20、
`tests/test_gate_rename_audit.py` 316/41。

`git status --porcelain` 确认未触碰 `rtl_obfuscator/` 下任何文件：

```text
 M docs/tasks/T114_implicit_net_collision.md
 M scripts/gate_rename_audit.py
 M tests/test_gate_rename_audit.py
?? tests/fixtures/t114_implicit_net_collision/
```

### 10.2 实现口径（按第 2 节）

`_renamed_name_at(records)` 把每条 `action == "rename"` 记录的**全部源码 range** 按
`(file, start)` 建索引。检查 1 对每个 gold 隐式 net：

```python
translated = renamed_at.get((file, offset))
if translated is None:
    fallback.append(...)      # 可见
    translated = name         # 回退到旧名
expected_gate.add((file, translated))
```

条件写在**结果**上（"位置查不到"），没有出现"当该拼写有多个新名时"之类按原因写的触发条件，
符合 §2.1 对 T108 §14 / T110 §2.4 合同错误的禁止。

一处必须记录的实测细节：**隐式 net 的位置存在记录的 `declaration` 字段里，不只在
`occurrences[*].source_range` 里**。§2.1 的表述是"某条记录的一个 `source_range`"，
而隐式 net 没有自己的声明，产品把它的**首次出现**写成了该记录的 `declaration` range。
实测 `mid_wire`：gold `NetSymbol.location.offset == 505 == declaration.start`。
因此索引必须同时收 `declaration` 与每个 `occurrences[*].source_range`；
只收后者会让每个隐式 net 都落进回退，检查 1 直接变瞎。这不是合同缺陷，是合同措辞
未点明的字段名，已按实测实现并在 `_renamed_name_at` docstring 中写明。

`implicit_nets.gold` / `gate` 两个计数仍按 `(file, name)` 去重口径统计（用新返回值
重新构造），因此与 T112 §14、T113 §12.3 的历史数字可直接比较；位置只用于翻译。

### 10.3 §2.2 回退计数

报告新增三个字段，全部位于 `implicit_nets` 内、**不参与 `verdict`**
（`verdict` 仍只由 `gate_only` 与 `renamed_range_bytes.mismatched` 决定，未改动）：

```text
implicit_nets.gold_fallback_to_old_name    整数计数
implicit_nets.gold_fallback_note           自述该字段是 report only 且是本检查唯一的失明途径
implicit_nets.gold_fallback_detail          {name, file, start}，受 --examples 截断
```

`_print_summary` 也打印该计数，避免只看 stderr 摘要的人漏掉它。

### 10.4 第 7 节验收命令与实际输出

命令按第 7 节原文，仅把 `conda run -n rtl_obfuscation python` 替换为
`/Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python`（见 tool_form）。

```text
1) python -m unittest tests.test_gate_rename_audit -v
   Ran 15 tests in 1.001s
   OK
   exit_code: 0
   （既有 10 个用例 + 新增 5 个用例；stderr 另有三行 AUDIT_* JSON，
     来自故意触发失败路径的既有用例，非错误）

2) python -m unittest tests.test_t113_unelaborated_reference \
     tests.test_t111_record_scope_preserve tests.test_t110_binding_fixes \
     tests.test_t108_pyslang_rename_index tests.test_binding_coverage -v
   Ran 64 tests in 2.250s
   OK
   exit_code: 0
   （T110/T111/T113 的 FORMAL_POSITIVE 均 exit 0 / "formal_equivalence": "pass"，
     FORMAL_NEGATIVE 均 exit 1 / "unproven; equiv_status -assert"，与历史一致）

3) python -m py_compile scripts/gate_rename_audit.py tests/test_gate_rename_audit.py
   （无输出）
   exit_code: 0

4) git diff --check HEAD
   （无输出）
   exit_code: 0

5) 状态守卫（本记录写完、状态改为 READY_FOR_REVIEW 后执行，输出见 10.8）
```

### 10.5 三个方向的实证（第 6 节）

新增用例 `ImplicitNetCollisionTest`，fixture 顶层 `t114_collision_top`，
`valid` 一名对应 5 个不同符号（两个 leaf 端口、两个已声明信号、一个隐式 net），
全部改名且新名两两不同。

```text
fixture 的 5 条 valid 记录（实测，均 action=rename、reason=null）
  ports    t114_sink_a       decl 1372 -> lfEy1GbUcWZcpufk_0mo
  ports    t114_sink_b       decl 1500 -> DuT6zb8oTZk_8lRynrhC
  signals  t114_producer     decl 1637 -> htvlvTgmP2mR4ipMPELU
  signals  t114_collision_top decl 2047 -> rUZFw4DOC55JocuQzqkB   ← 隐式 net
  signals  t114_late_stage   decl 2380 -> xJvScwRf1acQVmoW_k30
全局旧名→新名字典只留最后一个：valid -> xJvScwRf1acQVmoW_k30 ≠ rUZFw4DOC55JocuQzqkB
```

（新混淆名每次运行随机，上表与下文引用的具体拼写来自我这一次运行；
主 Agent 复跑会看到不同的新名。测试不硬编码任何新名：方向一断言的是
"命中的名字属于本次 mapping 的新名集合且不属于旧名集合"这个指纹，
而不是某个具体字符串。记录的 `declaration` offset 是稳定的。）

方向一，**修复前必假报**（旧口径在测试内局部重建，产品脚本不保留第二条路径）。
用改动前的脚本对该 fixture 的完好 gate 实跑：

```text
verdict suspect   implicit_nets gold 1  gate 1  gate_only 1
gate_only_detail  [{"name": "rUZFw4DOC55JocuQzqkB", "file": "collision.sv"}]
                  ← 命中的是一个新混淆名，不是旧名，即 T113 §13 的假报指纹
```

方向二，**修复后必干净**：同一完好 gate

```text
verdict clean  exit 0  gold 1  gate 1  gate_only 0  gold_fallback_to_old_name 0
```

方向三，**不得因此变瞎**（第 6 节第三条，反作弊）。复用既有
`_damaged_gate` 的"搜索一个编译器看不见的损坏点"做法（已提取为
`_revert_one_renamed_reference`，见 10.6），共两个用例：

```text
(a) 不限拼写的搜索：还原 out_a（sink_a 内连续赋值左端）
    损坏 gate 严格编译 (0, 0)      ← 缺陷对编译器不可见
    审计 verdict suspect  exit 1  gate_only 1  gate_only_detail ["out_a"]
(b) 强制落在冲突拼写上：还原 valid
    损坏 gate 严格编译 (0, 0)
    审计 verdict suspect  exit 1  gate_only 1  gate_only_detail ["valid"]
两者都另外要求 check 2 在同一 gate offset 上独立命中。
```

(b) 是必须加的：主 Agent 点明"把更多名字塞进 expected_gate"是最省事的错误修法，
于是我在临时副本上真的实施了该作弊（`expected_gate.add((file, name))`，即同时接受旧名）
并对两个损坏 gate 实跑，结果：

```text
损坏点        诚实脚本                      作弊脚本
out_a        gate_only=1（命中）           gate_only=1（也命中）  ← (a) 抓不到该作弊
valid        gate_only=1（命中）           gate_only=0（失明）    ← 只有 (b) 抓得到
```

因此 (a) 单独存在不足以守住反作弊，(b) 是承重的。
（作弊副本在 `/tmp` 内，已删除，未进入仓库。作弊脚本对 `valid` 仍报 suspect，
但那是检查 2 独立命中的功劳；检查 1 已经失明，故断言必须落在 `gate_only` 上，
不能只断言 `verdict`。）

方向四，**fixture 前提必须断言而非假设**（§5 第三条）。
`test_fixture_really_reproduces_the_key_collision` 断言：该拼写的记录 ≥3 条、
全部 `action == "rename"`、无一条 `reason == "unelaborated_reference"`、
新名两两不同、且全局字典会留下的那个值 ≠ 隐式 net 实际拿到的新名。
若冲突拼写出现在死源码里，T113 会先整批保留，改名不发生，冲突也不发生，
fixture 会在"仍然通过"的情况下什么都证明不了——所以 fixture 里没有任何死源码，
且 `t114_late_stage` 虽然写在 top 之后，仍由 top 实例化（否则它会变成未 elaborate 单元，
反而触发 T113 的保留，fixture 自我失效）。

### 10.6 既有 10 个用例是否改动

**断言一条未改、一条未放宽。** 10 个用例的断言文本全部原样保留，
`implicit_nets()` 返回值形状变化没有波及它们，因为报告 JSON 的
`implicit_nets.gold` / `gate` / `gate_only` 三个计数口径保持不变（见 10.2 末段），
而这 10 个用例只读 JSON，不直接调用 `implicit_nets()`。

唯一的非断言改动，逐条说明：

```text
tests/test_gate_rename_audit.py
  GateRenameAuditTest._damaged_gate（辅助方法，非用例、无断言语义变化）
    原 47 行的候选搜索循环提取为模块级 _revert_one_renamed_reference()，
    _damaged_gate 改为委托调用并保留原 self.fail() 文案。
    理由：第 6 节第三条要求新 fixture 用同一套"搜索编译器不可见损坏点"的做法；
          主 Agent 明确要求"复用该做法而不是另造一套"。提取而非复制，
          可避免两份会各自漂移的搜索实现。
    行为等价：原 self.assertTrue(candidates, ...) 改为 helper 内的 assert，
          unittest 对两者的失败呈现相同；返回值仍是 (damaged, original, start)；
          候选顺序、筛选条件（provenance == "semantic_reference"）、
          "第一个仍 0/0 编译的候选获胜"均未改。
    验证：test_damaged_gate_still_compiles_but_is_flagged 仍通过，
          且仍命中同一个旧名与同一个 offset。
  新增 only_old_name 可选参数（默认 None = 原行为），供 10.5(b) 把损坏点
    限制到冲突拼写；既有调用点不传该参数，行为不变。
  新增模块级常量 T114_FIXTURE。
```

`test_gold_side_implicit_net_is_not_blamed_on_the_rewrite` 仍为 `clean`（用例通过）。

### 10.7 §8 本地回归测量（RISC-V-Vector，project-root，top `vector_top`）

```text
发布 gate：
  python rtl_encrypt.py --source-root rtl_samples/RISC-V-Vector --top vector_top \
    --category all --output-dir /tmp/t114_rvv/gate
  exit_code: 0
  action_counts  rename 863  preserve 244  unsupported 0   （与 T113 §12.3 的 after 一致）
  files 19  modified_tokens 4281  strict_compile_passed true  restored_byte_identical true

审计：
  python scripts/gate_rename_audit.py --map /tmp/t114_rvv/gate/mapping.json \
    --gate-dir /tmp/t114_rvv/gate --gold-root rtl_samples/RISC-V-Vector \
    --json /tmp/t114_rvv/audit.json
  exit_code: 0
  verdict                    clean
  compile                    gold 0/0   gate 0/0
  implicit_nets.gold         5
  implicit_nets.gate         5
  implicit_nets.gate_only    0
  gold_fallback_to_old_name  1
  gold_fallback_detail       [{"name": "valid", "file": "rtl/vector/vmu.sv", "start": 20220}]
  renamed_range_bytes        checked 4281  leaked_old_name 0  misplaced 0  mismatched 0
  residual_old_names.count   11
```

对照 T113 §12.3 的 after 侧（`verdict=clean`、`gold 5`、`gate 5`、`gate_only 0`、
`residual 11`）：**逐项一致，无回退**。

那唯一 1 次回退已逐名查清，是良性的那一读：`valid` @ `rtl/vector/vmu.sv:20220`
正是 T113 §13 追查的那个符号。T113 之后它的记录是
`action=preserve, reason=unelaborated_reference`（该拼写另写在死源码里），
既然没有改名记录，它的位置自然不在任何 renamed range 内，回退到旧名 `valid` 是**正确**结论——
gate 在该处确实仍是 `valid`，故 `gate_only=0`。
两个样本因此把回退计数的两读都覆盖到了：fixture 侧隐式 net 被改名，计数 0；
RISC-V-Vector 侧隐式 net 被保留，计数 1。

未运行该样本的 Formal，未运行 `tests.test_risc_v_vector_project_root`（CLAUDE.md 排除）。

### 10.8 一处必须更正的引用数字（实测与合同 §0 不一致，非缺陷）

合同 §0 与 `token_first_binding.md` §8.2.1 写"206 个旧名被改成多于一个新名
（`i` 有 27 个、`clk` 有 15 个、`valid` 有 5 个）"。在**本次发布的 T113 之后的 mapping**
（863 条改名）上实测：

```text
被改成多于一个新名的旧名：169 个     i 仍为 27 个
clk  -> 0 个（该拼写现已全部保留，不再参与改名）
valid -> 0 个（同上）
```

206 是 T113 修复前（1090 条改名）的数字，两者都对，只是测量条件不同：
T113 把 `clk`、`valid` 整批保留后，它们退出了冲突集合。
机制本身没变（169 个仍在冲突，`i` 仍 27 个），所以缺陷与本任务的必要性不受影响；
但它带来一个必须讲明的后果——**RISC-V-Vector 现在已经无法复现该假报**，
因为它的 `valid` 一条都不改名了。这正是第 5 节要求专门 fixture 的原因，
也说明 §8 的 `clean` 不能被当作"修复生效"的证据，真正的证据是 10.5 的方向一/二。
我按实测把 `_renamed_name_at` docstring 与新测试类 docstring 的引用改成 169 并注明
T113 当时测得 206 的条件；未改动合同 §0 与架构文档（不在允许修改范围内），
请主 Agent 决定是否同步 `token_first_binding.md` §8.2.1。

### 10.9 未覆盖的边界

1. **宏内共享的物理 token**：若同一物理 range 被多条改名记录共用，
   `_renamed_name_at` 的后写覆盖前写。本地两个样本都没有这种记录
   （产品已有 `macro_origin_conflict` 逐对象保留策略，正常不会产生），
   故未构造用例，也未加冲突检测——加检测属于新门禁项，第 3 节禁止。
2. **无法定位到文件的隐式 net**：`implicit_nets()` 对这种 net 给 offset `-1`，
   它永远匹配不到 renamed range，因此必然落进回退并被计数（不会静默）。
   本地无此样本，未构造。
3. **`mapping_execution` 缺失时**：检查 1 只依赖 `mapping.records`，不依赖
   `mapping_execution`，所以位置索引仍可建；检查 2 的既有口径未改动。未专门构造用例。
4. **`gold_fallback_to_old_name` 的两读未在报告中自动区分**：字段只给出计数与明细，
   "该 net 本就没改名"（良性）与"该 net 改了名但没定位到"（危险）需人工判读，
   判据是查明细里的名字在 mapping 中是 preserve 还是 rename。
   自动区分需要引入按名字的推断，与 §2.1 的禁止相冲突，故不做。
5. **服务器 StCache 未测**：本任务只做本地测量，第 8 节未要求服务器往返。
   StCache 的 `implicit_nets.gold=17` 是否含冲突拼写，仍待主 Agent 的服务器验收确认。
6. 本任务未触碰 `rtl_obfuscator/`、检查 2、`residual_old_names`、`_resolve_gold_root`、
   `verdict` 定义，也未新增或移除门禁项。

### 10.10 PySlang API

没有与合同不一致之处。`NetSymbol.isImplicit` 与 `NetSymbol.location` 均按 §2.1 预期工作；
`location` 需要先过既有 `physical()` 做宏位置还原（既有代码已如此，未改）。
唯一与合同措辞有落差的是 mapping 的字段名而非 PySlang API，见 10.2。

### 10.11 Formal verification

```text
formal_verification: N/A
reason: 本任务不产生改写 RTL；审计器为只读，仅对已发布的 gate 输出 JSON 判定。
        第 6 节第三条的"人为损坏 gate"是测试内的临时副本（TemporaryDirectory），
        不是本任务发布的 gate。§8 发布的 RISC-V-Vector gate 在 /tmp 内，
        按 CLAUDE.md 不运行该样本的 Formal。
```


## 11. 主 Agent 独立验收记录

```text
reviewed_at: 2026-08-28
reviewed_head: 02029cf（与执行记录一致）
tool_form: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python
  （`conda run -n rtl_obfuscation` 在本机同样报 permission denied，与子 Agent 记录一致）

第 7 节五条门禁，主 Agent 亲自复跑：
  1) tests.test_gate_rename_audit          → Ran 15 tests，OK，exit 0
  2) T113 + T111 + T110 + T108 + coverage  → Ran 64 tests，OK，exit 0
  3) py_compile 两文件                      → exit 0
  4) git diff --check HEAD                  → 无输出，exit 0
  5) T114 状态守卫                          → t114_ready_for_review=pass，exit 0

边界核对：
  `git status --porcelain` 无 `rtl_obfuscator/` 条目，第 3 节"审计器保持只读且与产品无关"守住。
  `verdict` 计算实测未改：仍为 `"clean" if not gate_only and range_bytes["mismatched"] == 0`，
  回退计数不参与判决，符合 §2.2/§2.3。
  还原后 `grep -c rename_map` 为 0，确认全局字典真的被移除，没有残留第二条翻译路径。

修复承载性（主 Agent 自行验证）：
  把 scripts/gate_rename_audit.py 还原到 HEAD 后重跑 ImplicitNetCollisionTest
  → FAILED (failures=3, errors=2)，5 个用例全部失败
  （2 个 error 源于 HEAD 的 `implicit_nets()` 返回二元组而用例按三元组解包）。
  还原回交付版后与交付文件逐字节相同。
```

### 11.1 主 Agent 亲手复现"最省事的错误修法"，确认反作弊断言真的守得住

第 6 节第三条的意义在于防止用"扩大 `expected_gate`"换取 `gate_only == 0`。
主 Agent 没有只读断言文本，而是把该错误修法实际实现出来（在 `expected_gate` 中无条件
额外加入未翻译的旧名），然后跑全部用例：

```text
作弊版审计器下：
  GateRenameAuditTest（T112 原有 6 个用例）        → OK        ← 全部通过，不设防
  test_position_keyed_translation_keeps_..._clean   → ok        ← 通过
  test_position_keyed_translation_still_flags_...   → 通过      ← 通用损坏点不设防
  test_damage_on_the_colliding_spelling_itself_...  → FAIL      ← 唯一防线
                                                      AssertionError: 0 != 1（gate_only）
诚实版审计器下：15 个用例全部 OK
```

**结论：那个针对性损坏点用例是防住该错误修法的唯一防线。**
通用的"搜索一个编译器看不见的损坏点"做法**不足以**满足第 6 节第三条——
因为它命中的是搜索顺序里第一个可用引用，未必是发生冲突的那个拼写。
子 Agent 是通过真的把作弊版写出来跑过才发现这一点并补上第二个用例的，这是正确的方法。
主 Agent 独立复现了同一结论。

### 11.2 第 8 节数字，主 Agent 用自己发布的 gate 独立复核

不采用子 Agent 留下的 `/tmp/t114_rvv`，改用主 Agent 在 T113 验收时自行发布的
post-T113 RISC-V-Vector gate，用本次交付的审计器复算：

```text
verdict clean   exit 0
implicit_nets: gold 5  gate 5  gate_only 0
gold_fallback_to_old_name: 1
  → [{"name": "valid", "file": "rtl/vector/vmu.sv", "start": 20220}]
renamed_range_bytes: checked 4281  mismatched 0
residual_old_names: 11
```

每一项与 T113 §12.3 的基线一致，无回退。那唯一一次回退正是 T113 §13 追查的
`valid` @ vmu.sv:20220：T113 之后它是 `preserve / unelaborated_reference`，
没有已改名 range 覆盖其位置，因此"期望旧名原样"是**正确答案**，gate 里也确实是 `valid`。
两个样本因此覆盖了该计数的两种读法（fixture：已改名，计数 0；RISC-V：已保留，计数 1）。

### 11.3 子 Agent 更正了主 Agent 引用的一个数字，更正成立

契约 §0 与架构文档引用"206 个旧名被改成多于一个新名（`i` 27、`clk` 15、`valid` 5）"。
主 Agent 在 post-T113 的 mapping 上独立重算：

```text
被改成多于一个新名的旧名: 169     i -> 27   clk -> 0   valid -> 0
```

子 Agent 的 169 成立。主 Agent 原先那组数字量自 **T113 之前**的 mapping，
两者在各自条件下都正确，但混用会误导。

**更重要的后果，子 Agent 主动指出且主 Agent 认可**：T113 之后 RISC-V-Vector
已**无法**复现这个假报（`valid` 不再有任何改名记录可冲突），
所以第 8 节的 `clean` 只是无回退检查，**不是 T114 有效性的证据**；
有效性完全由 `tests/fixtures/t114_implicit_net_collision` 的 before/after 对承载。
这条自我限定比一个漂亮的回归数字有价值得多。

已据此同步 `token_first_binding.md` §8.2.1（该文件在第 4 节允许列表之外，
子 Agent 正确地没有越界修改，由主 Agent 补），并把其中的通用教训写成结论：
**当上游修复消除了某个缺陷的触发条件时，必须为该缺陷单独固定一个 fixture，
否则回归测试会在"看不见"和"已修好"之间无法区分。**

### 11.4 契约措辞缺陷（主 Agent 自身的，如实记录）

§2.1 的表格写"该 (file, offset) 恰好是 mapping 中某条 `action == "rename"` 记录的一个
`source_range`"。实测：隐式 net 没有自己的声明，产品把它的**首次出现**写进记录的
`declaration` 字段，而不是 `occurrences[*].source_range`。
只按后者建索引会让每个隐式 net 都落进回退，检查 1 直接变瞎。

子 Agent 按实测同时收 `declaration` 与全部 `occurrences[*].source_range`，
并在 `_renamed_name_at` docstring 中写明理由，处理正确。
这是主 Agent 契约措辞不精确（把两个字段笼统写成"一个 source_range"），不是执行偏差。

### 11.5 既有断言与一处非断言重构

T112 原有 10 个用例**一条未改、一条未放宽**，仍全部通过，
其中 `test_gold_side_implicit_net_is_not_blamed_on_the_rewrite` 仍报 `clean`。

唯一的非断言改动：`_damaged_gate` 内 47 行的损坏点搜索被提取为模块级
`_revert_one_renamed_reference()`，`_damaged_gate` 改为委托调用，
新增用例复用同一搜索而不是另写一套。主 Agent 逐行核对：候选过滤条件、遍历顺序、
"第一个还原后仍 0/0 编译的候选胜出"、返回三元组全部未变；
`self.assertTrue(candidates,...)` 因移出 TestCase 改为 `assert candidates,...`，
`self.fail(...)` 改为返回 `None` 由调用方 fail，语义等价。
新增的 `only_old_name` 参数默认 `None`，不改变既有调用路径。

`main_result: ACCEPTED`

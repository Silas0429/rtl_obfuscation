# T038：RISC-V-Vector parameter/genvar 修复与加密率口径统一

- 状态：READY
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T037 ACCEPTED
- Formal verification：必须执行本任务专用的 RISC-V-Vector 正例和功能负例
- RISC-V-Vector Formal：本任务明确要求执行；普通任务和普通全量回归仍然排除该 Formal 链路

## 1. 单一目标

修复两个相互影响但边界明确的问题，并保持 T037 已验收的五组 RISC 演示不变：

1. `project-root + top` 手动 profile 选择 `parameters` 时，正确区分真实 module
   `parameter/localparam` 与 PySlang elaboration 产生的 generate-loop iteration parameter，
   不再把 `genvar k` 误作为 parameter 改名导致 gate 语法损坏；
2. `--encryption-rate` 的选择器和 metrics 使用同一个 effective-line 分母，使
   `metrics.affected_lines.total` 与 `metrics.encryption_rate.total_lines` 一致。

`encrypt.py` 继续固定使用 T037 的五组 category，不在本任务中加入 `parameters`，也不把
Formal 植入一键演示。需要验证 parameter-inclusive RISC 行为时，使用本任务的独立验收入口。

## 2. 固定输入和已知失败

固定 RISC 输入：

```text
project-root: rtl_samples/RISC-V-Vector
top: vector_top
manual categories: signals ports instances struct interface parameters
```

当前错误基线必须在任务记录中保留：

- gold 使用上述六组 category 可以通过分析；
- `vex.sv` 的 `genvar k` 被错误作为 5 个 `parameters` entry 收集，共 36 个伪 occurrence；
- gate 出现类似 `for (renamed = 0; k < renamed_lanes; k++)` 的部分改写；
- CLI 以 `MAPPING_V4_GATE_ANALYSIS_FAILED` 回滚且不发布半成品；
- 当前 RISC 加密率样例中 `encryption_rate.total_lines=5532`，而
  `affected_lines.total=4461`，因为前者统计物理行，后者统计非空且非 `//` 行。

## 3. 参数/genvar 修复契约

### 3.1 语义规则

- 真实 module value parameter、module `localparam` 和其已确认的表达式、dimension、
  generate header、named override 引用继续按既有 T031/T032/T035 规则处理；
- top value parameter 和 top ABI 继续 preserved；top localparam 是否 eligible 遵循现有
  classification，不得因为本修复扩大 top ABI；
- generate-loop iteration parameter 只能归入 `genvars`（当用户选择该 category），不能
  归入 `parameters`；当用户只选择 `parameters` 时必须被排除或以稳定 preserved/unsupported
  结果返回；
- 同名真实 parameter 和 genvar 必须依据语义 owner/source origin 分离，禁止按文本名称合并；
- 如果 PySlang 无法提供稳定的 genvar origin/owner 关系，必须 fail-closed，不得使用全局文本
  替换或猜测性 fallback。

### 3.2 RISC parameter-inclusive oracle

修复后的六组 RISC 手动 profile 必须满足：

- mapping version 4，19 个 closure files，17 个 reachable modules；
- 五组既有 T037 mapping 数量保持 1091 entries / 5741 occurrences；
- `parameters` category 只包含真实 module parameter/localparam，目标为 120 entries /
  1094 occurrences；其中不得出现 `scope=vex, original_name=k` 的 parameter entry；
- 六组组合目标为 1211 mapping entries / 6835 modified tokens；
- mapping ranges 不重叠，gate strict reanalysis 通过，metrics coverage=1.0，
  `plaintext_leakage_rate=0.0`；
- decrypt 后 mapping files 中全部 19 个文件与 gold byte-identical；
- 连续两次运行的 mapping、gate manifest、metrics 和 per-file map byte-identical。

上述数量是由当前失败 gate 中剔除 5 个 `vex/k` generate 伪 parameter 后冻结的目标；若实现
发现目标与 PySlang 稳定语义 API 冲突，必须先记录偏差并停止，不得自行改 oracle。

## 4. 加密率口径统一契约

### 4.1 唯一分母

本任务把 effective line 定义为源文件 `splitlines()` 后满足以下条件的行：

```text
line.strip() != "" and not line.strip().startswith("//")
```

对单文件、filelist 和 project-root 三种入口均使用 mapping 对应 RTL 文件集合计算：

- `encryption_rate.total_lines` 使用 effective line 总数；
- `encryption_rate.target_lines`、`candidate_lines`、`selected_lines`、`actual_rate` 和
  `maximum_rate` 使用同一分母；
- `affected_lines.total` 和 `affected_lines.rate` 使用同一分母；
- 对率模式，必须满足
  `affected_lines.total == encryption_rate.total_lines`，且
  `affected_lines.rate == encryption_rate.actual_rate`（允许 JSON 浮点表示误差）；
- 空行、空白行和纯 `//` 注释行不进入分母，但 identifier 影响行集合仍按原文件的 1-based
  行号记录；`.svh` 按普通 RTL 文件计入；
- 不提供 `--encryption-rate` 时，既有 mapping、gate、解密和非率 metrics 语义保持不变。

### 4.2 率选择行为

- 仍先建立完整候选 mapping，再按唯一 `(file, line)` 集合执行 greedy；
- target 不可达时仍选择全部候选、不报错，并报告 `target_unreachable=true`；
- 率选择不得因参数/genvar 修复产生重复或重叠 range；
- 率模式选择出的 mapping 必须通过现有 gate audit 和 decrypt。

## 5. 专项测试范围

新增紧凑 fixture `tests/fixtures/t038_risc_v_parameter_genvar/`，至少覆盖：

- 非顶层 module parameter/localparam；
- module parameter 与 generate-loop genvar 同名但不同 owner；
- 多个 generate loop 重复使用 `genvar k`；
- named parameter override 左侧和 RHS；
- top parameter preserved、unreachable parameter、unsupported parameter fail-closed；
- 空行、纯 `//` 行和多 mapping 命中同一物理行。

新增 `tests/test_t038_risc_v_parameter_genvar_rate.py`，验证 inventory、mapping、gate、
metrics、rate、decrypt、确定性和负向诊断。新增 `scripts/t038_acceptance.py`，只负责本任务
六组 RISC gate、formal-view、formal-align、Yosys 正负例和 byte-identical 解密，不修改
T037 的 `scripts/t029_acceptance.py` 固定五组 oracle。

## 6. RISC Formal 验收

- gold 与 parameter-inclusive gate 各生成 260 项 formal-view transformation，signature
  必须完全一致；
- gate view 只用 mapping v4 执行 formal-align，不能读取 gold；alignment 数量、manifest 和
  warning oracle 必须在新任务测试中冻结并重复运行一致；
- 正例：gold formal-view 与 aligned gate formal-view，top `vector_top`，`--seq 1`，退出码
  0 且 JSON `formal_equivalence=pass`；
- 负例：只将 `vector_idle_o` 的第一个二元 `&` 改成 `|`，退出码非零，达到
  `equiv_status -assert`，且只留下对应的一个未证明 cell；
- 正例和负例各自最多 600 秒；超时、parse error、hierarchy error 或 identity comparison
  均不算通过；
- RISC-V-Vector Formal 不加入普通全量回归。

## 7. 允许修改的文件

- `rtl_obfuscator/inventory.py`：仅修复 parameter/genvar 语义收集、分类和 source ranges；
- `tests/fixtures/t038_risc_v_parameter_genvar/**`：新增紧凑 SystemVerilog fixture；
- `tests/test_t038_risc_v_parameter_genvar_rate.py`：新增黑盒和 oracle 测试；
- `scripts/t038_acceptance.py`：新增本任务专用 RISC Formal 驱动；
- `tests/test_t036_encryption_rate.py`：更新率分母断言并补充 effective-line 一致性回归；
- `README.md`、`docs/systemverilog_renaming_table.md`、`docs/formal_verification.md`、
  `docs/future_work.md`、`docs/project_root_top_roadmap.md`：同步当前边界和新口径；
- `docs/category_profile_normalization_plan.md`、`docs/project_root_parameter_plan_draft.md`：
  将条件性 profile 晋级顺延为 T039，并记录 T038 的边界修复；
- `docs/tasks/T038_risc_v_vector_parameter_genvar_rate.md`：任务记录和验收证据。

不允许修改 `encrypt.py`、`scripts/formal_equivalence.py`、T037 固定 RISC 测试的五组 oracle
或 `rtl_samples/RISC-V-Vector` 原始 fixture；不在本任务中晋级更多 default category。

## 8. 验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t038_risc_v_parameter_genvar_rate -v
conda run -n rtl_obfuscation python -m unittest tests.test_t036_encryption_rate -v
conda run -n rtl_obfuscation python scripts/t038_acceptance.py \
  --work-dir /private/tmp/rtl-obfuscation-t038-risc-parameter
conda run -n rtl_obfuscation python -m unittest tests.test_risc_v_vector_project_root -v
conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/inventory.py tests/test_t038_risc_v_parameter_genvar_rate.py \
  tests/test_t036_encryption_rate.py scripts/t038_acceptance.py
git diff --check
```

还必须执行 README 中的显式非 RISC 回归列表，并排除 `tests.test_risc_v_vector_project_root`
之外的 RISC Formal；本任务的专用脚本是唯一允许启动 RISC-V-Vector Formal 的新入口。

## 9. 执行记录

```text
status: READY
start_record: pending
changed_files: pending
parameter_genvar_result: pending
rate_denominator_result: pending
formal_verification: pending
exact_commands: pending
exit_codes: pending
uncovered_boundaries: pending
review_request: pending
```

## 10. 主 Agent 验收记录

```text
acceptance_time: pending
independent_commands: pending
independent_results: pending
formal_recheck: pending
git_status: pending
staged_diff_review: pending
acceptance_conclusion: pending
```

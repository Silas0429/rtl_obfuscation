# T037：RISC-V-Vector Formal 验收与 encrypt.py 演示脚本

- 状态：ACCEPTED
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 前置任务：T036 ACCEPTED
- Formal verification：必须执行 RISC-V-Vector 专项正例和功能负例并 PASS/FAIL 符合预期
- RISC-V-Vector Formal：本任务明确要求执行，是普通任务之外的专门 RISC 验收任务

## 1. 单一目标

完成两项紧密相关的交付：

1. 对当前 RISC-V-Vector `vector_top` 加密 gate 重新执行完整 formal-view、formal-align 和
   Yosys equivalence 正负例验证；
2. 在仓库根目录新增 `encrypt.py`，让用户可以通过一条简单命令演示 RISC-V-Vector 的
   project-root 加密、解密和 byte-identical 恢复。

脚本是用户演示入口，不替代既有 `rtl_obfuscator.rewrite` CLI，也不把 Formal 强行加入每次
演示。Formal 使用独立的 T037 验收命令执行。

## 2. 固定 RISC-V-Vector 输入和 oracle

固定输入目录和 top：

```text
project-root: rtl_samples/RISC-V-Vector
top: vector_top
```

必须使用当前已冻结的 T029 RISC oracle：

- candidate files：56；top closure：19 个文件；reachable modules：17；interfaces：0；
- compile order：由 `inspect-project` 报告冻结，不能按文件系统遍历顺序重排；
- eligible inventory：1091 entries / 5741 occurrences；preserved：35 entries / 113 occurrences；
- project-root mapping：version 4（T035 manual profile 的固定五组 category）；
- 演示和 Formal 组合使用五组显式 category：`signals`、`ports`、`instances`、`struct`、
  `interface`；不能在本任务中把 `parameters` 晋级到该固定组合；
- 组合 gate 的预期 mapping 摘要为 19 files / 1091 entries / 5741 modified tokens；
- gold 和 gate 的 formal-view transformation 必须都是 260 项：25 个 packed aggregate type、
  233 个 packed struct member access、2 个 concurrent assertion removal；
- formal-align 必须产生 5527 个 identifier replacements，并保持 gold/gate transformation
  signature、compile order 和 warning oracle 对称；
- 既有固定 manifest/oracle 以 `tests/test_risc_v_vector_project_root.py` 和
  `scripts/t029_acceptance.py` 为唯一来源；这两个专用验收入口允许做 profile/mapping v4
  迁移，使 inspect 显式传入上述五组 category，并更新 mapping v4 字段断言及 FIFO 兼容回归
  的当前数量 oracle，不修改 RTL fixture 或 formal-view 数值 oracle。

## 3. encrypt.py 用户接口

### 3.1 一条命令

从仓库根目录执行：

```sh
conda run -n rtl_obfuscation python encrypt.py
```

默认行为：

- 输入固定为 `rtl_samples/RISC-V-Vector`，top 固定为 `vector_top`；
- 输出到 `/tmp/rtl_obfuscation_risc_demo`；该目录必须不存在或为空，不能静默删除已有内容；
- 使用五组固定 category 和 `--name-length 8`；
- 依次执行 `encrypt-project`、`decrypt-project`；
- 输出 `gate/`、`mapping.json`、`metrics.json`、`maps/`、`restored/`；
- 对 mapping `files` 中的全部 19 个文件执行字节比较；任何一个文件不一致都以非零退出；
- stdout 输出一个 JSON 汇总，至少包含 `status`、`top`、`work_dir`、加密摘要、解密摘要、
  `mapping_version`、`files` 和 `byte_identical`；成功时 `status=pass`、`byte_identical=true`。

### 3.2 可选参数

脚本可以提供以下可选参数，但不得改变默认演示语义：

```text
--work-dir <dir>       替换默认输出目录；必须不存在或为空
--name-length <int>    默认 8，复用现有最小长度校验
--encryption-rate <r>  可选，原样传给 T036 rate workflow
```

脚本不得提供 `--project-root`、`--top` 或任意 category 重写选项来制造第二套 RISC 配置。
固定输入和五组 category 是为了确保演示与 Formal oracle 一致。`--encryption-rate` 仅作为
T036 功能的可选透传；未提供时必须得到 T029 固定 1091/5741 组合。

### 3.3 安全和失败行为

- 不修改 `rtl_samples/RISC-V-Vector` 原始文件；所有 gate/restored/metadata 都写入 work-dir；
- 使用 `subprocess.run(..., check=False, capture_output=True, text=True)` 调用现有 CLI，不能
  使用 shell 拼接命令或依赖当前工作目录；脚本应以自身所在仓库根目录作为 cwd；
- 子命令非零、JSON 无法解析、mapping files 缺失、解密失败、文件数量不符或 byte mismatch
  都必须以非零退出，并把可诊断信息写到 stderr；
- work-dir 已存在且非空时必须拒绝，不能递归删除、覆盖或移动用户文件；
- 脚本不执行 formal-view、formal-align 或 Yosys；这些命令属于下方 T037 Formal 验收链路。

## 4. RISC-V-Vector Formal 验收流程

Formal 必须从同一个原始 RISC 工程和同一个真实 gate 生成对称派生 view，不能使用 gold/gate
同一份文件冒充等价证明。

### 4.1 Gold/gate 生成、gate inspect 和解密

使用 T029 组合 category 生成 gate，要求严格 re-inspect、mapping/metrics 和 decrypt 通过。
解密后 mapping `files` 中 19 个文件必须与 gold byte-identical。

### 4.2 Formal view 和 alignment

- gold 和真实 gate 各执行一次 `formal-view`；
- 两份 transformation signature 必须相同，数量均为 260；
- gate view 执行 `formal-align`，只能使用已验证的 mapping v4 和 gate view，不能读取 gold；
- alignment 必须产生 5527 个 identifier replacements；
- 重复运行 `formal-align`，manifest 和全部 19 个 aligned 文件 byte-identical；
- 正例 formal 输入为 gold formal-view 与 aligned gate formal-view，top 为 `vector_top`，
  `--seq 1`，退出码 0 且 JSON `formal_equivalence=pass`。

### 4.3 功能负例

在 aligned gate 副本中只修改 `rtl/vector/vector_top.sv` 内
`assign vector_idle_o = ...` 的第一个二元 `&` 为 `|`：

- 只允许一个 byte 发生变化；
- 使用相同 gold formal-view、top 和 `--seq 1` 运行 Formal；
- 退出码必须非零；
- 日志必须到达 `equiv_status -assert`，并只留下 `vector_idle_o` 对应的 1 个未证明
  `$equiv`，不能以 parse、hierarchy 或缺失文件错误代替功能负例。

Formal 正例和负例各自最多允许 600 秒；超时视为失败，不能跳过或改用 identity comparison。

## 5. 允许修改的文件

- `encrypt.py`：新增根目录演示脚本；
- `tests/test_encrypt_demo.py`：脚本黑盒测试，使用临时空目录和固定 RISC sample；
- `tests/test_risc_v_vector_project_root.py`、`scripts/t029_acceptance.py`：仅将旧的无 category
  inspect/profile 假设迁移到 T035 后的显式五组 manual profile/v4 mapping，并同步 FIFO 兼容回归
  的当前 mapping 数量 oracle，保留原有 manifest、inventory、formal-view、alignment 和负例 oracle；
- `README.md`：增加一条命令演示和输出说明，明确 Formal 需使用 T037 专项命令；
- `docs/formal_verification.md`：将 RISC-V-Vector 专项 alignment/decrypt 说明迁移到 mapping v4；
- `docs/tasks/T037_risc_v_vector_formal_demo.md`：任务合同、执行记录和验收记录；
- `docs/project_root_top_roadmap.md`、`docs/future_work.md`：同步 T036/T037 状态；
- `rtl_obfuscator/rewrite.py`：仅补充 `formal-align` 对已验证 mapping v4 的 gate/range/closure
  校验分派，不改变 mapping/profile/closure 语义；
- `docs/category_profile_normalization_plan.md`、`docs/project_root_parameter_plan_draft.md`：
  仅允许把历史规划中的 RISC Formal 任务编号从 T036 校准为 T037、条件性 profile 任务从
  T037 校准为 T038，不得改变历史已验收事实；
- 不允许修改 `rtl_obfuscator/` 除上述 `formal-align` v4 分派之外的核心实现、
  `scripts/formal_equivalence.py` 或任何 RISC-V-Vector RTL fixture；除本合同已列明的 T035
  profile/mapping v4 字段和 FIFO 数量迁移外，不改变既有 Formal transformation、manifest、
  inventory、alignment 或负例数值 oracle。

## 6. 测试和验收命令

所有 Python、HDL、Formal 和测试命令必须通过 `rtl_obfuscation` Conda 环境执行。

脚本专项：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_encrypt_demo -v
conda run -n rtl_obfuscation python -m py_compile encrypt.py tests/test_encrypt_demo.py
git diff --check
```

完整 RISC-V-Vector Formal 验收驱动：

```sh
conda run -n rtl_obfuscation python scripts/t029_acceptance.py \
  --work-dir /private/tmp/rtl-obfuscation-t037-formal
```

该命令必须输出 `status=pass`，同时记录 inventory、mapping、decrypt、formal-view、alignment、
Formal 正例、功能负例和 FIFO 兼容回归结果。它是本任务专用 RISC Formal 命令，不能移入普通
全量回归。

还必须执行现有的 RISC 专项 unittest 作为固定 oracle 回归：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_risc_v_vector_project_root -v
```

该 unittest 允许运行 RISC Formal，因为 T037 是专门的 RISC Formal 任务。除此之外，T037 不
要求运行全量回归；非 RISC 回归仍使用显式模块列表并排除该测试。

## 7. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
start_record: 2026-07-21; migrated T035 manual profile assumptions before implementation
changed_files: encrypt.py, tests/test_encrypt_demo.py, tests/test_risc_v_vector_project_root.py,
  scripts/t029_acceptance.py, README.md, docs/formal_verification.md, docs/tasks/T037_risc_v_vector_formal_demo.md,
  docs/project_root_top_roadmap.md, docs/future_work.md, docs/category_profile_normalization_plan.md,
  docs/project_root_parameter_plan_draft.md, rtl_obfuscator/rewrite.py
script_command: conda run -n rtl_obfuscation python -m unittest tests.test_encrypt_demo -v
script_result: 2 tests OK; real one-command run returned status=pass, mapping_version=4,
  files=19, encrypt/decrypt=1091 entries and 5741 modified tokens, byte_identical=true
formal_command: conda run -n rtl_obfuscation python scripts/t029_acceptance.py
  --work-dir /private/tmp/rtl-obfuscation-t037-final.nYz4kI
formal_verification: PASS; inventory 1091/5741 eligible and 35/113 preserved; formal-view 260
  transformations; formal-align 5527 replacements; positive formal_equivalence=pass; negative
  expected-fail with equiv_status -assert and exactly vector_idle_o unproven; FIFO positive pass
  and negative expected-fail
exact_commands: conda run -n rtl_obfuscation python -m unittest tests.test_risc_v_vector_project_root -v
  (15 tests OK, 522.721s); conda run -n rtl_obfuscation python -m py_compile encrypt.py
  tests/test_encrypt_demo.py rtl_obfuscator/rewrite.py scripts/t029_acceptance.py
  tests/test_risc_v_vector_project_root.py; git diff --check
exit_codes: all listed commands exited 0; Formal functional negative intentionally exited nonzero
  inside the acceptance driver
uncovered_boundaries: encrypt.py intentionally fixes the RISC-V-Vector project-root/top and five
  categories, does not run Formal, and rejects non-empty work directories; RISC Formal remains a
  dedicated T037 acceptance flow and is excluded from routine regression
review_request: implementation and evidence complete; ready for Main Agent independent acceptance
```

## 8. 主 Agent 验收记录

```text
acceptance_time: 2026-07-21
acceptance_head: f5c6a9b
independent_commands: t029_acceptance.py dedicated Formal chain; unittest tests.test_risc_v_vector_project_root -v;
  unittest tests.test_encrypt_demo -v; py_compile; git diff --check; one-command encrypt.py run
independent_results: Formal driver status=pass; RISC unittest 15 tests OK; demo unittest 2 tests OK;
  py_compile and diff check OK; one-command demo status=pass with 19 byte-identical files
formal_recheck: positive formal_equivalence=pass, top=vector_top, seq=1; negative nonzero and
  equiv_status -assert reached with exactly vector_idle_o unproven; alignment=5527 identifiers
git_status: staged T037 paths only; no RISC-V-Vector RTL fixture, formal script, commit or push before review
staged_diff_review: passed; mapping v4 formal-align dispatch is the only core implementation change
acceptance_conclusion: ACCEPTED; RISC-V-Vector Formal is verified only under this dedicated T037 flow;
  encrypt.py is the simple encryption/decryption demonstration entry point
```

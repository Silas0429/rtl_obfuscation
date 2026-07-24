# T055：project-root 接入 vNext 统一流水线

- 状态：READY
- 设计负责人：主 Agent
- 实现负责人：子 Agent
- 所属重构阶段：R4
- 前置任务：T054 `ACCEPTED`，交付提交 `14127eb`
- 设计基线：`0eb059d`
- 设计依据：`docs/three_mode_refactor_plan.md` 第 1–7 节
- 执行规范：`docs/refactor_subagent_protocol.md`
- Formal 依据：`docs/formal_verification.md`
- 验收类型：project-root adapter；本任务通过 vNext 生成 actual rewritten RTL
- Formal verification：必须在目标 unittest 内真实执行 project-root actual gate 的 compact Formal 正例和固定功能负例

## 1. 目标漂移检查与单一目标

当前项目目标仍是：single-file、显式 filelist 和 `project-root + top` 只负责建立同一种
`SourceSet`，之后统一进入已验收的 SymbolGraph、RewritePolicy、MappingVNext、gate、metrics
和 restore 流水线。R1–R3 已完成前两种入口；T055 只完成第三种入口的 adapter 接入。

在现有 `python -m rtl_obfuscator.rewrite` CLI 中扩展已冻结的 `encrypt-vnext`，使其接受
`--project-root <dir> --top <module>`；同时让已冻结的 `decrypt-vnext` 能恢复
`source_set.origin=project-root` 的 T055 report。project-root 必须复用 T052/T053/T054 的
同一 orchestration、mapping、gate、metrics 和 restore 实现，不得形成第三套业务链路。

明确边界：

- 旧 `encrypt-project`、`decrypt-project`、legacy inventory 和 mapping v1/v2/v3/v4 行为保持不变；
- 不新增 category、inventory collector、mapping schema、rate 算法或 gate-audit 分支；
- 不修改 fixture、Formal 脚本或 RISC-V-Vector 流程；
- R5 legacy 删除、全量发布验收和 RISC 专项 Formal 不属于 T055。

## 2. 固定 CLI 接口

### 2.1 vNext 加密

`encrypt-vnext` 的输入三选一：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-vnext \
  --project-root <project-root> \
  --top <module> \
  [--include-dir <dir> ...] \
  [--define <NAME[=VALUE]> ...] \
  [--category signals|parameters|genvars ...] \
  [--abi-category parameters ...] \
  [--encryption-rate <rate>] \
  [--name-length <int>] \
  --output-dir <gate-dir> --map <orchestration-report.json> --metrics <metrics.json>
```

固定语义：

- `--input`、`--filelist`、`--project-root` 必须恰好提供一个；project-root 模式禁止
  `--source-root`；
- project-root 模式必须提供合法 `--top`，include dirs 和 defines 直接进入既有
  `from_project_root()`；
- `--category` 默认 `signals parameters genvars`，`--abi-category` 默认空，只接受已冻结
  canonical category；不得因 project-root 新增 category；
- `--encryption-rate`、`--name-length`、输出路径和 JSON 行为与 T053 完全一致；
- `--output-dir` 是 actual gate，`--map` 是 `rtl-obfuscation.orchestration-vnext`，`--metrics`
  是 `rtl-obfuscation.metrics-vnext`；report 的 `source_set.origin` 必须为 `project-root`，不得
  写入本机绝对路径；
- project-root discovery 后必须把 `compile_order` 显式投影为 vNext pipeline 所需的有序
  `ordered_source_files`，保留 `origin=project-root`、top closure、include dirs、defines 和
  compile order；不得排序、扩大到 closure 外源文件或重新发现第二套文件集合。

### 2.2 vNext 恢复

沿用 T054 `decrypt-vnext` 接口，不新增 project-root 专用 decrypt 命令：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-vnext \
  --map <project-root-orchestration-report.json> \
  --gate-dir <actual-gate-dir> \
  --source-root <project-root> \
  --output-dir <restore-dir> \
  --report <restore-report.json>
```

`restore_vnext.py` 只增加对 `origin=project-root` 的既有 report hydration 支持；仍须复用 T054
mapping/execution/metrics audit，不能调用旧 decrypt 或重新生成 gate。

## 3. 等价入口与固定 oracle

只读复用 compact fixture：

```text
tests/fixtures/refactor_symbol_graph_parameters/
  closure.f
  rtl/child.sv
  rtl/shadow.sv
  rtl/top.sv
  rtl/unreachable.sv
```

固定对等输入：

- project-root：fixture root，`--top parameter_top`；
- explicit filelist：`closure.f`，`--source-root` 为同一 fixture root，`--top parameter_top`；
- `closure.f` 的文件顺序必须与 project-root top closure 的 canonical compile order 一致；
- `rtl/unreachable.sv` 不得进入 project-root gate，closure 外文件不得被改写或复制到 gate。

normalized 等价比较必须去除随机 `renamed_name`、输入/gate 派生 hash 和 top-level `origin`，
但必须保留并比较 symbol_id、category、owner、semantic owner、declaration、occurrence ranges、
action/reason、effective mapping 和 file order。不能用固定对象数量替代 normalized mapping 比较。

## 4. 实现边界

### 4.1 project-root SourceSet adapter

- 调用既有 `source_set.from_project_root()`；不得复制 `project.py` discovery、inventory 或
  classification 逻辑；
- 仅做必要的 canonical projection，使 project-root closure 的有序 `.sv` 文件进入 T052
  `run_vnext()`；保持 `origin=project-root`；
- `orchestration_vnext.py` 只允许放宽已冻结的 SourceSet origin 验证以接受该 canonical
  project-root SourceSet，不得新增 mapping/rewrite/rate/gate 分支；
- project-root 与等价 filelist 必须使用同一 categories、ABI、name factory、rate 和 T046/T050
  writer，normalized mapping 必须一致。

### 4.2 restore hydration

- `restore_vnext.py` 只扩展 source-set origin 校验和必要的 portable report projection；
- report、source manifest、gate manifest、range、metrics、rate-selected mapping 和
  byte-identical restore 的 fail-closed 语义保持 T054 不变；
- 不从 project root 重新生成名称或 mapping，不调用 `run_vnext()`、T050 writer、legacy decrypt
  或旧 mapping loader。

### 4.3 旧路径隔离

测试必须确认 project-root `encrypt-vnext` 不调用 `_encrypt_project()`/旧 project helper，
`decrypt-vnext` 不调用 `_decrypt_project()`；旧 `encrypt-project`/`decrypt-project` 分派仍可用。

## 5. 输出合同

project-root `encrypt-vnext` 成功时：

1. gate 只包含 top closure 的 physical `.sv`/`.svh` files 和 canonical `design.f`；
2. `mapping`、`mapping_execution`、`metrics`、可选 `rate_metrics` 的 schema 与 T053 相同，
   top-level `source_set.origin=project-root`；
3. `strict_compile_passed=true`，restore/metrics audit 为 verified，stdout 为
   `rtl-obfuscation.cli-vnext` portable summary；
4. project-root rate path 的 `rate_unselected`、effective coverage 和 manifest order 与显式
   filelist path 的 normalized 结果一致。

project-root `decrypt-vnext` 成功时沿用 T054：输出 physical files byte-identical、portable
`rtl-obfuscation.restore-vnext` report 和 stdout summary，不额外发布 `design.f`。

## 6. 稳定错误与失败边界

沿用 T053/T054 稳定错误，不新增 project-root 专用兼容码：

- CLI 输入、三选一、缺失 top、source-root 冲突、非法 category：`CLI_VNEXT_INPUT_INVALID`；
- 输出已存在、路径重叠、无法发布：`CLI_VNEXT_OUTPUT_INVALID`；
- orchestration/discovery/gate/restore 审计失败：`CLI_VNEXT_ORCHESTRATION_INVALID`；
- 非法 rate：`CLI_VNEXT_RATE_INVALID`；
- report/JSON/原子 IO 失败：`CLI_VNEXT_IO_ERROR`；
- decrypt report/source 校验、gate/hash/range/metrics 失败继续沿用 T054 的
  `RESTORE_VNEXT_INPUT_INVALID`、`RESTORE_VNEXT_REPORT_INVALID`、`RESTORE_VNEXT_GATE_INVALID`、
  `RESTORE_VNEXT_OUTPUT_INVALID` 和 `RESTORE_VNEXT_IO_ERROR`。

任何失败都不得留下 gate、map、metrics、restore 或临时 publish 目录；不得修改 source root、
输入 filelist、旧 mapping 或用户已有输出。

## 7. 允许修改的文件

- `rtl_obfuscator/rewrite.py`：扩展 `encrypt-vnext` project-root parser/adapter，保持旧 CLI 分派；
- `rtl_obfuscator/orchestration_vnext.py`：仅接受 canonical project-root SourceSet origin，不新增流水线分支；
- `rtl_obfuscator/restore_vnext.py`：允许 project-root report hydration，保持 T054 audit 语义；
- `tests/test_project_root_vnext.py`：project-root/filelist 等价、rate/no-rate、restore、Formal 正负例和失败边界；
- `README.md`：记录 vNext project-root 用法及与旧 `encrypt-project` 的边界；
- `docs/tasks/T055_project_root_vnext.md`：状态、执行记录和主 Agent验收记录。

不得修改 `rtl_obfuscator/project.py`、`rtl_obfuscator/source_set.py`、任何 fixture、Formal 脚本、
legacy implementation 或其他路径。需要修改允许列表外文件时，先在合同记录偏差并停止。

## 8. 固定测试 oracle

目标 unittest 必须覆盖：

1. project-root no-rate 与等价 `closure.f` filelist 的 normalized mapping/source file order 一致；
2. project-root rate=`0.35` 的 actual gate、portable report、`decrypt-vnext` restore 和
   `rate_unselected`/metrics/manifest 审计；
3. project-root actual selected gate 的 Formal 正例：gold=`closure.f`、top=`parameter_top`、
   seq=`5`，JSON 含 `formal_equivalence=pass`；
4. 从该 actual project-root gate 复制 gate，只插入一个 ASCII `~`，负例 strict compile 仍为 0/0，
   Formal 非 0 且包含 `unproven` 和 `equiv_status -assert`；
5. closure 外 `unreachable.sv` 不进入 gate，三选一/缺失 top/路径 overlap/discovery failure
   fail-closed 且无部分输出；
6. project-root vNext 不调用旧 project encrypt/decrypt、T052/T050 重新生成路径，旧命令分派未改变。

unittest 内部必须通过独立子进程调用 actual CLI 和 Formal；不得复制 gold、使用 identity comparison
或把 T054 restore 结果冒充 Formal。不得运行 RISC-V-Vector Formal 或 blanket discovery。

## 9. 目标验收命令

唯一验收命令：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_project_root_vnext -v
conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/rewrite.py rtl_obfuscator/orchestration_vnext.py rtl_obfuscator/restore_vnext.py tests/test_project_root_vnext.py
git diff --check HEAD
rg -x -- '- 状态：READY_FOR_REVIEW' docs/tasks/T055_project_root_vnext.md
```

第一个 unittest 必须真实执行 project-root actual gate Formal 正例和固定功能负例；主 Agent必须
独立复跑同四条命令并审查 JSON/byte identity。RISC Formal、旧全量 acceptance 和 hidden probe 不属于本任务。

## 10. 子 Agent执行记录

```text
status: NOT_STARTED
starting_head:
start_time:
starting_worktree:
baseline_command:
baseline_result:
allowed_files:
changed_files:
commands:
results:
project_root_source_set:
filelist_equivalence:
rate_no_rate:
restore_and_cleanup:
formal_positive:
formal_negative:
legacy_blocking:
formal_verification: PASS | FAIL | BLOCKED
deviations_or_blockers:
boundaries:
review_request:
```

## 11. READY_FOR_REVIEW 条件

- 状态严格为 `READY_FOR_REVIEW`，精确状态守卫通过；
- unittest、py_compile、`git diff --check HEAD` 全部通过；
- project-root 与等价 filelist normalized mapping、owner/range、file order 一致；
- no-rate/rate project-root actual gate、report、metrics、restore 和 failure cleanup 全部通过；
- actual project-root gate Formal 正例通过，固定 `~` 负例按预期失败；
- closure 外文件未进入 gate，旧命令未改变，无新增 category/inventory/mapping schema/兼容分支；
- 只修改本合同第 7 节列出的六个文件；
- 子 Agent不得设置 `ACCEPTED`、创建 R5/T056、commit 或 push。

## 12. 主 Agent验收边界

主 Agent只独立复跑第 9 节四条命令，审查 project-root/filelist normalized 等价、actual gate、
Formal 正负例、T054 restore、路径失败清理和旧分派隔离；不增加 RISC、旧全量回归、R5 删除任务
或隐藏 probe。全部通过后写本节验收记录并设置 `ACCEPTED`。

## 13. 主 Agent合同冻结记录（2026-07-24）

```text
status: READY
baseline_commit: 0eb059d
decision: T054 accepted; connect project-root discovery to the already verified vNext encrypt/decrypt pipeline before R5 cleanup
inputs: existing from_project_root() + T052 orchestration + T053 encrypt-vnext + T054 decrypt-vnext
oracle: project-root/filelist normalized mapping equality; closure-only actual gate; byte-identical restore; compact Formal +/-
formal_verification: required because T055 produces actual rewritten RTL
forbidden: legacy replacement, new category/inventory/mapping schema, project.py/source_set.py edits, fixture edits, R5/T056 creation
```

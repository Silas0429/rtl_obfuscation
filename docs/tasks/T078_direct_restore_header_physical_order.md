# T078：direct restore 区分编译单元与 header 物理清单

- 状态：`ACCEPTED`
- 合同版本：1.0
- 设计日期：2026-08-07
- 设计负责人：主 Agent
- 实现负责人：代码子 Agent（请求模型：Luna extra high / standard speed；当前执行器无 Luna，实际配置必须如实记录）
- 前置任务：T077 `ACCEPTED`，交付提交 `5616ccac3f7141afda9a2eef7d563099fc381de4`
- 设计基线 HEAD：`5616ccac3f7141afda9a2eef7d563099fc381de4`
- 任务类型：persistent direct restore 不变量修复；不改变 mapping、rewrite 或 gate bytes

## 1. 单一目标

修复含 `.svh` 物理文件的有效 gate 无法通过公开 `rtl_decrypt` 恢复的问题。

`SourceSet.compile_order` 只包含独立 SystemVerilog 编译单元；`included_files` 是需要参与输入/gate
manifest、hash、篡改审计和逐字节恢复的物理 header，但不得被强制加入 `design.f`。T078 只把这两个
顺序合同分开；任何重复、交叉、缺失、重排或 hash 不一致仍必须原子失败。

## 2. 起始状态与已冻结诊断

```text
branch: main
HEAD/origin/main: 5616ccac3f7141afda9a2eef7d563099fc381de4
worktree: clean
active implementation tasks: none
restore/public baseline: 19/19 PASS
```

主 Agent 已运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_restore_vnext tests.test_public_cli -v
```

结果：exit 0，Ran 19 tests，OK。

已冻结最小诊断使用第 3 节 fixture：

```text
public encrypt: exit 0
summary: files=2, mapping_records=4, modified_tokens=3
strict_compile_passed=true, restored_byte_identical=true
mapping: 1 signals rename + selected-top module/2 ports preserve
public rtl_decrypt: exit 1, RESTORE_VNEXT_INPUT_INVALID, output absent
internal RestoreVNextError.message: source_set physical order is invalid
positive actual-gate Formal: exit 0, complete JSON pass
fixed ~ negative: exit 1, 1 unproven cell, contains equiv_status -assert
```

外部稳定性仓库 `/Users/lufengchi/Desktop/workspace/rtl_obfuscation_realworld_stability` 在提交
`b99f5e43128964cc78a5c123a31f84e46df76934` 保存了 8 个 pinned 工程、168 个 ABI/非 ABI profile；
该矩阵使用的产品提交是 `4af1772905497d1524f7c33c9ef38eb34f966574`。当前 T075–T077 后重放得到：

- riscv-dbg `abi__modules` 已由 T076 从 `FAIL_STRICT` 收敛为 `PASS_EFFECTIVE`，4 个 module records
  rename、strict/restore 通过；
- Ibex 已由 T077 越过原 `conflicting quarantine reasons` 建图拒绝；`abi__modules` 与
  `non_abi__instances` 分别产生 18/37 个 rename 且 strict compile 通过，但公开 restore 均以本任务
  的错误原子失败；
- Ibex `abi_group` / `non_abi_group` 仍为独立 `FAIL_STRICT`，不属于 T078。

## 3. 冻结 compact fixture

子 Agent 必须逐字创建：

```text
tests/fixtures/t078_direct_restore_headers/design.f
tests/fixtures/t078_direct_restore_headers/defs.svh
tests/fixtures/t078_direct_restore_headers/top.sv
```

`design.f`：

```text
defs.svh
top.sv
```

`defs.svh`：

```systemverilog
`ifndef T078_DEFS_SVH
`define T078_DEFS_SVH
`define T078_UNUSED_WIDTH 8
`endif
```

`top.sv`：

```systemverilog
module t078_header_top (
    input  logic data_i,
    output logic data_o
);
    logic data_q;
    assign data_q = data_i;
    assign data_o = data_q;
endmodule
```

固定 public profile：filelist、top=`t078_header_top`、category=`signals`、无 include-dir/define/rate。

## 4. 最小实现合同

只修改 `restore_vnext._load_orchestration_gate_inputs_vnext()` 的 persisted SourceSet 顺序审计：

1. `ordered_source_files` 必须非空、无重复；
2. `included_files` 必须无重复，且与 `ordered_source_files` 不相交；
3. `compile_order` 必须逐项等于 `ordered_source_files`，不得附加 header、缺项或重排；
4. physical file order 固定为 `ordered_source_files + included_files`，用于 gate file set、outer/effective/
   execution/restored manifests、hash 审计、range 审计与最终恢复；
5. `gate/design.f` 仍必须逐字等于 `compile_order`，因此只列 `top.sv`；gate 仍必须实际包含并审计
   `defs.svh`；
6. 非 canonical persisted SourceSet 继续使用现有稳定码 `RESTORE_VNEXT_INPUT_INVALID`；gate 文件、hash
   或 `design.f` 篡改继续使用 `RESTORE_VNEXT_GATE_INVALID`；report/schema 篡改保持既有码；
7. 不读取原始 source tree，不重建 orchestration，不改变 report schema、字段、manifest 顺序或错误码。

不得通过删除 header、把 header 写入 `design.f`、跳过 hash、放松 gate file set 或回退到需要
`--source-root` 的 legacy restore 来制造成功。

## 5. 冻结 machine oracle

目标 unittest 至少证明：

- `ordered_source_files=[top.sv]`、`included_files=[defs.svh]`、`compile_order=[top.sv]`；
- mapping input/gate/restored manifest 顺序均为 `[top.sv, defs.svh]`；
- public encrypt 固定 `files=2`、4 records、1 signals rename、3 edits，strict 和 internal restore true；
- public `rtl_decrypt` 不需要 original source，exit 0，恢复 `top.sv` 与 `defs.svh` 逐字节相等，且不发布
  `design.f`；可选 restore report 的 manifest equality/byte identity 为 true；
- direct API 与 public CLI 共用同一 gate audit，不调用 orchestration regeneration；
- persisted compile_order 附加 header、source/header 重复或交叉、`design.f` 附加 header、header bytes
  篡改、unexpected gate file 均以冻结错误类别失败，输出/report 不发布；
- actual gate strict compile 0/0 + 0/0；compact Formal top=`t078_header_top`, seq=5 正例 exit 0 JSON pass；
- 固定负例只在 actual gate 副本唯一 `assign data_o = ` 后增加 `~`；其 strict compile 0/0 + 0/0，
  Formal 非零且含 `unproven` 与 `equiv_status -assert`；
- 外部 Ibex pinned view 的 `abi__modules` 与 `non_abi__instances` 均为 `PASS_EFFECTIVE`、strict true、
  public restore byte-identical，rename counts 分别为 18/37；不宣称 group 或完整 Ibex 支持。

## 6. 明确不包含

- 不修改 SourceSet discovery、SourceCatalog、SymbolGraph、policy、mapping、rewrite、rate、metrics、CLI
  参数或 Formal；
- 不把 `.svh` 当独立编译单元，不扩展 Verilog `.v` 产品范围；
- 不修 Ibex ABI/non-ABI group strict failure，不修 riscv-dbg 其他 category failure；
- 不更新或修改相邻 real-world stability 仓库、第三方 checkout 或 pinned input；
- 不运行 RISC-V-Vector Formal、blanket discovery 或历史 acceptance driver。

## 7. 允许修改

```text
docs/tasks/T078_direct_restore_header_physical_order.md
rtl_obfuscator/restore_vnext.py
tests/test_t078_direct_restore_headers.py
tests/fixtures/t078_direct_restore_headers/design.f
tests/fixtures/t078_direct_restore_headers/defs.svh
tests/fixtures/t078_direct_restore_headers/top.sv
docs/development/future_work.md
```

除此之外不得修改、删除、格式化或生成仓库文件。外部工程和所有 gate/restore/log 只能写入新的
`/private/tmp` 目录。

## 8. 子 Agent 执行顺序

1. 完整阅读 AGENTS、T078、task workflow、subagent protocol、T061、restore/public tests、future work
   和 Formal 文档；
2. 确认 HEAD/origin/main、clean worktree、唯一 T078 READY；第一次实现编辑前设置 `IN_PROGRESS`，记录
   实际模型、允许文件和 19-test baseline；
3. 逐字创建 fixture 和目标测试，产品修改前记录 compact public decrypt 的冻结失败；
4. 只实现第 4 节顺序/manifest 审计；先跑目标测试，再跑 regression 和外部 Ibex delta replay；
5. 运行第 9 节五条验收，记录 exact commands、counts、strict/restore、篡改矩阵及 Formal 正负证据；
6. 确认允许路径外零修改，设置 `READY_FOR_REVIEW` 后停止；不得 stage、commit、push、设置
   `ACCEPTED` 或创建 T079。

如果 SourceSet 的实际合法 `compile_order` 不等于 `ordered_source_files`、修复需要 schema/API/允许列表外
文件、外部 pin 不匹配，或 positive Formal 不通过，必须记录最小事实并停止，不得改 fixture/oracle。

## 9. 唯一验收命令

Baseline（实现前一次）：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_restore_vnext tests.test_public_cli -v
```

实现后五条：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t078_direct_restore_headers \
  tests.test_restore_vnext tests.test_public_cli -v

external_root=/Users/lufengchi/Desktop/workspace/rtl_obfuscation_realworld_stability
test "$(git -C "$external_root" rev-parse HEAD)" = b99f5e43128964cc78a5c123a31f84e46df76934
test "$(git -C "$external_root/repos/ibex" rev-parse HEAD)" = 3250d99482f1963891ef1cf19356eeaeeaa71d30
replay_root=$(mktemp -d /private/tmp/t078-ibex-replay.XXXXXX)
sh "$external_root/projects/ibex/commands/materialize.sh" "$external_root" "$replay_root/source"
conda run -n rtl_obfuscation python "$external_root/category_matrix_runner.py" \
  --study-root "$external_root" --project ibex \
  --source-root "$replay_root/source" \
  --filelist "$external_root/projects/ibex/prepared/design.f" --top ibex_top \
  --include-dir vendor/lowrisc_ip/ip/prim/rtl \
  --include-dir vendor/lowrisc_ip/dv/sv/dv_utils --include-dir rtl --define SYNTHESIS \
  --output-root "$replay_root/matrix" \
  --profiles abi__modules,non_abi__instances --formal-policy none
jq -e '
  (.results | length) == 2 and
  all(.results[];
    .classification == "PASS_EFFECTIVE" and
    .strict_compile_passed == true and
    .restore_byte_identical == true and
    .gate_published == true and
    .decrypt_exit_code == 0 and
    .restore.files == 45) and
  ([.results[] | {profile, renamed: .effective_renamed_records}] | sort_by(.profile)) ==
    [{profile:"abi__modules",renamed:18},{profile:"non_abi__instances",renamed:37}]
' "$replay_root/matrix/matrix.json"

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/restore_vnext.py tests/test_t078_direct_restore_headers.py

git diff --check HEAD

rg -x -- '- 状态：`READY_FOR_REVIEW`' \
  docs/tasks/T078_direct_restore_header_physical_order.md
```

目标 unittest 内部必须执行 compact actual-gate strict compile、restore、Formal 正例与固定功能负例；
不得 identity/copy-gold 或弱化 `equiv_status -assert`。外部 replay 只验证 strict/restore delta，不把
Formal `none` 描述为功能等价证明。

## 10. Formal verification 记录

```text
formal_verification: PASS | FAIL | BLOCKED
gold: tests/fixtures/t078_direct_restore_headers
gate: <actual public rtl_encrypt output>
top: t078_header_top
seq: 5
positive_command: <exact command>
positive_exit_code: <integer>
positive_result: <complete stdout JSON>
negative_gate: <actual gate copy with only frozen top assign mutation>
negative_compile: <catalog/top overlay counts>
negative_command: <exact command>
negative_exit_code: <nonzero integer>
negative_result: <unproven / equiv_status -assert summary>
external_formal: N/A; T078 does not change external gate bytes and Ibex gold is outside routine compact proof
```

## 11. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
actual_model: gpt-5.6-sol / xhigh；当前调度器未提供 Luna 模型或 standard speed 参数，未声称使用 Luna
starting_head: c13db554a938d7ee566a732cf79c8cd3074bb543；origin/main 同提交；worktree clean
allowed_files_check: PASS；合同第 7 节七个允许路径无既有未提交修改；唯一活动实现任务为 T078
baseline: PASS；`conda run -n rtl_obfuscation python -m unittest tests.test_restore_vnext tests.test_public_cli -v`；exit 0；Ran 19 tests；OK
pre_fix_characterization: PASS；public encrypt exit 0，files=2/mapping_records=4/modified_tokens=3/strict=true/internal restore=true；persisted ordered=[top.sv]、included=[defs.svh]、compile=[top.sv]，五组 manifests 均按 [top.sv, defs.svh]；public decrypt exit 1 且 stderr `error: RESTORE_VNEXT_INPUT_INVALID`、输出不存在；direct API 精确 code=`RESTORE_VNEXT_INPUT_INVALID`、message=`source_set physical order is invalid`
changed_files: docs/tasks/T078_direct_restore_header_physical_order.md；rtl_obfuscator/restore_vnext.py；tests/test_t078_direct_restore_headers.py；tests/fixtures/t078_direct_restore_headers/{design.f,defs.svh,top.sv}；docs/development/future_work.md
commands: 第 9 节 baseline 一次；目标测试首次暴露测试自身对既存 TemporaryDirectory 重复 mkdir 后修正；随后目标测试通过；最终逐条执行第 9 节五条验收（外部 replay 命令末尾另打印 replay_root 供记录）
results: 项目内目标+回归最终 exit 0，Ran 27 tests，OK；external pinned HEAD/ibex HEAD checks 通过，materialize/runner exit 0，冻结 jq 返回 true；py_compile exit 0；git diff --check HEAD exit 0；READY_FOR_REVIEW guard exit 0
test_rework: 首次目标 unittest 的 7 个行为测试均通过，仅 `test_public_encrypt_persists_compile_and_physical_orders` 因 helper 对已存在 TemporaryDirectory 调用 `mkdir()` 抛 FileExistsError；只将 test helper 改为 exist_ok=True，未修改 fixture、产品行为或 oracle，最终 8/8 与合并 27/27 均通过
schema_or_behavior: 不改变 report/schema/manifest 字段或顺序；只在 `_load_orchestration_gate_inputs_vnext()` 将 persisted compile-unit order 与 physical order 分离：ordered_source_files 非空无重复、included_files 无重复且不交叉、compile_order 精确等于 ordered_source_files，physical files 精确拼接 ordered+included；后续 gate set、五组 manifests、hash、range 与 restore 审计全部继续复用该 physical 顺序
compact_oracle: PASS；source_set ordered=[top.sv]、included=[defs.svh]、compile=[top.sv]；五组 manifests=[top.sv,defs.svh]；public encrypt files=2、records=4、signal rename=1、edits=3、strict/internal restore true；public decrypt 无 original source/report exit 0，只发布 byte-identical top.sv/defs.svh 且不发布 design.f；可选 report manifest equality true；direct API/public adapter 均只调用共享 gate audit 且不调用 orchestration regeneration
tamper_matrix: PASS；persisted compile_order 附加 header、ordered duplicate、included duplicate、source/header 交叉均为 RESTORE_VNEXT_INPUT_INVALID；gate design.f 附加 header、header bytes 篡改、unexpected gate file 均为 RESTORE_VNEXT_GATE_INVALID；所有失败无 traceback、output/report 均不发布
external_replay: PASS；stability HEAD=b99f5e43128964cc78a5c123a31f84e46df76934，Ibex HEAD=3250d99482f1963891ef1cf19356eeaeeaa71d30；replay_root=/private/tmp/t078-ibex-replay.3wlkF9；abi__modules 与 non_abi__instances 均 PASS_EFFECTIVE/strict true/restore byte-identical/gate published/decrypt exit 0/restore files 45，effective rename 分别 18/37；runner formal-policy none 未描述为等价证明
documentation: PASS；future-work 记录 compile_order 与 included_files 的持久化审计边界，并明确 Ibex abi_group/non_abi_group strict failure 不属于 T078
boundaries: 不修改 SourceSet/graph/policy/mapping/rewrite/CLI/Formal，不把 header 加入 design.f，不读取 original source，不修 Ibex group；未运行 RISC-V-Vector Formal、blanket discovery 或历史 driver；外部仓库/pinned input 未修改
cleanup_candidates: none
formal_verification: PASS
gold: tests/fixtures/t078_direct_restore_headers
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t078-formal-positive-chke4v7s/encrypt/gate；actual public rtl_encrypt output，3 个真实 edits
top: t078_header_top
seq: 5
positive_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t078_direct_restore_headers/design.f --gold-root tests/fixtures/t078_direct_restore_headers --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t078-formal-positive-chke4v7s/encrypt/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t078-formal-positive-chke4v7s/encrypt/gate --top t078_header_top --seq 5
positive_exit_code: 0
positive_result: {"formal_equivalence":"pass","gate":"/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t078-formal-positive-chke4v7s/encrypt/gate","gold":"tests/fixtures/t078_direct_restore_headers","seq":5,"top":"t078_header_top"}
negative_gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t078-formal-negative-bc83nmr_/negative；actual gate 副本且只含冻结 `assign data_o = ~` 功能变更
negative_compile: catalog 0/0；top overlay 0/0
negative_command: /Users/lufengchi/anaconda3/envs/rtl_obfuscation/bin/python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t078_direct_restore_headers/design.f --gold-root tests/fixtures/t078_direct_restore_headers --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t078-formal-negative-bc83nmr_/negative/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t078-formal-negative-bc83nmr_/negative --top t078_header_top --seq 5
negative_exit_code: 1
negative_result: `equiv_status -assert`；1 unproven cell remains in module equiv；ERROR 报告 unproven equivalence
external_formal: N/A；T078 不改变外部 gate bytes，Ibex gold 位于 routine compact proof 之外，冻结 replay 使用 formal-policy none
review_request: 请主 Agent 独立复跑第 9 节、审计 persisted SourceSet/manifest 顺序与 external delta 并决定验收；子 Agent 未 stage、commit、push、设置 ACCEPTED 或创建 T079
```

## 12. 主 Agent 验收

```text
review_date: 2026-08-07
reviewer: 主 Agent
starting_head: c13db554a938d7ee566a732cf79c8cd3074bb543；origin/main 同提交
allowed_files: PASS；最终 diff 精确为第 7 节七个允许路径，无额外 tracked/untracked 文件
implementation_review: PASS；产品 diff 只在 persisted gate loader 将 compile units 与 included
  physical headers 分开，并增加 source/header duplicate/intersection fail-closed；未修改 schema、
  mapping、rewrite、gate generation、CLI 或 Formal
target_and_regression: PASS；第 9 节合并 unittest exit 0；Ran 27 tests；OK
compact_oracle: PASS；files=2、mapping_records=4、1 signals rename、3 edits；source_set
  ordered=[top.sv]、included=[defs.svh]、compile=[top.sv]；五组 manifests=[top.sv,defs.svh]
strict_and_restore: PASS；actual gate catalog/top overlay 0/0 + 0/0；公开 direct restore 不读取
  original source，恢复 top.sv/defs.svh byte-identical 且不发布 design.f
tamper_review: PASS；非 canonical persisted SourceSet 使用 RESTORE_VNEXT_INPUT_INVALID；design.f、
  header bytes/hash 和 file-set 篡改使用 RESTORE_VNEXT_GATE_INVALID；所有失败无部分输出/report
formal_positive: PASS；Main-Agent actual gate
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t078-formal-positive-nsuzvhxf/encrypt/gate；
  top=t078_header_top；seq=5；exit 0；complete JSON formal_equivalence=pass
formal_negative: PASS as expected negative；Main-Agent actual-gate copy
  /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t078-formal-negative-k_40q88u/negative；
  only frozen `assign data_o = ~` mutation；strict compile 0/0 + 0/0；exit 1；1 unproven cell，
  output contains `unproven` and `equiv_status -assert`
external_replay: PASS；stability HEAD=b99f5e43128964cc78a5c123a31f84e46df76934，Ibex
  HEAD=3250d99482f1963891ef1cf19356eeaeeaa71d30；Main-Agent replay root
  /private/tmp/t078-ibex-replay.BuKo3Y；abi__modules/non_abi__instances 均 PASS_EFFECTIVE、strict
  true、restore byte-identical、decrypt exit 0、45 files；rename=18/37，modified_tokens=53/37
py_compile: PASS；第 9 节命令 exit 0
diff_check: PASS；git diff --check HEAD exit 0
ready_for_review_guard: PASS；精确 guard 在本次 ACCEPTED 状态变更前 exit 0
documentation: PASS；future work 精确记录 T078，并保留 Ibex groups 与其他工程输入边界
forbidden_runs: 未运行 RISC-V-Vector Formal、blanket discovery 或历史 acceptance driver；未修改外部仓库
decision: ACCEPTED；T078 修复公开 direct restore 的 header physical manifest 不变量，且保持 fail-closed
delivery_commit: current acceptance commit；exact hash 在提交后报告并冻结进后继合同
push: pending current acceptance commit
successor: 主 Agent 只在本 acceptance commit 推送后冻结下一任务
```

# T078：direct restore 区分编译单元与 header 物理清单

- 状态：`READY`
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
status: not started
actual_model:
starting_head:
changed_files:
commands:
results:
schema_or_behavior:
boundaries:
formal_verification:
review_request:
```

## 12. 主 Agent 验收

待子 Agent 设置 `READY_FOR_REVIEW` 后，由主 Agent独立执行第 9 节并填写。

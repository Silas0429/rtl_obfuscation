# T121：精确放行供应商诊断并仅改写指定目录

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 起始 HEAD：`e3c388187b4f58728c8279fa698560f43861cfb1`（T120 已 `ACCEPTED`）
- 任务类型：filelist PySlang compatibility + diagnostic-file read-only firewall + rewrite-root allowlist
- 服务器环境：PySlang `11.0.0`

## 1. 已确认的现状与基线

真实 filelist 已通过 `-v`、`.vic`、多物理根和输出路径处理，但 authoritative PySlang compilation
在供应商标准单元与 memory model 上产生 512 条 blocking parse diagnostics：

- 384 条 `DiagCode(IfNoneEdgeSensitive)`，源码形状为
  `ifnone (posedge A0 => (AX+:1'b1)) = 0;`；
- 128 条 `DiagCode(UnknownDirective)`，实际 directive 只来自：
  `protect`、`endprotect`、`suppress_faults`、`enable_portfaults`、`disable_portfaults`、
  `nosuppress_faults`。

主 Agent 用本地同版本 PySlang 复现：这些 diagnostics 被标记为 error，但 module、instance、port 和
timing-path 的主要语义节点仍可建立。当前 `compile_pyslang_source_set()` 把全部 syntax-tree error 放入
`parse_errors`，authoritative SourceSet 和 SourceCatalog 因此在重命名前停止。

真实 filelist 审计还确认：

- `-v PATH` 和裸 `PATH` 同时用于普通源码与外部模型，不能据此判断文件归属；
- 已知供应商来源中至少约 811 个 source entry 是裸 `.v`，因此也不能只识别 `-v`；
- 有一个已确认的 source-suffix include：外层 `.v` 使用 `` `include "vcs/DW_exp2.v"``。当前
  include closure 只记录 header/context suffix，原始编译可找到该文件，但 gate 不会复制它，后续 strict
  compile 存在确定性 `MissingInclude` 风险。

起始 HEAD 的冻结基线：

```text
39 targeted regression tests: PASS
T117 -v/bare SourceSet report equality: PASS
T117 actual-gate Formal positive and fixed negative: PASS
T120 actual-gate Formal positive and fixed negative: PASS
target UnknownDirective / IfNoneEdgeSensitive diagnostics: blocking before T121
```

## 2. 单一目标

为公共 filelist 流程增加两层同时生效的安全边界：

1. 只精确放行第 1 节确认且能回到预期物理字节的供应商兼容诊断；产生这些诊断的整个物理文件仍参与
   PySlang compile/elaboration，但禁止任何改写。
2. 增加可重复的 `--rewrite-root DIR`；提供后，只有位于至少一个指定目录内、且没有供应商兼容诊断的
   filelist source unit 才有资格改写。目录外文件继续参与语义绑定但保持只读。

同时补齐已在真实输入中确认的 `.sv/.v` include-only 物理依赖：复制、校验和恢复，但不作为独立 source
unit 编译，也不进入 rename target。

## 3. 精确诊断合同

### 3.1 允许继续的诊断

1. `DiagCode(IfNoneEdgeSensitive)` 仅在诊断位置能可靠映射到普通物理文件，且该字节位置以完整
   `ifnone` token 开始时允许；identifier 边界必须成立。
2. `DiagCode(UnknownDirective)` 仅在诊断所在物理行去除行首/行尾水平空白后精确为以下之一时允许；
   可有行尾 `//` comment，但不得有参数、宏实参或其他 token：
   - `` `protect``
   - `` `endprotect``
   - `` `suppress_faults``
   - `` `enable_portfaults``
   - `` `disable_portfaults``
   - `` `nosuppress_faults``
3. 同一物理文件中的 `protect/endprotect` 必须按顺序一一配对、不得嵌套；允许多组顺序配对。
4. 允许项从 blocking `parse_errors` 移入独立的 `vendor_compatibility_errors`；共享
   `nonblocking_errors` 可同时包含它们和现有 `MissingTimeScale`，但两类原因不得混淆。
5. parse/semantic 去重必须继续使用全部原始 syntax error key，防止已放行的 parse diagnostic 又进入
   `semantic_errors`。
6. diagnostic 位于 macro/virtual buffer、路径不在 SourceSet、offset 越界、源码读取失败或字节形状不匹配
   时一律 fail closed。

### 3.2 必须继续阻塞

- 任意其他 `UnknownDirective`，包括普通未定义宏；
- 六个名称后带参数、宏实参或额外 token；
- 未配对、逆序或嵌套的 `protect/endprotect`；
- `IfNoneEdgeSensitive` 的位置不是预期完整 `ifnone` token；
- `ExpectedExpression`、`UnknownModule`、`InvalidSpecifySource` 及其他现有 parse/semantic error；
- 真正 encrypted/protected opaque payload 产生的任何额外错误。

精确放行只说明 PySlang 语义结构足以继续建立，不声明这些语法符合所有仿真器，也不授权改写相关文件。

## 4. `--rewrite-root` 合同

1. 仅公共 `--filelist` 加密模式接受可重复的 `--rewrite-root DIR`；single-file、project-root 和 decrypt
   模式提供该参数必须在创建输出前以 `CLI_VNEXT_INPUT_INVALID` 拒绝。
2. `DIR` 必须是已存在目录。相对路径按调用进程当前目录解析；内部使用 `expanduser().resolve()` 后的
   canonical path，不做字符串前缀判断，不写死任何服务器目录名。
3. 每个 root 必须位于推导后的 SourceSet root 内，并至少包含一个 filelist 中显式列出的
   `ordered_source_files`；不存在、越界、只包含 header/context/include-only 文件或零命中时拒绝。
4. 多个 root 取并集；规范化重复项去重。父子 root 同时提供不改变结果。
5. 提供至少一个 root 后，source unit 只有在其 canonical physical path 位于某个 root 内时才有资格
   rename；目录外 source unit 的 record 稳定 preserve reason 为 `outside_rewrite_root`。
6. 未提供 `--rewrite-root` 时，保持 T120 以前“全部 filelist source unit 可参与改写”的兼容行为；但产生
   第 3 节兼容诊断的文件仍按第 5 节强制只读。README 必须明确真实混合工程推荐显式提供该参数。
7. `-v PATH` 仍只是裸 `PATH` 的 filelist 语法别名：不得保留用于只读判断的 `-v` provenance，不得因
   `-v` 改变 SourceSet report、compile order、rename eligibility 或输出 `design.f`。
8. root 只控制“能否改写”，不控制“是否编译”。目录外 source、top 所需供应商定义和 include 依赖仍
   必须保留在 compilation、manifest、gate 与 restore 中。

## 5. Read-only firewall

1. `readonly_vendor_files` 是 catalog/top compilation 中实际产生第 3.1 节
   `vendor_compatibility_errors` 的物理文件集合；不得按路径、文件名、module 名、文件大小或出现次数猜测。
2. `readonly_include_files` 是 include closure 中不是显式 standalone source unit 的物理文件；包括原有
   `.svh/.vh/.h` 与第 6 节新增的 include-only `.sv/.v`。
3. RenameIndex 完成普通 declaration/occurrence 物理绑定后、执行 name-completeness 前应用 firewall：
   - 任一 record 的 declaration 或任何 occurrence 位于 `readonly_vendor_files` 时，整条 record preserve，
     reason 为 `readonly_vendor_model`；
   - 否则，提供 rewrite roots 后，任一 declaration/occurrence 位于所有 roots 之外时，整条 record
     preserve，reason 为 `outside_rewrite_root`；
   - include-only 文件不得出现 rename edit；若 record 跨入该文件，整条 record preserve。
4. 已经因更早、更具体的 binding/unsupported 原因被 preserve/unsupported 的 record 保持原原因；
   firewall 只把仍为 eligible 的 record 降为 preserve。
5. read-only 文件中实际 edit 必须为 0，gate SHA-256 必须等于 input SHA-256；目录内普通用户 RTL 必须
   仍有真实 rename 和 `modified_tokens > 0`，不得把整个 category 或工程降级。
6. strict gate reanalysis 必须使用同一精确诊断分类。gold 允许而 gate 阻塞，或 gate 出现新的诊断，均
   不得发布输出。

## 6. Source-suffix include-only 物理依赖

1. filelist bounded include closure 允许发现由已列 source/header/context 直接或递归引用的 lower-case
   `.sv/.v` 文件；只接受现有 local-directory / `+incdir+` 有序搜索范围内的唯一物理解析结果。
2. source-suffix include 只加入 `included_files` 物理清单，不加入 `ordered_source_files` 或
   `compile_order`，canonical gate `design.f` 不单独列出它。
3. include-only `.sv/.v` 必须复制到 gate、进入 input/gate/restored manifest、逐字节恢复，并保持只读。
4. 同一路径已经是显式 standalone source unit 时不得重复加入 `included_files`；现有 duplicate filelist
   检查不变。
5. 同名候选无法唯一确定、解析越界或依赖文件缺失时 fail closed；不实现 glob、`-y`、`+libext+` 或
   simulator lazy library search。

## 7. 风险、阶段边界与未来工作

本任务同步 README、重命名表、项目结构和 future work，明确：

- `--rewrite-root` 是用户所有权白名单，不是自动供应商识别；目录放得过大会授权更多文件，放得过小会
  降低覆盖率，但不会破坏目录外文件；
- 本任务不验证或改写 SDF、Liberty、网表之外的 testbench、VPI/PLI、fault simulation 配置或层次路径；
- 不生成 blackbox/module-interface stub，不跳过 top 使用的 module definition；
- 不实现完整 vendor parser、真实 `-v` lazy search、`-y`、`+libext+`、library map、PVT 选择、duplicate
  definition resolution、encrypted protect payload、UDP/primitive 或新的 simulator directive；
- 新供应商诊断默认继续阻塞；只有独立证据证明物理位置和语义结构可恢复后才能另立任务增加；
- 没有特殊诊断、但位于 rewrite root 内的第三方代码仍会被加密。用户必须把 root 设为真正拥有并允许
  改写的最小目录；工具不根据版权头或路径猜测归属；
- 服务器后续验证不依赖 Yosys。本任务 compact Formal 只满足仓库对实际改写 RTL 的验收规则，不证明
  真实供应商 timing/SDF/fault 行为等价。

服务器进入下一轮测试前必须从 `mapping_execution.per_file_mapping` 审计：

- 有 landed `rename` range 的每个文件都位于指定 rewrite roots；
- `readonly_vendor_model`、`outside_rewrite_root` 文件没有 landed edit，且 input/gate hash 相等；
- include-only `.v` 存在于 gate、未进入 `design.f`、hash 不变；
- actual simulator compile/elaboration、必要的 SDF/timing/fault 流程由服务器环境另行验证。

## 8. Compact fixture 与机器验收

新增 `tests/fixtures/t121_vendor_model_readonly/`，至少包含：

- `project/`：普通 top/child，必须真实改名；其中一个 clean source 在 `-v` filelist 版本中列出，证明
  `-v` 与裸路径改写结果一致；
- `project/diagnostic_inside.v`：位于 rewrite root 内但包含全部六个 legacy directive 与
  edge-sensitive `ifnone`，证明诊断只读优先于目录授权；
- `external/clean_wrapper.v`：无供应商特殊语法、参与 top hierarchy，因目录外而只读；
- `external/provider.v` + `external/vcs/provider_body.v`：source-suffix include-only 依赖，证明复制、
  compile、manifest、restore 与只读；
- 一个跨目录 record，使 declaration 或 occurrence 位于目录外，证明整条 preserve。

供应商专用 construct 可放在 `` `ifndef YOSYS`` 内，使 PySlang 看到目标诊断，而 compact Formal 使用
同一 actual gate 时走功能分支；这只是本地证明隔离，不是服务器运行要求。

目标测试必须证明：

1. raw diagnostics 精确包含目标 code；blocking parse/semantic 为 0；compatibility 与
   `MissingTimeScale` 分类分离；SourceSet/SourceCatalog 成功。
2. 六个 directive 的空白、行尾 comment、多组配对和 `ifnone` token 正例通过；普通未知宏、带参数、
   未配对、嵌套、伪 token、macro/virtual location 及另一个 parse/semantic error阻塞且不发布输出。
3. 单 root、多 root、重复/嵌套 root、相对路径、lexical prefix 邻居、越界/不存在/零命中 root 精确；
   参数在非 filelist 模式拒绝。
4. diagnostic-inside、external clean、include-only 和跨目录 record 全部无 edit并报告稳定原因；目录内
   clean RTL 有 rename。`-v` 与 bare fixture 的 SourceSet report、mapping action 和 landed edits一致。
5. source-suffix include 存在于 physical manifest/gate/restore，不进入 compile order/design.f；缺失或歧义
   fail closed。
6. public `--category all --rewrite-root <project>` actual gate exit 0、schema 1/2 持久化形状不变、strict
   compile 通过、direct restore 全部物理输入逐字节相同；逐文件 report 证明所有 landed edit 均在 root。
7. compact Formal 正例 exit 0 且 JSON `formal_equivalence=pass`；复制 actual gate 后只修改用户 RTL 的
   XOR 为 OR，strict compile 仍通过而 Formal 非零并含 `unproven` / `equiv_status -assert`。

## 9. 允许修改的文件

- `README.md`
- `docs/systemverilog_renaming_table.md`
- `docs/development/project_structure.md`
- `docs/development/future_work.md`
- `docs/tasks/T121_vendor_model_readonly.md`
- `rtl_obfuscator/project_discovery.py`
- `rtl_obfuscator/source_set.py`
- `rtl_obfuscator/source_catalog.py`
- `rtl_obfuscator/rename_index.py`
- `rtl_obfuscator/rewrite.py`
- `tests/test_t121_vendor_model_readonly.py`
- `tests/fixtures/t121_vendor_model_readonly/**`

不得修改 mapping/orchestration/rewrite-vNext/restore/Formal 实现、category registry、历史任务或历史测试；
不得提交真实服务器 RTL、绝对路径或日志。

## 10. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t121_vendor_model_readonly -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_source_set tests.test_source_catalog \
  tests.test_t094_builtin_preprocessor_macros \
  tests.test_t099_filelist_compile_context \
  tests.test_t117_filelist_v_library_source \
  tests.test_t119_filelist_multi_root_output \
  tests.test_t120_explicit_vic_include_reference -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project_discovery.py rtl_obfuscator/source_set.py \
  rtl_obfuscator/source_catalog.py rtl_obfuscator/rename_index.py \
  rtl_obfuscator/rewrite.py tests/test_t121_vendor_model_readonly.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T121_vendor_model_readonly.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t121_ready_for_review=pass")'
```

## 11. Formal verification

目标测试必须从 public CLI 生成 actual gate。正例使用 compact fixture 的 gold `design.f` 与实际 gate
`design.f`、top `t121_top`、`--seq 5`；退出 0 且 JSON `formal_equivalence=pass`。负例复制 actual gate，
只把 rewrite root 内用户 RTL 的一个 XOR 改为 OR；Icarus/PySlang strict compile 通过，Formal 必须非零并
包含 `unproven` / `equiv_status -assert`。

## 12. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: e3c388187b4f58728c8279fa698560f43861cfb1
baseline: Main Agent targeted regression 39/39 PASS; local PySlang 11.0.0 probe confirmed 6 UnknownDirective + IfNoneEdgeSensitive were blocking while module/port/timing-path nodes remained present
changed_files: README.md; docs/systemverilog_renaming_table.md; docs/development/project_structure.md; docs/development/future_work.md; docs/tasks/T121_vendor_model_readonly.md; rtl_obfuscator/project_discovery.py; rtl_obfuscator/source_set.py; rtl_obfuscator/source_catalog.py; rtl_obfuscator/rename_index.py; rtl_obfuscator/rewrite.py; tests/test_t121_vendor_model_readonly.py; tests/fixtures/t121_vendor_model_readonly/**
commands: contract target unittest; frozen 39-test regression; frozen py_compile; git diff --check HEAD; exact READY_FOR_REVIEW guard
results: target 7/7 PASS; updated regression 40/40 PASS including T119; py_compile exit 0; diff check PASS; SourceSet schema 1 and mapping/mapping-execution schema 2 persisted shapes unchanged; -v/bare SourceSet report, decisions and landed source ranges equal
schema_or_behavior: exact physical diagnostic classifier keeps full syntax-error keys for semantic de-duplication; compatibility files and include-only files remain internal catalog state; --rewrite-root is repeatable, canonicalized and stored root-relative only in live SourceSet; record firewall runs before name completeness and preserves cross-file records transactionally
boundaries: no vendor path/name guessing; no -v provenance; no lazy library resolution, blackbox/stub, encrypted payload, UDP/primitive or new directive support; source-suffix include is physical-only and uniquely resolved; compact Yosys guard is test isolation only, while server simulator/timing/fault validation remains external as documented
cleanup_candidates: none
formal_verification: PASS
gold: tests/fixtures/t121_vendor_model_readonly via design.f
gate: /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t121-formal-6qispoex/gate-bare (public CLI actual gate)
top: t121_top
command: conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t121_vendor_model_readonly/design.f --gold-root tests/fixtures/t121_vendor_model_readonly --gate-filelist <actual-gate>/design.f --gate-root <actual-gate> --top t121_top --seq 5
exit_code: 0
result: {"formal_equivalence":"pass","seq":5,"top":"t121_top"}
negative: copied actual gate; project/top.sv XOR -> OR; PySlang blocking parse/semantic 0; Icarus strict compile exit 0; Formal exit 1 with unproven / equiv_status -assert
review_correction: PASS; permanent public-CLI case combines /Users fixture sources with a /private/var wrapper/extra source, proves inferred source_root=/, root-relative rewrite allowlist relocation, successful publish/restore, landed edits only under fixture/project, unchanged diagnostic/external/include-only/extra hashes, exact physical manifests and canonical design.f; T119 added to regression
review_request: Main Agent please independently rerun all five updated commands, inspect diagnostic-byte fail-closed rules and the new source_root=/ black-box case, verify no landed edit outside the rewrite root, and rerun the compact actual-gate positive/negative Formal
```

## 13. 主 Agent 验收

```text
main_result: PASS
reviewed_head: e3c388187b4f58728c8279fa698560f43861cfb1 + T121 working tree
review: inspected every allowed-file diff; no changes outside the frozen allowlist; persisted SourceSet schema 1 and mapping/mapping-execution schema 2 shapes remain unchanged
target_command: conda run -n rtl_obfuscation python -m unittest tests.test_t121_vendor_model_readonly -v
target_result: PASS, 7/7; includes public source_root=/ black-box, exact diagnostic fail-closed matrix, rewrite-root boundaries, -v/bare equivalence, include-only .v, direct restore, and actual-gate Formal
regression_command: conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_t094_builtin_preprocessor_macros tests.test_t099_filelist_compile_context tests.test_t117_filelist_v_library_source tests.test_t119_filelist_multi_root_output tests.test_t120_explicit_vic_include_reference -v
regression_result: PASS, 40/40
py_compile: PASS
git_diff_check: PASS
global_root_audit: PASS; inferred source_root=/, every landed edit resolved under the authorized project root, and diagnostic/external/include-only/extra source hashes remained unchanged
formal_positive: PASS; public actual gate, exit 0, {"formal_equivalence":"pass","seq":5,"top":"t121_top"}
formal_negative: PASS; copied actual gate with project/top.sv XOR -> OR, PySlang blocking=0, Icarus strict=0, Formal exit 1 with unproven / equiv_status -assert
accepted_by: Main Agent Codex
```

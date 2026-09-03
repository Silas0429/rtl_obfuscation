# T134：FAST 分支集成物理 include 闭包

- 状态：`ACCEPTED`
- 负责人：子 Agent（实现与自测）/ 主 Agent（合同与验收）
- 起始分支：`delivery/fast-local-signals`
- 起始提交：`2f263c7`

## 1. 单一目标

把主分支已验收提交 `1d9736f [FIX] Close physical include dependencies` 的 bounded literal include-only
物理闭包安全移植到 FAST 交付分支。FAST 的 parse-only mapping 与严格 gate compile 必须共享同一闭包检查；
不得合并整个 `main`，不得改变 FAST 候选、引用授权、改名决策、CLI、SourceSet/Mapping schema 或性能算法。

真实服务器证据固定为：SourceSet 登记 2574 个文件，PySlang 额外打开 5 个未登记 IncludeFile buffer，
对应 4 个唯一 Synopsys DesignWare `.inc`；原始 `top=None` 严格编译 `parse_errors=0`、
`semantic_errors=0`、`nonblocking_errors=1525`，但临时 gate 因未复制这些 include 而失败。

## 2. 固定输入

主 Agent 冻结以下文件，子 Agent 不得修改：

```text
tests/fixtures/t134_fast_include_closure/design.f
tests/fixtures/t134_fast_include_closure/formal.f
tests/fixtures/t134_fast_include_closure/formal_defs.sv
tests/fixtures/t134_fast_include_closure/project/top.sv
tests/fixtures/t134_fast_include_closure/external/vendor_a.v
tests/fixtures/t134_fast_include_closure/external/vendor_b.v
tests/fixtures/t134_fast_include_closure/external/vendor_function.inc
tests/test_t134_fast_include_closure.py
```

公开 FAST 输入固定为：

```sh
python rtl_encrypt.py \
  --filelist tests/fixtures/t134_fast_include_closure/design.f \
  --rewrite-root tests/fixtures/t134_fast_include_closure/project \
  --category signals \
  --output-dir <new-output>
```

## 3. 冻结行为

1. source/header/context/include-only 文件通过字面量 `` `include "..."`` 在当前目录或 `+incdir+` 中唯一
   解析到的普通文件，不论后缀，递归加入 `SourceSet.included_files`。
2. include-only 文件按规范物理路径和首次发现顺序去重；同一 `.inc` 被两个 module include 仍只登记一次。
3. include-only 文件进入 input/gate/restored manifest 并逐字节只读，但不进入 `ordered_source_files`、
   `compile_order`、gate `design.f`、FAST target 或 mapping record。
4. 任意后缀只由真实 bounded literal include 关系授权；不得扩展裸 filelist、`-v` 或 standalone suffix。
5. 缺失、歧义、越界、symlink 或递归读取失败必须 fail closed。
6. PySlang parse 完成后，`DesignFile`、`LibraryFile`、`IncludeFile` 的真实 buffer 必须全部属于
   `compilation_files + include_files`；`Macro`、`MacroArg` 和精确 `<unnamed_bufferN>` 排除。
7. 共享检查必须同时覆盖 `compile_pyslang_source_set()` 和 FAST 的 `parse_pyslang_source_set()`；动态宏
   include 不自动登记，而是在 FAST `rename_index` 开始前带真实路径拒绝。
8. FAST definition-local CST 算法、候选类型、歧义 preserve、name factory、mapping/rewrite/restore、供应商
   精确语法放行及原子失败全部不变。

## 4. 预期机器可读结果

```text
CLI exit                         = 0
format/schema                    = rtl-obfuscation.cli-vnext / 2
summary.strict_compile_passed    = true
summary.restored_byte_identical  = true
SourceSet included_files         = (external/vendor_function.inc,)
SourceSet compile_order          = three explicit source units only
gate design.f                    = three explicit source units only
vendor/include landed edits      = 0
project/top.sv rename             = first_stage, second_stage
decrypt all physical files       = byte-identical
actual rewritten gate Formal     = pass
fixed functional negative Formal = fail
```

动态宏 include 负例必须在 `rename_index` 前失败，错误包含真实 include 路径，输出目录不存在。

## 5. 不包含

- 不合并整个 `main`，不删除或回退 T130–T133 FAST 文件；
- 不支持宏计算 include、absolute include、glob、`-y`、`+libext+` 或 library map；
- 不改变改名对象、FAST/FULL 分派、diagnostic allowlist、schema 或公开参数；
- 不处理 1195 秒 RenameIndex 和 60 秒 Mapping 性能问题；
- 不运行真实 AICluster/StCache 或 RISC-V-Vector Formal。

## 6. 允许修改文件

```text
README.md
docs/systemverilog_renaming_table.md
docs/development/project_structure.md
docs/development/future_work.md
docs/tasks/T134_fast_include_closure_integration.md
rtl_obfuscator/source_set.py
rtl_obfuscator/project_discovery.py
```

第 2 节测试与 fixture 由主 Agent 冻结；不得修改其它产品代码、历史任务、测试或 fixture。需要扩大范围时
记录偏差并停止。

## 7. Baseline

修改产品代码前运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t134_fast_include_closure.T134FastIncludeClosureTests.test_public_fast_inc_roundtrip -v
```

预期当前 gate strict compile 失败；若失败形状不同，记录后停止。

## 8. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t134_fast_include_closure -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_source_set tests.test_source_catalog \
  tests.test_t099_filelist_compile_context tests.test_t120_explicit_vic_include_reference \
  tests.test_t121_vendor_model_readonly tests.test_t124_filelist_inventory_and_provenance \
  tests.test_t130_fast_local_signals tests.test_t131_definition_local_signals \
  tests.test_t132_separated_declarator_list tests.test_t133_fast_direct_variables -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/source_set.py rtl_obfuscator/project_discovery.py \
  tests/test_t134_fast_include_closure.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T134_fast_include_closure_integration.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t134_ready_for_review=pass")'
```

第一条必须使用公开 FAST CLI 的 actual encrypted gate，执行独立 decrypt，并运行：

```text
gold-filelist = tests/fixtures/t134_fast_include_closure/formal.f
gold-root     = tests/fixtures/t134_fast_include_closure
gate-filelist = <actual gate>/formal.f
gate-root     = <actual gate>
top           = t134_top
seq           = 5
positive      = exit 0 and JSON formal_equivalence=pass
negative      = actual gate 最后一个 ^ 改为 |，exit nonzero，含 unproven 与 equiv_status -assert
```

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 2f263c7
changed_files: `README.md`, `docs/systemverilog_renaming_table.md`, `docs/development/project_structure.md`, `docs/development/future_work.md`, `rtl_obfuscator/source_set.py`, `rtl_obfuscator/project_discovery.py`, 本合同（执行记录）
commands: `baseline：conda run -n rtl_obfuscation python -m unittest tests.test_t134_fast_include_closure.T134FastIncludeClosureTests.test_public_fast_inc_roundtrip -v；验收：conda run -n rtl_obfuscation python -m unittest tests.test_t134_fast_include_closure -v；conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_t099_filelist_compile_context tests.test_t120_explicit_vic_include_reference tests.test_t121_vendor_model_readonly tests.test_t124_filelist_inventory_and_provenance tests.test_t130_fast_local_signals tests.test_t131_definition_local_signals tests.test_t132_separated_declarator_list tests.test_t133_fast_direct_variables -v；conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py rtl_obfuscator/project_discovery.py tests/test_t134_fast_include_closure.py；git diff --check HEAD；最终状态守卫按第 8 节执行`
results: `baseline exit 1：公开 FAST CLI 在写出阶段含 [compile.parse]、构建改名索引和生成映射后，以 REFUSED_ATOMIC: strict gate compilation has diagnostics 失败，与第 7 节预期一致。T134 3/3 OK；固定回归 62/62 OK；py_compile exit 0；git diff --check HEAD exit 0。公开 CLI exit 0，summary.strict_compile_passed=true、summary.restored_byte_identical=true；SourceSet included_files 仅 external/vendor_function.inc，ordered_source_files/compile_order/design.f 均为三个显式 source，gate manifest 含四个物理文件且 include/vendor 无 edit，project/top.sv 有 first_stage/second_stage 两条 rename。动态宏负例 exit nonzero，包含 dynamic.inc，stderr 不含 构建改名索引，输出目录不存在；任意后缀递归、缺失、歧义和裸 filelist 边界均通过；四份允许文档已同步 bounded literal include-only、动态 include fail-closed 和 manifest/gate/restore 保留边界。主 Agent review 返工仅更新四份文档，明确共享检查在 SourceCatalog 全树遍历或 FAST 改名索引开始前带路径拒绝；随后 git diff --check HEAD 通过，T134 3/3 OK。`
schema_or_behavior: `filelist literal include closure accepts bounded ordinary files of any suffix in first-discovery order; arbitrary suffixes remain outside standalone suffixes and compile_order/design.f, are deduplicated by canonical physical path, and are retained read-only in manifest/gate/restore. Shared parse primitive rejects unregistered DesignFile/LibraryFile/IncludeFile buffers after parse and before SourceCatalog/FAST rename_index, excluding Macro/MacroArg and exact <unnamed_bufferN>`
boundaries: Sections 3 and 5
formal_verification: `PASS；gold-filelist=tests/fixtures/t134_fast_include_closure/formal.f，gold-root=tests/fixtures/t134_fast_include_closure；gate-filelist=/tmp/t134-review.aZr9g8/gate/formal.f，gate-root=/tmp/t134-review.aZr9g8/gate；top=t134_top，seq=5；positive command=conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist tests/fixtures/t134_fast_include_closure/formal.f --gold-root tests/fixtures/t134_fast_include_closure --gate-filelist /tmp/t134-review.aZr9g8/gate/formal.f --gate-root /tmp/t134-review.aZr9g8/gate --top t134_top --seq 5，exit 0，JSON formal_equivalence=pass；negative=actual gate 最后一个 second_stage 的 ^ 改为 |，同命令 gate 指向 /tmp/t134-review.aZr9g8/negative/formal.f，exit nonzero（conda wrapper exit 127），输出含 unproven 与 equiv_status -assert。公开测试同时独立 decrypt 并确认所有物理文件 byte-identical。`
review_request: `主 Agent 请独立复跑第 8 节五条命令并验收；本轮 review 返工仅修改四份允许文档及本合同执行记录，未改代码、测试或 fixture，未 commit/push。`
```

## 10. 偏差或阻塞

```text
review_findings_2026-09-03: 主 Agent review 指出四份允许文档只写“SourceCatalog 全树遍历前”拒绝，未明确当前 FAST
parse-only 路径也在 FAST 改名索引前共享该检查；本轮只修订四份允许文档及本合同执行记录，不修改代码、测试或 fixture。
```

## 11. 主 Agent 验收记录

```text
status: ACCEPTED
reviewed_head: 2f263c7 + T134 working tree
acceptance: `主 Agent 独立复跑 T134 专项 3/3 OK、固定回归 62/62 OK、py_compile exit 0、git diff --check HEAD exit 0，READY_FOR_REVIEW 状态守卫通过。公开 FAST CLI actual gate exit 0，strict_compile_passed=true、restored_byte_identical=true，mapping records=2、rename=2、preserve=0、unsupported=0。`
code_review: `确认 bounded literal include 闭包只登记唯一普通物理文件；include-only 文件进入 manifest/gate/restore，但不进入 compile_order、design.f、FAST target 或 mapping；共享 parse primitive 在 SourceCatalog 全树遍历或 FAST rename_index 前拒绝未登记的 DesignFile/LibraryFile/IncludeFile。四份公开文档已按 review finding 明确 FAST 边界。`
blocking_findings: none
formal_verification: `PASS；主 Agent 使用 actual gate /private/tmp/t134-main-review.JBNAlx/gate，gold-filelist=tests/fixtures/t134_fast_include_closure/formal.f，gold-root=tests/fixtures/t134_fast_include_closure，gate-filelist=/private/tmp/t134-main-review.JBNAlx/gate/formal.f，gate-root=/private/tmp/t134-main-review.JBNAlx/gate，top=t134_top，seq=5；positive exit 0 且 JSON formal_equivalence=pass；negative 将 actual gate 中 XOR 改为 OR，gate 指向 /private/tmp/t134-main-review.JBNAlx/negative，exit 1，输出含 2 个 unproven $equiv cells 与 equiv_status -assert。`
resolution: `ACCEPTED；允许提交并推送 delivery/fast-local-signals。`
next_step: `提交并推送后，在 AICluster 服务器复跑物理 buffer probe，预期 registered_files 从 2574 增至 2578，unregistered_files 从 5 降至 0；使用新 output-dir 复跑公开 FAST 命令。`
```

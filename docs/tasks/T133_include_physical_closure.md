# T133：闭合 PySlang 实际 include 物理依赖

- 状态：`ACCEPTED`
- 负责人：子 Agent（实现与自测）/ 主 Agent（合同与验收）
- 起始分支：`main`
- 起始提交：`43c6e7c7575110d7c12457a37dacdcdf9caab808`

## 1. 单一目标

修复 authoritative filelist 的物理清单小于 PySlang 实际 include 集合的问题。由已知 source、header、context
或 include-only 文件通过字面量 `` `include "..."`` 在本地目录 / `+incdir+` 有界范围内唯一解析到的普通
文件，即使后缀不是 `.sv/.v/.svh/.vh/.h/.vic`，也必须作为**只读 include-only 物理依赖**进入
`SourceSet.included_files`。PySlang 解析后还必须在进入 SourceCatalog 全树遍历前核对真实物理 buffer；未登记
的真实 source/include buffer 必须带路径提前拒绝，不能运行数小时后才由 Mapping 拒绝。

## 2. 固定输入与已复现基线

主 Agent 冻结以下输入，子 Agent 不得修改：

```text
tests/fixtures/t133_include_physical_closure/design.f
tests/fixtures/t133_include_physical_closure/formal.f
tests/fixtures/t133_include_physical_closure/formal_defs.sv
tests/fixtures/t133_include_physical_closure/project/top.sv
tests/fixtures/t133_include_physical_closure/external/vendor_a.v
tests/fixtures/t133_include_physical_closure/external/vendor_b.v
tests/fixtures/t133_include_physical_closure/external/vendor_function.inc
```

两个只读 vendor source 都 include 同一个 `.inc`；filelist 的 `+define+T133_WIDTH=4` 同时使 PySlang 创建
`<unnamed_buffer0>`。公开复现：

```sh
python rtl_encrypt.py \
  --filelist tests/fixtures/t133_include_physical_closure/design.f \
  --top t133_top \
  --rewrite-root tests/fixtures/t133_include_physical_closure/project \
  --category all \
  --output-dir <new-output>
```

起始 HEAD 实测：SourceSet、compile、RenameIndex 均完成，进入 Mapping 后 exit 1：

```text
REFUSED_ATOMIC: MAPPING_SOURCE_INVALID: symbol range is not a physical file
```

## 3. 冻结行为

1. `external/vendor_function.inc` 在 SourceSet 中精确出现一次；两个 PySlang include buffer 必须按规范物理路径
   去重。
2. `.inc` 只进入 `included_files` 和物理 manifest，不进入 `ordered_source_files`、`compile_order` 或 gate
   `design.f`，也不得成为 rename target。
3. `.inc`、`vendor_a.v`、`vendor_b.v` 全部位于 rewrite root 外；其 input/gate/restored bytes 必须相同，
   landed edit 为 0。`project/top.sv` 必须仍有真实 rename。
4. 新的 include-only 分类按“真实 include 关系”授权，不把 `.inc` 加进 standalone source/context 后缀，
   不允许 `.inc` 作为裸 filelist entry 或 `-v` entry。
5. 字面量 include 只使用现有本地目录 / `+incdir+` 有界候选；目标必须存在、是普通文件并唯一规范解析。
   缺失、歧义、越界、递归读取失败均 fail closed。
6. 已发现的新 include-only 文件参与递归字面量 include closure；同一路径只保留一次，顺序保持首次发现顺序。
7. PySlang parse 返回后，对 `DesignFile`、`LibraryFile`、`IncludeFile` 的真实普通文件做一次闭合检查。真实路径
   不在 `compilation_files + include_files` 时立即拒绝，错误必须包含未登记路径；不得进入
   `compile.catalog_inventory`。该检查只保存紧凑路径，不保留 buffer wrapper。
8. `Macro`、`MacroArg` 和 PySlang `<unnamed_bufferN>` 非物理 buffer 必须排除，不能进入 SourceSet、manifest
   或 gate。
9. 宏计算出来的动态 include 本任务不自动加入 SourceSet；若它没有被结构 closure 登记，必须由第 7 条在
   parse 后提前、精确、原子拒绝。这一边界防止再次在 Mapping 才发现，不声明完整预处理器发现能力。
10. CLI 参数、SourceSet schema 1、Mapping schema 2、改名类别、rewrite-root 判据、name factory、供应商诊断
    精确放行和安全判据全部不变。

## 4. 不包含

- 不把 `.inc` 当作 standalone source unit、显式 context entry 或新的可改名后缀。
- 不实现宏 include 自动扩充、absolute include、glob、`-y`、`+libext+`、library map 或供应商路径猜测。
- 不过滤全部供应商 RenameIndex 记录，不改变 preserve 统计，不做 SourceCatalog/RenameIndex 性能优化。
- 不修改 Mapping/Rewrite/Restore schema 或取消任何物理 range 检查。
- 不运行真实 AICluster、StCache 或 RISC-V-Vector Formal。

## 5. 允许修改文件

```text
README.md
docs/systemverilog_renaming_table.md
docs/development/project_structure.md
docs/development/future_work.md
docs/tasks/T133_include_physical_closure.md
rtl_obfuscator/source_set.py
rtl_obfuscator/project_discovery.py
tests/test_t133_include_physical_closure.py
```

第 2 节 fixture 是主 Agent 冻结输入。不得修改 `rtl_files.py` 的 standalone suffix 集合，不得修改
Mapping、RenameIndex、SourceCatalog、Rewrite、Formal 或既有测试。需要扩大范围时记录偏差并停止。

## 6. 预期机器可读结果

```text
CLI exit                         = 0
format                           = rtl-obfuscation.cli-vnext
schema_version                   = 2
summary.strict_compile_passed    = true
summary.restored_byte_identical  = true
SourceSet included_files         = (external/vendor_function.inc,)
SourceSet compile_order          = three explicit source units only
gate design.f                    = three explicit source units only
vendor/include landed edits      = 0
project/top.sv landed edits      > 0
decrypt all physical files       = byte-identical
actual rewritten gate Formal     = pass
fixed functional negative Formal = fail
```

动态 macro include 负例：exit nonzero、包含未登记真实文件路径、输出目录不存在，stage observer 不得出现
`[compile.catalog_inventory]`（也不得出现 `SourceCatalog 建立物理模块清单`）。

## 7. Baseline

修改产品代码前必须运行：

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t133_include_physical_closure.T133IncludePhysicalClosureTests.test_public_inc_roundtrip -v
```

预期因当前 Mapping physical-file mismatch 失败；若失败形状不同，记录偏差并停止。

## 8. 固定验收命令

```sh
conda run -n rtl_obfuscation python -m unittest \
  tests.test_t133_include_physical_closure -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_source_set tests.test_source_catalog \
  tests.test_t099_filelist_compile_context \
  tests.test_t120_explicit_vic_include_reference \
  tests.test_t121_vendor_model_readonly \
  tests.test_t124_filelist_inventory_and_provenance -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/source_set.py rtl_obfuscator/project_discovery.py \
  tests/test_t133_include_physical_closure.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T133_include_physical_closure.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t133_ready_for_review=pass")'
```

第一条必须执行公开 CLI、独立 decrypt、物理文件/manifest/edit 审计，以及 actual rewritten gate Formal：

```text
gold-filelist = tests/fixtures/t133_include_physical_closure/formal.f
gold-root     = tests/fixtures/t133_include_physical_closure
gate-filelist = <actual gate>/formal.f（由测试复制 formal_defs.sv/formal.f 作为 Formal-only harness；
                其余输入必须是 actual encrypted gate 文件）
gate-root     = <actual gate>
top           = t133_top
seq           = 5
positive      = exit 0 and JSON formal_equivalence=pass
negative      = actual gate 中唯一 second_stage ^ ...'h5 改为 |，exit nonzero，含 unproven 与 equiv_status -assert
```

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: 43c6e7c7575110d7c12457a37dacdcdf9caab808
changed_files: `README.md`, `docs/systemverilog_renaming_table.md`, `docs/development/project_structure.md`, `docs/development/future_work.md`, `rtl_obfuscator/source_set.py`, `rtl_obfuscator/project_discovery.py`, `tests/test_t133_include_physical_closure.py`, 本合同（执行记录）
commands: `baseline：conda run -n rtl_obfuscation python -m unittest tests.test_t133_include_physical_closure.T133IncludePhysicalClosureTests.test_public_inc_roundtrip -v；验收：conda run -n rtl_obfuscation python -m unittest tests.test_t133_include_physical_closure -v；conda run -n rtl_obfuscation python -m unittest tests.test_source_set tests.test_source_catalog tests.test_t099_filelist_compile_context tests.test_t120_explicit_vic_include_reference tests.test_t121_vendor_model_readonly tests.test_t124_filelist_inventory_and_provenance -v；conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_set.py rtl_obfuscator/project_discovery.py tests/test_t133_include_physical_closure.py；git diff --check HEAD；最终状态守卫按第 8 节执行`
results: `baseline exit 1：SourceSet/compile/RenameIndex 完成，stderr 含 [compile.catalog_inventory] 与 SourceCatalog 建立物理模块清单，随后 ORCHESTRATION_MAPPING_INVALID / REFUSED_ATOMIC: MAPPING_SOURCE_INVALID: symbol range is not a physical file，与第 2 节冻结基线一致。返工后 T133 3 tests OK；固定回归 44 tests OK；py_compile exit 0；git diff --check HEAD exit 0。公开 CLI exit 0，summary.strict_compile_passed=true、summary.restored_byte_identical=true；included_files 仅 external/vendor_function.inc，compile_order/design.f 均为三个显式 source；vendor/include manifest bytes 相同且 landed edits=0，project/top.sv 有真实 rename；独立 decrypt 全部物理文件 byte-identical。动态 macro 负例 exit nonzero，含 dynamic.inc，且 stderr 不含 [compile.catalog_inventory] 或 SourceCatalog 建立物理模块清单；任意后缀 include 递归、缺失、歧义和裸 filelist 边界均通过；文档同步 bounded literal include-only、动态 include fail-closed 和 manifest/gate/restore 保留边界；source_set.py 未使用 import 已移除`
schema_or_behavior: `filelist literal include closure accepts bounded ordinary files of any suffix in first-discovery order; arbitrary include-only files remain outside compile_order and are read-only; parse result rejects unregistered DesignFile/LibraryFile/IncludeFile buffers, excluding Macro/MacroArg and exact <unnamed_bufferN>`
boundaries: frozen by Sections 3 and 4
cleanup_candidates: none
formal_verification: `PASS；gold-filelist=tests/fixtures/t133_include_physical_closure/formal.f，gold-root=tests/fixtures/t133_include_physical_closure；gate-filelist=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t133-public-ifkro663/gate/formal.f，gate-root=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t133-public-ifkro663/gate；top=t133_top，seq=5；command=conda run -n rtl_obfuscation python -m unittest tests.test_t133_include_physical_closure.T133IncludePhysicalClosureTests.test_public_inc_roundtrip -v；positive exit 0，JSON formal_equivalence=pass；negative 在实际 gate 唯一 second_stage ^ ...'h5 改为 |，exit 1，含 unproven 与 equiv_status -assert`
review_request: `按 review findings 完成三项合同内返工：动态 include 负例改为精确排除 [compile.catalog_inventory]（并排除中文 catalog label）；四份允许文档已同步外部行为边界；未使用 import 已移除。目标测试、固定回归、实际 rewritten gate Formal 正负例和第 8 节前四条命令均完成，请主 Agent 独立复跑五条命令并验收。`
```

## 10. 偏差或阻塞

```text
contract_correction_2026-09-02: 主 Agent 最初在 delivery/fast-local-signals 上冻结合同；用户要求本次
修复必须基于 main。子 Agent 在任何产品代码修改前已被中断，工作树只有主 Agent 创建的合同与冻结 fixture。
主 Agent 随后切换到与 origin/main 一致的 43c6e7c，并将合同恢复为 READY；不得带入该 delivery 分支的
e870f7a、055f04c、cb03deb 三个提交。

formal_fixture_correction_2026-09-02: 主 Agent 已将冻结 formal.f 首行改为 formal_defs.sv，并新增冻结
formal_defs.sv（`define T133_WIDTH 4）；产品 design.f 继续保留 +define 以覆盖 <unnamed_buffer0>。
测试在 public gate 生成后仅复制 formal_defs.sv 和 formal.f 到 actual gate root 作为 Formal-only harness，
gold/gate Formal 各自使用 formal.f；未替换或重新生成实际加密 RTL，未修改 Formal 脚本。

review_findings_2026-09-02: 主 Agent review 未接受本轮交付，要求：（1）动态 include 负例断言精确检查实际
observer 文本 `[compile.catalog_inventory]`，并可同时排除中文 catalog label；（2）外部行为变化同步
README.md、docs/systemverilog_renaming_table.md、docs/development/project_structure.md、
docs/development/future_work.md；（3）移除 source_set.py 未使用的 is_physical_rtl_file import。除上述三项外
不得修改 fixture 或其它逻辑。
```

## 11. 主 Agent 验收记录

```text
status: ACCEPTED
reviewed_head: 43c6e7c7575110d7c12457a37dacdcdf9caab808 + T133 working tree on main
acceptance: 主 Agent 独立执行第 8 节五条命令；T133 3/3，固定六模块回归 44/44，py_compile、
  git diff --check HEAD、READY_FOR_REVIEW guard 全部 exit 0。
code_review: SourceSet 仅从 bounded literal include closure 增加普通文件并以 canonical physical path
  去重；arbitrary suffix 没有进入 standalone suffix 集合、ordered_source_files、compile_order 或 design.f。
  project_discovery 在 parse end 后单次核对 DesignFile/LibraryFile/IncludeFile，排除 Macro、MacroArg 和精确
  <unnamed_bufferN>；未登记真实 buffer 在 elaborate、catalog inventory 和 RenameIndex 前带路径拒绝。
  Mapping、RenameIndex、SourceCatalog、Rewrite/Restore、CLI 和 schema 均未修改。
blocking_findings: 初审发现动态 include 测试 observer 断言过弱、四份公开文档缺失和一个 unused import；
  子 Agent 在同一合同内返工，精确排除 [compile.catalog_inventory]/中文 label，同步全部允许文档并移除
  unused import；重跑全部验收后无剩余阻塞。
formal_verification: PASS。主 Agent第一条验收使用公开 CLI 生成的 actual encrypted gate；gold-filelist=
  tests/fixtures/t133_include_physical_closure/formal.f，gate-filelist=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/
  t133-public-lu7qkoia/gate/formal.f，top=t133_top，seq=5；正例 exit 0 且 JSON formal_equivalence=pass；
  actual gate 唯一 second_stage ^ ...'h5 改为 | 的固定功能负例 exit 1，含 unproven 与 equiv_status -assert。
resolution: ACCEPTED；真实 `.inc` 重复 include 闭合、只读 manifest/gate/restore、动态 include 提前拒绝
  和 `<unnamed_buffer0>` 排除均有黑盒证据。
next_step: 在 main 提交并推送；服务器更新后用新的空 OUT 重跑 AICluster。成功运行时间仍由独立的
  SourceCatalog/RenameIndex 性能任务处理，不属于 T133。
```

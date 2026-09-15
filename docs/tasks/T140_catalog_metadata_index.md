# T140：FULL SourceCatalog 不可变文件集合与物理声明索引

- 状态：`ACCEPTED`
- 负责人：主 Agent（合同、冻结测试与独立验收）/ Luna xhigh 子 Agent（实现、自测）
- 起始分支 / HEAD：`main@448647d`
- 计划：`docs/development/full_performance_plan.md` 第一步
- 验收类型：rewrite/mapping 回归；不改变候选，实际 gate Formal 正负例仍必需

## 1. 单一目标与固定输入输出

只消除 SourceCatalog 的完整物理集合重复构造，以及显式 top 到物理声明的线性匹配。
必读 AGENTS.md、docs/tasks/README.md、docs/development/process/refactor_subagent_protocol.md、
docs/formal_verification.md 以及上述计划全文。

主 Agent 冻结 `tests/test_t140_catalog_metadata_index.py`，子 Agent不得修改。
T125 fixture 的 no-top / top / top+rewrite-root 三分支，每次 build 调用 `_known_physical_files`
恰好一次；连续两次构建恰好两次，完整 catalog report 与 owner IDs 不变。
16/64 个独立 leaf + top 的比较计数不超过 3*(leaf+1)，不以耗时阈值作为 flaky gate。
输出 `T140_MEMBERSHIP_JSON` 与 `T140_LOOKUP_JSON`，全部测试通过。
同一构建内文件删除、目录替换、等长 token 修改和 symlink 逃逸仍报 CATALOG_RANGE_INVALID；
物理清单缺失 top 仍报 CATALOG_TOP_MISMATCH。

## 2. 实现边界

- 一次 build 的 `frozenset(compile_order + included_files)` 可显式传递到私有 helper；
  standalone helper 可以保留原检查路径。不得以 SourceSet 相等/hash 作为跨调用缓存 key。
- 显式 top inventory 完成后建立 `(file,start,end)` 集合；只代替两处 any 全量匹配，不去重或
  删除 inventory 条目，不改变 duplicate-provider、parse/semantic/top 的错误先后。
- 不缓存 getFullPath / resolve / is_file / token bytes / 已验证 ranges，继续逐次验证。
- 不新增公共 schema、第三方依赖、global cache 或配置选项。
- 不改变编译次数、root.visit 次数、候选判定、rewrite-root/full-filelist/include、no-top ABI、
  FAST、四组类别、rate 或 gate 验证流程。不运行 RISC，不删除历史测试。

子 Agent 允许修改：

```text
rtl_obfuscator/source_catalog.py
docs/tasks/T140_catalog_metadata_index.md
```

主 Agent拥有本合同、冻结测试和整体计划；已有这三份未提交文件是已知合同输入，不能覆盖/移除。
发现确需额外文件/API/安全边界变更，记录后停止交主 Agent，不自行扩展。

## 3. Baseline（唯一命令）

先记录 starting HEAD / status，更新 READY→IN_PROGRESS，再运行：

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t140_catalog_metadata_index -v
```

性能断言应在原实现失败；live-file 和 index-miss 安全断言应通过。不修改 oracle 制造通过。

## 4. 冻结验收（五条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t140_catalog_metadata_index -v

conda run -n rtl_obfuscation python -m unittest tests.test_source_catalog tests.test_t126_source_backed_owner_boundary tests.test_t128_rename_index_range_cache tests.test_t129_ordered_semantic_workset tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_single_explicit_top_view_has_cst_inventory_and_one_compile tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_physical_inventory_reads_only_token_sized_ranges tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_readonly_duplicate_matrix_is_finite_and_fail_closed tests.test_t133_include_physical_closure.T133IncludePhysicalClosureTests.test_dynamic_macro_include_is_rejected_before_catalog_inventory tests.test_t133_include_physical_closure.T133IncludePhysicalClosureTests.test_literal_arbitrary_suffix_closure_is_bounded_and_fail_closed tests.test_t139_filelist_delivery -v

conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_catalog.py tests/test_t140_catalog_metadata_index.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; s=next(l for l in Path("docs/tasks/T140_catalog_metadata_index.md").read_text().splitlines() if l.startswith("- 状态：")); assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t140_ready_for_review=pass")'
```

第二条重跑 T108 42/70、T115 56/125 完整决策 digest，T139 三视图完整物理交付与 restore、actual
renamed gate / relocated export Formal positive（exit 0 / pass JSON）及 XOR→OR negative
（非零且含 unproven / equiv_status -assert）。记录 T139_FORMAL 的实际 gold/gate/top、seq=5、
精确 `scripts/formal_equivalence.py` 命令与输出；不使用 identity gate。

## 5. 子 Agent 执行记录

status: `READY_FOR_REVIEW`
starting_head: `main@448647d7d127aad014b069cb76b85ce6ed7e0760`
changed_files: `rtl_obfuscator/source_catalog.py`, `docs/tasks/T140_catalog_metadata_index.md`
commands:
- `git status --short --branch && git rev-parse HEAD` -> `## main...origin/main`, `448647d7d127aad014b069cb76b85ce6ed7e0760`
- `conda run -n rtl_obfuscation python -m unittest tests.test_t140_catalog_metadata_index -v` (baseline before edits)
- `conda run -n rtl_obfuscation python -m unittest tests.test_t140_catalog_metadata_index -v`
- `conda run -n rtl_obfuscation python -m unittest tests.test_source_catalog tests.test_t126_source_backed_owner_boundary tests.test_t128_rename_index_range_cache tests.test_t129_ordered_semantic_workset tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_single_explicit_top_view_has_cst_inventory_and_one_compile tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_physical_inventory_reads_only_token_sized_ranges tests.test_t125_single_view_rewrite_root_catalog.T125SingleViewRewriteRootCatalogTests.test_readonly_duplicate_matrix_is_finite_and_fail_closed tests.test_t133_include_physical_closure.T133IncludePhysicalClosureTests.test_dynamic_macro_include_is_rejected_before_catalog_inventory tests.test_t133_include_physical_closure.T133IncludePhysicalClosureTests.test_literal_arbitrary_suffix_closure_is_bounded_and_fail_closed tests.test_t139_filelist_delivery -v`
- `conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/source_catalog.py tests/test_t140_catalog_metadata_index.py`
- `git diff --check HEAD`
- T140 status guard
results:
- Baseline exit `1` as expected: membership calls `12/15/9`; explicit-top SourceRange comparisons `170/2210`; live-file and index-miss guards passed.
- T140 target exit `0`, `5` tests passed; `T140_MEMBERSHIP_JSON` reports one membership build in each branch and two across consecutive builds; `T140_LOOKUP_JSON` reports `0` counted SourceRange equality comparisons for 17 and 65 physical modules.
- Targeted regression exit `0`, `46` tests passed; T108 digest `0180e2d80e623f5677e3dbce6cf0259e9a486380d8b4ad7142c023350f23bf9f`, T115 digest `dbbc8fb76135251abcd8f87dca6e78ce3a5df7c19101e1c3907f020d8dd49a78`.
- T139 actual gate/export Formal: design and relocated export exit `0`, JSON `{"formal_equivalence":"pass","top":"t139_top","seq":5}`; XOR-to-OR negative exit `1` with `unproven` and `equiv_status -assert`.
- `py_compile` exit `0`; `git diff --check HEAD` exit `0`.
schema_or_behavior: implement one build-local physical membership set and explicit-top physical declaration index only
boundaries: preserve per-call path, regular-file, token-byte validation; no cache across SourceSet/build/SourceManager
cleanup_candidates: none
formal_verification: `PASS`
gold: `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zajctmzt/project` via `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zajctmzt/gate/original_design.f`
gate: `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zajctmzt/gate/design.f`; relocated export `/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zajctmzt/relocated/export_design.f`
top: `t139_top`
command: `conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zajctmzt/gate/original_design.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zajctmzt/project --top t139_top --seq 5 --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zajctmzt/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zajctmzt/gate`; relocated export uses `OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zajctmzt/relocated` and the corresponding relocated `export_design.f`; negative uses `OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-zajctmzt/negative` and the corresponding negative `export_design.f`.
exit_code: positive `0`, relocated positive `0`, negative `1`
result: positive and relocated JSON `formal_equivalence=pass`; negative contains `unproven` and `equiv_status -assert`
review_request: implementation and evidence complete; Main Agent must independently rerun the five frozen commands and decide `ACCEPTED`

## 6. 偏差或阻塞

暂无。

## 7. 主 Agent 验收

2026-09-15 主 Agent 在子 Agent 正式交付后独立重跑全部五条命令：

- 精确 READY_FOR_REVIEW guard：exit 0，`t140_ready_for_review=pass`。
- T140：exit 0，5 tests / 0.067s；三分支每次集合构造均为 1；17/65 个物理 module 的
  SourceRange equality 计数均为 0（已替换为物理键集合查询，不表示没有查询）。
- 固定回归矩阵：exit 0，46 tests / 2.121s；T108 / T115 完整 digest 与合同基线完全一致。
- py_compile、git diff --check HEAD：均 exit 0。
- live-file 删除、目录替换、等长字节修改、symlink 逃逸、missing inventory、duplicate-provider、
  macro/include 及 T139 完整交付/逐字节恢复均通过。

正式交付前 Main 的一次预检因顶层仍为 IN_PROGRESS 而被状态 guard 拒绝；该预检不计入验收。
本节只记录状态 guard 通过后的独立复跑。最终代码差异限于传递不可变成员集合及两处物理键查询；
没有缓存 token/path，没有改候选、编译/遍历次数、异常优先级或 gate 校验。

formal_verification: `PASS`。命令 2 在本次 Main 独立进程内调用以下同环境脚本：

```sh
conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/gate/original_design.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/gate/design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/gate --top t139_top --seq 5

OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/relocated conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/gate/original_design.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/relocated/export_design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/relocated --top t139_top --seq 5

OUT=/var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/negative conda run -n rtl_obfuscation python scripts/formal_equivalence.py --gold-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/gate/original_design.f --gold-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/project --gate-filelist /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/negative/export_design.f --gate-root /var/folders/cp/bx46stb947z85y3_zdrnwxj40000gn/T/t139-filelist-views-c_3pz5p0/negative --top t139_top --seq 5
```

两个正例 exit 0，JSON 为 `formal_equivalence=pass, top=t139_top, seq=5`，gold 为上述 project，gate
分别为 gate / relocated。实际 gate XOR→OR 负例 exit 1，`unproven=true, equiv_status_assert=true`。
测试同时断言 modified_tokens > 0、gate 字节不同于 gold；临时目录由测试自动清理。

结论：主 Agent 接受 T140；提交/推送结果在本轮交付及后续计划记录中确认。

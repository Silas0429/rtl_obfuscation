# T122：供应商诊断核验使用有界读取

- 状态：`ACCEPTED`
- 主 Agent：Codex
- 起始 HEAD：`aa40c877dae560c6f8a1ae3bdfa0743e5c13d1b6`（T121 已 `ACCEPTED`）
- 任务类型：SourceSet / PySlang diagnostic classifier resource fix
- 服务器环境：PySlang `11.0.0`

## 1. 已确认问题

服务器使用完整 filelist 和 `--rewrite-root` 时，在进度停留于“读取 filelist / 组装 SourceSet”后被
系统发送 SIGKILL。内核日志已明确记录：

```text
Memory cgroup out of memory: Kill process ... (python)
Killed process ... total-vm:20941976kB, anon-rss:20586828kB
```

主机当时仍有约 69 GiB available memory，因此这是当前作业所在 memory cgroup 的限制，不是普通
PySlang diagnostic，也不是输出目录错误。

T121 前后都只创建一次 `SyntaxTree` 和一次 `Compilation`，也都会执行 `getRoot()` 与
`getAllDiagnostics()`。T121 新增的 `_physical_diagnostic_source()` 会针对每一条 syntax diagnostic
执行 `Path.read_bytes()`。主 Agent 已用 T121 fixture 实测：同一 552-byte 文件的 9 条兼容诊断导致
9 次整文件读取、累计读取 4968 bytes。真实输入有 512 条目标诊断，且整文件读取发生在完整 PySlang
编译结构仍驻留内存时，会增加不必要的峰值和内存分配压力。

完整 filelist 的 PySlang 编译仍是约 20 GiB 常驻内存的主体；本任务只移除 T121 新增的无界物理文件
读取。服务器复测若仍 OOM，必须另立任务讨论缩小 semantic compilation 范围及外部 module interface
合同，不得在本任务中静默跳过目录外 source。

## 2. 单一目标

保持 T121 精确放行、fail-closed 和供应商文件只读语义完全不变，把诊断位置的物理字节核验改为有界、
流式读取，使分类器用于物理字节核验的读取 buffer 不随源文件大小或诊断数量增长，并且不再为任何一条
诊断读取整个文件。

## 3. 行为合同

### 3.1 必须保持不变

1. 只放行 T121 已授权的 `DiagCode(IfNoneEdgeSensitive)` 完整 `ifnone` token，以及六个精确
   `UnknownDirective`；其他 diagnostics 继续阻塞。
2. directive 的行首水平空白、行尾水平空白、可选 `//` comment、CRLF、EOF 行，以及
   `protect/endprotect` 顺序配对语义不变。
3. macro/virtual location、非 SourceSet 物理文件、越界 offset、路径解析失败、读取失败和字节形状不符
   继续 fail closed。
4. `vendor_compatibility_errors`、`vendor_compatibility_files`、`parse_errors`、`semantic_errors` 和
   `nonblocking_errors` 的内容及顺序不变。
5. `--rewrite-root` 仍只控制 rename eligibility，不缩小 filelist compile order；`-v` 仍与裸路径等价。
6. 不改变 SourceSet、mapping、mapping-execution 或 CLI 的持久化 schema，不新增用户参数、配置或缓存。

### 3.2 有界读取要求

1. `_physical_diagnostic_source()` 或其替代 helper 只返回可信 canonical path、relative path、offset 和
   必要的文件元数据，不得调用 `Path.read_bytes()`、`read()` 无长度形式或等价整文件读取。
2. `ifnone` 核验只读取 token、前一个边界 byte 和后一个边界 byte 所需的小窗口。
3. directive 核验可从 diagnostic offset 向行首和行尾分块扫描；每次读取必须有固定上限，内存中不得
   拼接或保留完整任意长物理行。任意长的合法空白或 `//` comment 仍应以流式状态检查，不得仅因超过
   人为行长上限而改变 T121 结果。
4. 分块大小是内部实现常量，不进入公共 schema。读取错误、文件被截断或 diagnostic offset 超出打开后
   的实际文件范围时 fail closed。
5. protect pairing 只保存既有的 diagnostic offset 和 directive name；不得保存源文件内容。

## 4. Compact 验收场景

新增 `tests/test_t122_vendor_diagnostic_memory.py`，至少证明：

1. T121 fixture 的 9 条 compatibility diagnostics、文件集合、blocking/nonblocking 分类与现有结果
   完全相同。
2. instrumentation 禁止 `Path.read_bytes()`、禁止无长度 `read()`，并记录单次最大读取尺寸；包含多个
   diagnostic 时仍只出现固定上限的小块读取。
3. 一个高 offset 的 sparse physical file 不被整体读取；对重复 `ifnone` diagnostics 的分类正确，
   Python 侧额外峰值保持在与文件大小无关的小界限内。
4. directive 覆盖长行首空白、长 `//` comment、CRLF 和 EOF；精确合法形状继续通过，额外 token、错误
   comment marker、截断和 I/O 失败继续拒绝。
5. 现有普通未知宏、带参数、未配对/逆序/嵌套 protect、伪 `ifnone` 和 macro location 仍 fail closed。

不得把“目标测试未 OOM”作为唯一证据；测试必须直接约束读取 API 和单次读取上限，防止小 fixture 掩盖
整文件读取回归。

## 5. 明确不包含

- 不减少或重排 authoritative filelist 的 PySlang compilation units；
- 不按 `--rewrite-root` 跳过目录外 source 的 parse/elaboration；
- 不生成 blackbox、module header stub 或第二份 analysis filelist；
- 不新增供应商 directive、UDP/primitive、encrypted payload 或其它语法兼容；
- 不改变 rename、rewrite、gate、restore 或 Formal 实现；
- 不声称本地 compact 测试能证明服务器 20 GiB cgroup 下必然成功。

如果服务器复测仍 OOM，后续任务必须先冻结以下选择：用户提供外部接口 stub、工具生成精确 stub，或允许
受控的 unresolved external module；在没有接口合同前不得简单删除目录外 filelist entry。

## 6. 允许修改的文件

- `docs/tasks/T122_bounded_vendor_diagnostic_reads.md`
- `rtl_obfuscator/project_discovery.py`
- `tests/test_t122_vendor_diagnostic_memory.py`

不得修改 T121 历史任务、T121 fixture/test、SourceSet/rewrite/catalog/rename 实现、公共文档或其他文件。

## 7. 固定验收命令（5 条）

```sh
conda run -n rtl_obfuscation python -m unittest tests.test_t122_vendor_diagnostic_memory -v

conda run -n rtl_obfuscation python -m unittest \
  tests.test_t121_vendor_model_readonly.T121VendorModelReadonlyTests.test_exact_diagnostics_are_nonblocking_and_catalog_tracks_physical_file \
  tests.test_t121_vendor_model_readonly.T121VendorModelReadonlyTests.test_diagnostic_whitelist_fails_closed -v

conda run -n rtl_obfuscation python -m py_compile \
  rtl_obfuscator/project_discovery.py tests/test_t122_vendor_diagnostic_memory.py

git diff --check HEAD

conda run -n rtl_obfuscation python -c 'from pathlib import Path; \
s=next(l for l in Path("docs/tasks/T122_bounded_vendor_diagnostic_reads.md").read_text().splitlines() if l.startswith("- 状态：")); \
assert s=="- 状态：`READY_FOR_REVIEW`", s; print("t122_ready_for_review=pass")'
```

## 8. Formal verification

```text
formal_verification: N/A
reason: SourceSet diagnostic byte-reading resource fix only; no rewrite, mapping, gate, restore, or RTL output behavior changes
```

## 9. 子 Agent 执行记录

```text
status: READY_FOR_REVIEW
starting_head: aa40c877dae560c6f8a1ae3bdfa0743e5c13d1b6
changed_files:
  - docs/tasks/T122_bounded_vendor_diagnostic_reads.md
  - rtl_obfuscator/project_discovery.py
  - tests/test_t122_vendor_diagnostic_memory.py
baseline:
  command: conda run -n rtl_obfuscation env PYTHONPATH=. python /tmp/t122_baseline_probe.py
  result: PASS; vendor_compatibility_errors=9, diagnostic_read_bytes_calls=9,
    diagnostic_read_bytes_total=4968, diagnostic_file_size=552
commands:
  - conda run -n rtl_obfuscation python -m unittest tests.test_t122_vendor_diagnostic_memory -v
  - conda run -n rtl_obfuscation python -m unittest tests.test_t121_vendor_model_readonly.T121VendorModelReadonlyTests.test_exact_diagnostics_are_nonblocking_and_catalog_tracks_physical_file tests.test_t121_vendor_model_readonly.T121VendorModelReadonlyTests.test_diagnostic_whitelist_fails_closed -v
  - conda run -n rtl_obfuscation python -m py_compile rtl_obfuscator/project_discovery.py tests/test_t122_vendor_diagnostic_memory.py
  - git diff --check HEAD
  - conda run -n rtl_obfuscation python -c '<T122 READY_FOR_REVIEW status guard>'
results:
  - target tests: exit 0; Ran 4 tests in 0.107s; OK
  - frozen T121 regression: exit 0; Ran 2 tests in 0.107s; OK
  - py_compile: exit 0; no stdout/stderr
  - diff check: exit 0; no stdout/stderr
  - status guard: exit 0; t122_ready_for_review=pass
schema_or_behavior: T121 diagnostic classification and ordering are unchanged; physical verification now uses
  explicit bounded reads of at most 4096 bytes, with a small ifnone window and streaming directive-line state.
  Sparse offsets above 96 MiB remained bounded and the target test measured Python peak allocation below 2 MiB.
boundaries: Full authoritative filelist compilation remains unchanged and may still exceed the server's roughly
  20 GiB cgroup limit. This task adds no cache, compile-order reduction, external-module stub, CLI option, schema,
  directive, or rewrite behavior.
cleanup_candidates: none
formal_verification: N/A; SourceSet diagnostic byte-reading resource fix only; no rewrite, mapping, gate,
  restore, or RTL output behavior changes
review_request: Main Agent should independently rerun the five fixed acceptance commands and confirm the diff
  remains restricted to the three files authorized by section 6.
```

## 10. 主 Agent 验收

```text
main_result: PASS
reviewed_head: aa40c877dae560c6f8a1ae3bdfa0743e5c13d1b6 + T122 working tree
scope_review: PASS; changes limited to the three authorized files
code_review: PASS; no whole-file or unbounded read remains in the diagnostic path; ifnone reads only its
  boundary window; directive scanning uses at most 4096-byte chunks and preserves arbitrary-length leading
  whitespace/comment behavior; macro/path/offset/read failures remain fail closed
target_command: conda run -n rtl_obfuscation python -m unittest tests.test_t122_vendor_diagnostic_memory -v
target_result: PASS, 4/4
t121_regression_command: conda run -n rtl_obfuscation python -m unittest
  tests.test_t121_vendor_model_readonly.T121VendorModelReadonlyTests.test_exact_diagnostics_are_nonblocking_and_catalog_tracks_physical_file
  tests.test_t121_vendor_model_readonly.T121VendorModelReadonlyTests.test_diagnostic_whitelist_fails_closed -v
t121_regression_result: PASS, 2/2
py_compile: PASS
git_diff_check: PASS
ready_for_review_guard: PASS; t122_ready_for_review=pass
differential_probe: PASS; 366 old-vs-streamed directive/ifnone cases, 0 mismatches
resource_probe: PASS; sparse file above 96 MiB, maximum single read 4096 bytes, Python traced peak below 2 MiB
formal_verification: N/A; no rewrite, mapping, gate, restore, or RTL output behavior changes
remaining_boundary: full authoritative PySlang compilation remains unchanged and may still exceed the server
  cgroup; server rerun is required before deciding whether a separate reduced-compilation/interface task is needed
accepted_by: Main Agent Codex
```

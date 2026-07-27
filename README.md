# RTL Obfuscation vNext

本项目使用 PySlang 对 SystemVerilog 建立唯一的
`SourceSet -> SourceCatalog -> SymbolGraph -> RewritePolicy -> MappingVNext`
语义链路，并通过 actual gate、restore、metrics 和 portable report 完成可审计的标识符改写。

当前用户入口只有：

```text
encrypt-vnext
decrypt-vnext
```

旧 mapping、旧 profile 和旧命令不提供兼容层；未知 operation 会 fail-closed。

## 输入与输出

`encrypt-vnext` 三选一：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-vnext \
  --input tests/fixtures/refactor_symbol_graph_parameters/single.sv \
  --source-root tests/fixtures/refactor_symbol_graph_parameters \
  --output-dir /tmp/rtl-vnext/gate \
  --map /tmp/rtl-vnext/orchestration.json \
  --metrics /tmp/rtl-vnext/metrics.json
```

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-vnext \
  --filelist tests/fixtures/refactor_symbol_graph_parameters/design.f \
  --source-root tests/fixtures/refactor_symbol_graph_parameters \
  --top parameter_top --category all --category interface \
  --category modules --category ports --encryption-rate 0.35 \
  --output-dir /tmp/rtl-vnext/gate \
  --map /tmp/rtl-vnext/orchestration.json \
  --metrics /tmp/rtl-vnext/metrics.json
```

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-vnext \
  --project-root rtl_samples/example_fifo --top fifo_top \
  --category all --category interface --category modules --category ports \
  --output-dir /tmp/rtl-vnext/fifo-gate \
  --map /tmp/rtl-vnext/fifo-orchestration.json \
  --metrics /tmp/rtl-vnext/fifo-metrics.json
```

`--output-dir` 是 actual gate；`--map` 是
`rtl-obfuscation.orchestration-vnext`；`--metrics` 是
`rtl-obfuscation.metrics-vnext`。三个输出均原子发布、不得覆盖已有路径，并且 report 不含绝对路径。
single-file、filelist 和 project-root 共享同一流水线；project-root report 保留 top closure、compile order、include dirs 和 defines。

恢复只消费持久化 orchestration report、actual gate 和原始 source bytes：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt-vnext \
  --map /tmp/rtl-vnext/orchestration.json \
  --gate-dir /tmp/rtl-vnext/gate \
  --source-root tests/fixtures/refactor_symbol_graph_parameters \
  --output-dir /tmp/rtl-vnext/restored \
  --report /tmp/rtl-vnext/restore.json
```

失败时不留下部分 gate、restore、JSON 或临时文件；恢复后的 physical files 与输入 bytes 一致。

## 19 类 registry

canonical 顺序固定为：

```text
signals parameters enum_values genvars functions tasks arguments instances
generate_blocks typedefs struct_types struct_fields union_fields modules ports
interfaces interface_instances interface_ports modports
```

`all` 默认展开前 13 类；`struct` 展开为 `struct_types, struct_fields`；
`interface` 展开为 `interfaces, interface_instances, interface_ports, modports`。
ABI category 只能从 `parameters typedefs struct_types struct_fields union_fields modules ports interfaces interface_instances interface_ports modports` 中选择，且必须同时出现在 normalized category、top closure 和完整 binding 中。

SymbolGraph 使用统一 `SourceSymbol`，每个 declaration/reference range 都经过 source-byte、owner、重复和重叠审计。top boundary、未解析 owner、外部消费者和不完整 interface/type binding 默认保留或 fail-closed。

## FIFO demo

`encrypt.py` 只演示非 RISC 的 FIFO vNext project-root 流程：

```sh
conda run -n rtl_obfuscation python encrypt.py --work-dir /tmp/rtl-vnext-fifo
```

它会运行 actual gate、portable orchestration/metrics report 和独立 restore，并检查四个 physical files 的 byte identity。

## 验证

项目使用 Conda 环境 `rtl_obfuscation`。常规测试显式列出非 RISC 模块；RISC-V-Vector 专项验证不属于普通 vNext 产品流程。Formal 等价验证只在产生 rewritten RTL 的专门验收任务中按 `docs/formal_verification.md` 执行。

RISC-V-Vector 发布验收由独立场景驱动执行；它不改变产品 CLI：

```sh
conda run -n rtl_obfuscation python scripts/risc_v_vector_acceptance.py \
  --work-dir /private/tmp/rtl-obfuscation-t057-release
```

该驱动使用通用 `formal_vnext.py` view/alignment API，并在 actual selected gate 上完成唯一一次
正例与功能负例 Formal。

# 项目结构

本文面向开发者。普通用户只需要阅读根目录
[`README.md`](../../README.md) 和
[`SystemVerilog 可加密类型表`](../systemverilog_renaming_table.md)。

## 产品入口

普通用户从仓库根目录运行 `python rtl_encrypt.py` 加密，运行 `python rtl_decrypt.py`
恢复；无需安装本项目。项目模式也使用 `--source-root`，由缺少 input/filelist 且提供 top
来推断。两个根目录脚本只负责调用共享 Python 函数。

`rtl_obfuscator/rewrite.py` 负责共享参数注册、公共入口和执行调度。公共入口直接复用同一文件
中的 `_encrypt_vnext` / `_decrypt_vnext`；内部 `encrypt-vnext` / `decrypt-vnext`
operation 暂时只为历史测试和兼容保留，不是当前用户接口。

## 核心模块

| 路径 | 职责 |
| --- | --- |
| `rtl_obfuscator/source_set.py` | 将单文件、显式 filelist 和 project-root 输入归一化为同一种 SourceSet。 |
| `rtl_obfuscator/project_discovery.py` | 从 project root 和 top 自动发现依赖闭包及编译顺序。 |
| `rtl_obfuscator/source_catalog.py` | 使用 PySlang 建立源文件、编译上下文和模块 owner catalog。 |
| `rtl_obfuscator/symbol_graph.py` | 收集可处理的 SystemVerilog 符号、声明、引用及归属关系。 |
| `rtl_obfuscator/category_registry_vnext.py` | 定义 19 个 canonical category、默认集合、alias 和 ABI 可选集合。 |
| `rtl_obfuscator/rewrite_policy.py` | 根据 category、top boundary 和 ABI 授权决定改名或保留。 |
| `rtl_obfuscator/mapping_vnext.py` | 建立并校验统一的 MappingVNext 记录。 |
| `rtl_obfuscator/systemverilog_names.py` | 生成合法且不冲突的 SystemVerilog 新名称。 |
| `rtl_obfuscator/rewrite_vnext.py` | 应用 source-range edits，生成 gate，并执行严格编译和恢复检查。 |
| `rtl_obfuscator/rate_vnext.py` | 按目标加密比例选择 mapping entries。 |
| `rtl_obfuscator/rate_execution_vnext.py` | 执行 rate-selected mapping，并复用统一 gate/restore 引擎。 |
| `rtl_obfuscator/metrics_vnext.py` | 计算符号、引用、有效行覆盖率和明文泄漏指标。 |
| `rtl_obfuscator/rate_metrics_vnext.py` | 组合 rate execution、mapping envelope 和 metrics 报告。 |
| `rtl_obfuscator/orchestration_vnext.py` | 编排 SourceSet、mapping、可选 rate、gate、restore 和 metrics。 |
| `rtl_obfuscator/restore_vnext.py` | 从持久化报告校验 gate 并恢复原始文件。 |
| `rtl_obfuscator/formal_vnext.py` | 提供 Formal 使用的通用 view、alignment 和审计 API。 |

当前数据流：

```text
python rtl_encrypt.py -> SourceSet -> SourceCatalog -> SymbolGraph -> RewritePolicy
    -> MappingVNext -> optional rate -> gate/restore -> metrics/report

python rtl_decrypt.py -> persisted report + actual gate
    -> gate/range/manifest audit -> direct restore -> hydration validation
    -> byte-identical source files
```

## 测试、脚本和样例

- `tests/`：使用 Python `unittest` 的产品与边界测试，以及测试专用 SystemVerilog fixtures。
- `scripts/formal_equivalence.py`：运行 Yosys 等价验证。
- `scripts/risc_v_vector_acceptance.py`：RISC-V-Vector 专项发布验收工具，不是用户入口，也不属于
  常规测试。
- `rtl_samples/`：可供试用的 SystemVerilog 语法样例、FIFO 项目和 RISC-V-Vector 发布样例。
- `docs/tasks/`：逐任务保存合同、状态和验收证据；历史任务中的命令不代表当前产品接口。

## 开发规范

- [Formal 验证流程](../formal_verification.md)
- [未来扩展与已知边界](future_work.md)
- [任务状态和验收流程](../tasks/README.md)
- [R0–R5 历史重构计划](architecture/three_mode_refactor_plan.md)

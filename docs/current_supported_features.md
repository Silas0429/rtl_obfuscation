# 当前支持的重命名功能与综合演示

面向交付使用的最新边界、项目结构和 FIFO 命令统一见
[delivery_guide.md](delivery_guide.md)。本文保留较早的单文件综合样例数据。

本文只描述已经通过黑盒测试和 Yosys formal 的功能，不包含计划中尚未实现的类别。
单文件能力使用 mapping v1；多文件 project 能力使用 filelist、mapping v2 和 project-level
formal。`interfaces`、`modules`、`ports` 以及其他 interface ABI 类别必须显式指定，
不属于安全的 `all` 集合。

## 1. 当前支持表

| CLI category | 当前支持内容 | 验收结果 | 当前边界 |
| --- | --- | ---: | --- |
| `signals` | module 内部、非 port 的 `VariableSymbol`/`NetSymbol`；源码可为 `logic`、`reg`、`wire`、`tri` | 7 entries / 24 tokens | 不含 port、interface member、subroutine argument、aggregate field |
| `parameters` | module value parameter/localparam 声明、普通表达式、常用 packed/unpacked dimension、generate header 和 resolved named override 左侧 | FIFO：9 / 51 | 不含 type/package/class/interface parameter、defparam、层次引用和任意复杂同名遮蔽；详见交付指南第 4—5 节 |
| `enum_values` | module 内 enum member 的声明和已绑定引用 | 3 / 8 | 不含 package/class enum 或跨文件引用 |
| `genvars` | 单个简单 generate-for 的声明、条件、步进和循环体索引 | 1 / 5 | 当前固定样例为 4 次展开；不含多个、嵌套 loop 和 generate block label |
| `functions` | module function 声明、普通调用；T009 另覆盖传统返回赋值 | 1 / 2 | 不含 extern、DPI、recursive、package/class function |
| `tasks` | module task 声明和普通 ordered call | 1 / 2 | 不含 extern、DPI、层次调用和命名实参 |
| `arguments` | module function/task 形式参数声明及 subroutine 内部引用 | 4 / 9 | ordered actual expressions 不改名；不含命名实参和 prototype |
| `instances` | 单个具名 module instance 的声明 | T012 fixture 1 / 1 | 不含层次引用、instance array、primitive/checker/interface instance |
| `generate_blocks` | module 直属、显式命名的 generate-for block label | 综合样例 1 / 1 | 不含层次引用、嵌套/conditional generate、implicit `genblkN` |
| `typedefs` | module 内普通 typedef 名（非 struct/union）的声明和类型引用 | 综合样例 1 / 2 | 不含 package/class typedef、forward declaration、port 类型引用、cast 表达式 |
| `struct_types` | module 内 typedef struct/union 类型名的声明和类型引用 | T013 fixture 1 / 3 | 不含 struct_fields、union_fields、package/class scope |
| `modules` | 多文件项目中的非 top module 定义名及已绑定 instance type 引用 | T016：1 / 2 | 只允许 project CLI；top module 必须保留 |
| `ports` | 多文件项目中的 child port 声明、module body 引用和 named connection 左侧 | T016：2 / 6 | 只允许 project CLI；top ports 必须保留 |
| `interfaces` | 多文件项目中的 interface 定义名、instance type 和 interface port header 引用 | T017：1 / 3 | 必须显式指定；不含 interface instance/member/modport 名 |
| `interface_instances` | interface instance 声明和层次/member connection 中的 instance 引用 | T018：1 / 4 | 必须显式指定；不含 virtual interface、外部层次引用 |
| `interface_ports` | interface header/body member 声明、member access、named connection 左侧和 modport port 引用 | T018：5 / 17 | 必须显式指定；`modport_ports` 不独立生成 entry |
| `modports` | interface 中 modport 声明名 | T018：2 / 2 | 必须显式指定；当前为 declaration-only |

综合样例总计 23 个 mapping entries、63 个被改写 token。名称长度由 `--name-length` 控制，当前演示使用 8，允许值必须不小于 4。

正常使用时选择 `--category all`，一次解析并直接生成最终 RTL、单一混合 mapping 和全局 metrics。
当前 `all` 只展开以下 13 个安全 category：

```text
signals parameters enum_values genvars functions tasks arguments instances
generate_blocks typedefs struct_types struct_fields union_fields
```

`modules`、`ports`、`interfaces`、`interface_instances`、`interface_ports` 和 `modports`
必须通过重复的 `--category` 显式加入。单 category 选项仍保留，作为定位某一类重命名问题的 debug 模式。

T020 已验收四文件 FIFO、per-file mapping、parameter dimension/named override 和 19 类
debug 流程。FIFO 固定完整结果为 77 entries / 292 tokens。

## 2. 演示输入

```text
gold: rtl_samples/11_supported_obfuscation.sv
top:  sample11_supported_obfuscation
```

本单文件演示中 module 名和 ports 不会改名；多文件 project 中可以显式改写非 top module
及 child ports，但 top module 和 top ports 始终保留，因此 formal 的 top 保持不变。

## 3. 生成最终加密 RTL

从仓库根目录运行：

```sh
OUT=/tmp/rtl_obfuscation_supported_demo
rm -rf "$OUT"
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
  --input rtl_samples/11_supported_obfuscation.sv \
  --output "$OUT/gate.sv" \
  --map "$OUT/mapping.json" \
  --metrics "$OUT/metrics.json" \
  --category all \
  --name-length 8
```

预期 stdout：

```json
{"files": 1, "mapping_entries": 23, "modified_tokens": 63}
```

三个输出分别为：

```text
/tmp/rtl_obfuscation_supported_demo/gate.sv
/tmp/rtl_obfuscation_supported_demo/mapping.json
/tmp/rtl_obfuscation_supported_demo/metrics.json
```

查看混合 mapping 和全局 metrics：

```sh
conda run -n rtl_obfuscation python -m json.tool \
  "$OUT/mapping.json"
conda run -n rtl_obfuscation python -m json.tool \
  "$OUT/metrics.json"
```

只调试某个类别时，将 `--category all` 改为例如 `--category signals`。

## 4. 前端检查和 Yosys formal

```sh
FINAL_GATE="$OUT/gate.sv"

conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("/tmp/rtl_obfuscation_supported_demo/gate.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'

conda run -n rtl_obfuscation verible-verilog-syntax \
  --lang=sv "$FINAL_GATE"

conda run -n rtl_obfuscation iverilog -g2012 -t null \
  -s sample11_supported_obfuscation "$FINAL_GATE"

conda run -n rtl_obfuscation python scripts/formal_equivalence.py \
  --gold rtl_samples/11_supported_obfuscation.sv \
  --gate "$FINAL_GATE" \
  --top sample11_supported_obfuscation
```

前三条命令预期退出码为 0；formal 预期输出包含：

```json
{"formal_equivalence": "pass", "seq": 5, "top": "sample11_supported_obfuscation"}
```

## 5. 使用 mapping 逆向恢复

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
  --input "$OUT/gate.sv" \
  --output "$OUT/restored.sv" \
  --map "$OUT/mapping.json"

cmp -s rtl_samples/11_supported_obfuscation.sv "$OUT/restored.sv"
echo $?
```

最后输出 `0` 表示恢复文件与原始 SystemVerilog 文件字节完全一致。

## 6. 结果解释

- final gate 与 gold 的功能一致性由 Yosys formal 证明。
- mapping 中每个 entry 保留真实 category，并提供相对原始输入的双向名称关系和 source ranges。
- metrics 直接统计原始 gold 到最终 gate 的全局效果；综合样例为 41/61 个有效代码行、23/23 个符号和 63/63 个 occurrences。
- 单文件演示不改写 module/port 是 preserve 策略；多文件 project 已支持显式的非 top
  `modules`/child `ports` 重命名。top 和外部 ABI 的保留仍是设计边界，不应视为遗漏。

## 7. 多文件 project 验收入口

已通过验收的固定 project fixture：

```text
tests/fixtures/t015_multi_file       # mapping v2 / project formal 基线
tests/fixtures/t016_module_port      # modules + ports
tests/fixtures/t017_interface        # interfaces
tests/fixtures/t018_interface_member # interface_instances + interface_ports + modports
```

项目级命令形式为：

```sh
conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt-project \
  --filelist tests/fixtures/t018_interface_member/design.f \
  --source-root tests/fixtures/t018_interface_member \
  --output-dir /tmp/rtl_obfuscation_project/gate \
  --map /tmp/rtl_obfuscation_project/mapping.json \
  --metrics /tmp/rtl_obfuscation_project/metrics.json \
  --top t018_top \
  --category interface_instances \
  --category interface_ports \
  --category modports \
  --name-length 8
```

随后使用 `decrypt-project` 和 `scripts/formal_equivalence.py` 完成逐文件恢复及多文件
Yosys 等价验证。

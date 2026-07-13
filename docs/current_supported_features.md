# 当前支持的重命名功能与综合演示

本文只描述已经通过黑盒测试和 Yosys formal 的功能，不包含计划中尚未实现的类别。

## 1. 当前支持表

| CLI category | 当前支持内容 | 验收结果 | 当前边界 |
| --- | --- | ---: | --- |
| `signals` | module 内部、非 port 的 `VariableSymbol`/`NetSymbol`；源码可为 `logic`、`reg`、`wire`、`tri` | 7 entries / 24 tokens | 不含 port、interface member、subroutine argument、aggregate field |
| `parameters` | module value parameter 与普通 module localparam 的声明和普通表达式引用 | 4 / 10 | 不含 type parameter、type-dimension 引用、generate iteration parameter |
| `enum_values` | module 内 enum member 的声明和已绑定引用 | 3 / 8 | 不含 package/class enum 或跨文件引用 |
| `genvars` | 单个简单 generate-for 的声明、条件、步进和循环体索引 | 1 / 5 | 当前固定样例为 4 次展开；不含多个、嵌套 loop 和 generate block label |
| `functions` | module function 声明、普通调用；T009 另覆盖传统返回赋值 | 1 / 2 | 不含 extern、DPI、recursive、package/class function |
| `tasks` | module task 声明和普通 ordered call | 1 / 2 | 不含 extern、DPI、层次调用和命名实参 |
| `arguments` | module function/task 形式参数声明及 subroutine 内部引用 | 4 / 9 | ordered actual expressions 不改名；不含命名实参和 prototype |
| `instances` | 单个具名 module instance 的声明 | T012 fixture 1 / 1 | 不含层次引用、instance array、primitive/checker/interface instance |
| `generate_blocks` | module 直属、显式命名的 generate-for block label | 综合样例 1 / 1 | 不含层次引用、嵌套/conditional generate、implicit `genblkN` |

综合样例总计 22 个 mapping entries、61 个被改写 token。名称长度由 `--name-length` 控制，当前演示使用 8，允许值必须不小于 4。

正常使用时选择 `--category all`，一次解析并直接生成最终 RTL、单一混合 mapping 和全局 metrics。单 category 选项仍保留，作为定位某一类重命名问题的 debug 模式。

## 2. 演示输入

```text
gold: rtl_samples/11_supported_obfuscation.sv
top:  sample11_supported_obfuscation
```

module 名和 ports 当前不会改名，因此 formal 的 top 保持不变。

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
{"files": 1, "mapping_entries": 22, "modified_tokens": 61}
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
- metrics 直接统计原始 gold 到最终 gate 的全局效果；综合样例为 40/61 个有效代码行、22/22 个符号和 61/61 个 occurrences。
- 当前不支持 module/port 重命名，因此不能把 top 或外部接口名称的保留视为遗漏。

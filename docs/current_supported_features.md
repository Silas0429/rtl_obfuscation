# 当前支持的重命名功能与综合演示

本文只描述已经通过黑盒测试和 Yosys formal 的功能，不包含计划中尚未实现的类别。

## 1. 当前支持表

| CLI category | 当前支持内容 | 综合样例结果 | 当前边界 |
| --- | --- | ---: | --- |
| `signals` | module 内部、非 port 的 `VariableSymbol`/`NetSymbol`；源码可为 `logic`、`reg`、`wire`、`tri` | 7 entries / 24 tokens | 不含 port、interface member、subroutine argument、aggregate field |
| `parameters` | module value parameter 与普通 module localparam 的声明和普通表达式引用 | 4 / 10 | 不含 type parameter、type-dimension 引用、generate iteration parameter |
| `enum_values` | module 内 enum member 的声明和已绑定引用 | 3 / 8 | 不含 package/class enum 或跨文件引用 |
| `genvars` | 单个简单 generate-for 的声明、条件、步进和循环体索引 | 1 / 5 | 当前固定样例为 4 次展开；不含多个、嵌套 loop 和 generate block label |
| `functions` | module function 声明、普通调用；T009 另覆盖传统返回赋值 | 1 / 2 | 不含 extern、DPI、recursive、package/class function |
| `tasks` | module task 声明和普通 ordered call | 1 / 2 | 不含 extern、DPI、层次调用和命名实参 |
| `arguments` | module function/task 形式参数声明及 subroutine 内部引用 | 4 / 9 | ordered actual expressions 不改名；不含命名实参和 prototype |

综合样例总计 21 个 mapping entries、60 个被改写 token。名称长度由 `--name-length` 控制，当前演示使用 8，允许值必须不小于 4。

当前 CLI 一次只接受一个 category，因此“全部当前功能”通过 7 次串联生成；每阶段产生独立 mapping 和 metrics。恢复时必须严格逆序使用这些 mapping。

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
mkdir -p "$OUT"

CURRENT=rtl_samples/11_supported_obfuscation.sv
for CATEGORY in signals parameters enum_values genvars functions tasks arguments; do
    STAGE="$OUT/$CATEGORY"
    conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite encrypt \
      --input "$CURRENT" \
      --output "$STAGE/gate.sv" \
      --map "$STAGE/mapping.json" \
      --metrics "$STAGE/metrics.json" \
      --category "$CATEGORY" \
      --name-length 8 || exit 1
    CURRENT="$STAGE/gate.sv"
done
```

预期 7 行 stdout 的 `mapping_entries / modified_tokens` 依次为：

```text
signals      7 / 24
parameters   4 / 10
enum_values  3 / 8
genvars      1 / 5
functions    1 / 2
tasks        1 / 2
arguments    4 / 9
```

最终加密 RTL：

```text
/tmp/rtl_obfuscation_supported_demo/arguments/gate.sv
```

每阶段 mapping 和五项指标分别位于：

```text
/tmp/rtl_obfuscation_supported_demo/<category>/mapping.json
/tmp/rtl_obfuscation_supported_demo/<category>/metrics.json
```

例如查看 signals 阶段结果：

```sh
conda run -n rtl_obfuscation python -m json.tool \
  "$OUT/signals/mapping.json"
conda run -n rtl_obfuscation python -m json.tool \
  "$OUT/signals/metrics.json"
```

## 4. 前端检查和 Yosys formal

```sh
FINAL_GATE="$OUT/arguments/gate.sv"

conda run -n rtl_obfuscation python -c \
  'import pyslang; t=pyslang.syntax.SyntaxTree.fromFile("/tmp/rtl_obfuscation_supported_demo/arguments/gate.sv"); c=pyslang.ast.Compilation(); c.addSyntaxTree(t); raise SystemExit(any(d.isError() for d in c.getAllDiagnostics()))'

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
mkdir -p "$OUT/restored"
CURRENT="$OUT/arguments/gate.sv"

for CATEGORY in arguments tasks functions genvars enum_values parameters signals; do
    RESTORED="$OUT/restored/$CATEGORY.sv"
    conda run -n rtl_obfuscation python -m rtl_obfuscator.rewrite decrypt \
      --input "$CURRENT" \
      --output "$RESTORED" \
      --map "$OUT/$CATEGORY/mapping.json" || exit 1
    CURRENT="$RESTORED"
done

cmp -s rtl_samples/11_supported_obfuscation.sv "$CURRENT"
echo $?
```

最后输出 `0` 表示恢复文件与原始 SystemVerilog 文件字节完全一致。

## 6. 结果解释

- final gate 与 gold 的功能一致性由 Yosys formal 证明。
- mapping 提供每一阶段的双向名称关系和 source ranges。
- metrics 是每一阶段独立统计，不是 7 阶段的合并指标。
- 当前不支持 module/port 重命名，因此不能把 top 或外部接口名称的保留视为遗漏。

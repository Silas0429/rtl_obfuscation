`ifndef T095_ASSERTS_H
`define T095_ASSERTS_H

`define PRIM_STRINGIFY(__x) `"__x`"

`define ASSERT_FATAL(__name)                                                    \
  $fatal(1, "%0s:%0d %0s", `__FILE__, `__LINE__, `PRIM_STRINGIFY(__name));

`define ASSERT_ERROR(__name)                                                    \
`ifdef T095_USE_ERROR                                                           \
  `ASSERT_FATAL(__name)                                                         \
`else                                                                           \
  $error("%0s:%0d %0s", `__FILE__, `__LINE__, `PRIM_STRINGIFY(__name));         \
`endif

`define ASSERT_FINAL(__name, __prop)                                            \
  final begin                                                                   \
    __name: assert (__prop)                                                     \
      else begin                                                                \
        `ASSERT_ERROR(__name)                                                   \
      end                                                                       \
  end

`define ASSERT_AT_RESET(__name, __prop, __rst = `ASSERT_DEFAULT_RST)            \
`ifdef T095_USE_ALT                                                             \
  __name: assert property (@(posedge __rst) (__prop))                          \
    else begin `ASSERT_FATAL(__name) end                                       \
`else                                                                           \
  `T095_UNKNOWN_INACTIVE(__name)                                                \
`endif

`define ASSERT_KNOWN_IF(__name, __sig, __clk = `ASSERT_DEFAULT_CLK)             \
  `ASSERT_FINAL(__name``KnownEnable, !$isunknown(__sig))

`endif

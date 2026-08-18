`include "asserts.h"

module t095_top(
    input logic t095_clk,
    input logic t095_rst,
    input logic in_a,
    output logic out_y
);
    logic signal_a;
    assign signal_a = in_a;
    `ASSERT_FINAL(t095_final, signal_a == in_a)
    `ASSERT_AT_RESET(t095_reset, signal_a == in_a)
    `ASSERT_KNOWN_IF(t095_known, signal_a, t095_clk)
    assign out_y = signal_a;
endmodule

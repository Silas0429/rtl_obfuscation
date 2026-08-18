`include "stl_gmacro.h"
`ifdef T091_ENABLE
`timescale 1ns/1ps
`endif

module t091_top(input logic in_a, output logic out_y);
  logic signal_a;
  assign signal_a = in_a;
  assign out_y = signal_a ^ 1'b1;
endmodule

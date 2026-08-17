module t088_child(input wire in_a, output wire out_y);
  `define T088_HEADER_IN_MODULE
  `include "../include/internal.vh"
  assign out_y = in_a ^ header_wire;
endmodule

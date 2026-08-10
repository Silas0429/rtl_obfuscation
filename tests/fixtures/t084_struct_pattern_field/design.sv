module t084_top (
  input  logic data_i,
  output logic data_o
);
  typedef struct packed {
    logic lhs;
    logic rhs;
  } pair_t;

  pair_t pair;
`ifdef T084_NAMED_PATTERN
  always_comb pair = '{rhs: data_i, lhs: 1'b0};
`else
  always_comb pair = {1'b0, data_i};
`endif
  assign data_o = pair.lhs ^ pair.rhs;
endmodule

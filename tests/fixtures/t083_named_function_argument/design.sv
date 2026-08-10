module t083_top (
  input  logic data_i,
  output logic data_o
);
  function automatic logic choose(input logic lhs, input logic rhs);
    choose = lhs ^ rhs;
  endfunction

  logic base;
  assign base = data_i;

`ifdef T083_NAMED_ARGUMENT
  assign data_o = choose(.rhs(base), .lhs(1'b0));
`else
  assign data_o = choose(1'b0, base);
`endif
endmodule

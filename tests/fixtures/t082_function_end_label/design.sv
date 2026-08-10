module t082_top (
  input  logic data_i,
  output logic data_o
);
  function automatic logic passthrough(input logic value);
    passthrough = value;
  endfunction

  logic base;
  assign base = passthrough(data_i);

`ifdef T082_LABEL_CLOSURE
  function automatic logic invert(input logic value);
    invert = ~value;
  endfunction : invert
  assign data_o = invert(base);
`else
  assign data_o = ~base;
`endif
endmodule

module t080_expression_sized_cast (
  input  logic [5:0] addr_i,
  output logic       hit_o
);
  localparam int unsigned RomSize = 20;

  assign hit_o = addr_i < $clog2(RomSize)'(RomSize);
endmodule

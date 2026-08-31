module t118_top (
    input  logic [DATA_BITS-1:0] in_data,
    input  logic [ADDR_BITS-1:0] in_addr,
    output logic [DATA_BITS-1:0] out_data
);
  logic [DATA_BITS-1:0] selected_data;

  assign selected_data = in_data ^ {{(DATA_BITS-ADDR_BITS){1'b0}}, in_addr};
  assign out_data = (SIMPLE_RR == 2'b00) ? selected_data : '0;
endmodule

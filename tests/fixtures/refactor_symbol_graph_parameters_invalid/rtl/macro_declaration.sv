`define DECLARE_LOCALPARAM(name) localparam int name = 2

module macro_parameter_declaration;
    `DECLARE_LOCALPARAM(MACRO_WIDTH);
    logic [MACRO_WIDTH-1:0] payload;
endmodule

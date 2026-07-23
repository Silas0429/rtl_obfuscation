`define PARAMETER_REF(name) name

module macro_parameter_reference #(
    parameter int WIDTH = 2
);
    logic [`PARAMETER_REF(WIDTH)-1:0] payload;
endmodule

module t071_sibling (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] sibling_mix;

    assign sibling_mix = data_i ^ 8'h5a;
    assign data_o = sibling_mix;
endmodule

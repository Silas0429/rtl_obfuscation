module t073_sibling (
    input  logic data_i,
    output logic data_o
);
    logic sibling_mix;

    assign sibling_mix = data_i ^ 1'b1;
    assign data_o = sibling_mix;
endmodule

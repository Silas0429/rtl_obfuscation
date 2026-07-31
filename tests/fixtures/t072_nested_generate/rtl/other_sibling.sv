module t072_other_sibling (
    input  logic data_i,
    output logic data_o
);
    logic other_mix;

    assign other_mix = data_i ^ 1'b1;
    assign data_o = other_mix;
endmodule

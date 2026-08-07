module t075_sibling (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] sibling_state;

    assign sibling_state = ~data_i;
    assign data_o = sibling_state;
endmodule

module t100_clean (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] clean_state;

    assign clean_state = data_i ^ 8'h3c;
    assign data_o = clean_state;
endmodule

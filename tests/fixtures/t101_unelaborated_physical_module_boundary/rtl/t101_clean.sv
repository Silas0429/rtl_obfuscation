module t101_clean (
    input  logic data_i,
    output logic data_o
);
    logic clean_state;

    assign clean_state = data_i ^ 1'b1;
    assign data_o = clean_state;
endmodule

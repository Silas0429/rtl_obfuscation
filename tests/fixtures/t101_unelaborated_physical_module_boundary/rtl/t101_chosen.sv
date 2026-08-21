module t101_chosen (
    input  logic data_i,
    output logic data_o
);
    logic chosen_state;

    assign chosen_state = data_i;
    assign data_o = chosen_state;
endmodule

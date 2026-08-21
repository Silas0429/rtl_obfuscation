module t101_candidate (
    input  logic data_i,
    output logic data_o
);
    logic candidate_state;

    assign candidate_state = data_i;
    assign data_o = candidate_state;
endmodule

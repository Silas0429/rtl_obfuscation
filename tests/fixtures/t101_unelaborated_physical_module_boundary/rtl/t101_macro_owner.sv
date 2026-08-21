module t101_macro_owner (
    input  logic data_i,
    output logic data_o
);
    logic macro_state;

    `define T101_ASSIGN_STATE(VALUE, TARGET) \
        assign TARGET = VALUE;

    `T101_ASSIGN_STATE(data_i, macro_state)
    assign data_o = macro_state;
endmodule

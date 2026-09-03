module t133_fast_direct_variables_formal (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    word_t      formal_typed_signal;
    logic [7:0] formal_selected_signal;

    assign formal_typed_signal = data_i;
    assign formal_selected_signal = {
        formal_typed_signal[3:0],
        formal_typed_signal[7:4]
    };
    assign data_o = formal_selected_signal ^ 8'h3;
endmodule

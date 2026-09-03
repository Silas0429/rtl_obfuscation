`define T133_MACRO_SIGNAL macro_signal

module t133_child (
    input logic same_label
);
endmodule

module t133_fast_direct_variables (
    input  logic       select_i,
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0]       packed_signal;
    logic [7:0]       array_signal [0:1];
    word_t            typed_signal;
    pair_t            aggregate_signal;
    logic             same_label;
    logic             macro_signal;

    assign packed_signal = data_i;
    assign array_signal[0] = packed_signal;
    assign array_signal[1] = {packed_signal[3:0], packed_signal[7:4]};
    assign typed_signal = array_signal[select_i];
    assign aggregate_signal.low = typed_signal[3:0];
    assign aggregate_signal.high = typed_signal[7:4];
    assign same_label = ^typed_signal;
    assign macro_signal = data_i[0];

    t133_child child_i (.same_label(same_label));

    if (1) begin : generated_scope
        logic generated_local;
        assign generated_local = typed_signal[0];
    end

    function automatic logic nested_value(input logic value_i);
        logic function_local;
        function_local = value_i;
        nested_value = function_local;
    endfunction

    assign data_o = array_signal[select_i]
                  ^ typed_signal
                  ^ {aggregate_signal.high, aggregate_signal.low}
                  ^ {7'b0, same_label ^ `T133_MACRO_SIGNAL
                            ^ nested_value(data_i[1])};
endmodule

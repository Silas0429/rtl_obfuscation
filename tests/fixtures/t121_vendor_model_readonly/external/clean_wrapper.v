module t121_clean_wrapper (
    input  wire [7:0] data_i,
    output wire [7:0] data_o
);
    wire [7:0] wrapper_signal;
    t121_provider external_provider (
        .data_i(data_i),
        .data_o(wrapper_signal)
    );
    assign data_o = wrapper_signal;
endmodule

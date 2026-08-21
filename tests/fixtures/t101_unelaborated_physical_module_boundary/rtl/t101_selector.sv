module t101_selector #(
    parameter bit USE_CANDIDATE = 1'b0
) (
    input  logic data_i,
    output logic data_o
);
    generate
        if (USE_CANDIDATE) begin : g_candidate
            t101_candidate u_candidate (
                .data_i(data_i),
                .data_o(data_o)
            );
        end
        else begin : g_chosen
            t101_chosen u_chosen (
                .data_i(data_i),
                .data_o(data_o)
            );
        end
    endgenerate
endmodule

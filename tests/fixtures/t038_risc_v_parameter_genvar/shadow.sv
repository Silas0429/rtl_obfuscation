module t038_shadow #(
    parameter int k = 2
) (
    output logic [1:0] out
);
    generate
        for (genvar k = 0; k < 2; k++) begin : g_k
            logic [k:0] lane;
            assign lane = '0;
            assign out[k] = lane[0];
        end
    endgenerate
endmodule

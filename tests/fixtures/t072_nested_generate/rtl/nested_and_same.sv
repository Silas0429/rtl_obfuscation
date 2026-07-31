module t072_nested_owner (
    input  logic data_i,
    output logic data_o
);
    logic owner_passthrough;

    for (genvar i = 0; i < 2; i++) begin : g_outer
        for (genvar i = 0; i < 2; i++) begin : g_inner
            logic lane_nested;
            assign lane_nested = data_i;
        end
    end

    assign owner_passthrough = data_i;
    assign data_o = owner_passthrough;
endmodule

module t072_same_file_sibling (
    input  logic data_i,
    output logic data_o
);
    logic same_mix;

    assign same_mix = ~data_i;
    assign data_o = same_mix;
endmodule

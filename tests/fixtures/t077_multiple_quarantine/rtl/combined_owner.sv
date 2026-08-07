module t077_combined_owner (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] target_o;
    logic [7:0] nested_mix;

    t077_parameter_target u_target (
        .data_i(data_i),
        .data_o(target_o)
    );
    defparam u_target.WIDTH = 8;

    for (genvar outer = 0; outer < 2; outer++) begin : g_outer
        for (genvar inner = 0; inner < 1; inner++) begin : g_inner
            logic lane_value;
            assign lane_value = data_i[outer];
        end
    end

    assign nested_mix = data_i ^ 8'h0f;
    assign data_o = target_o ^ nested_mix;
endmodule

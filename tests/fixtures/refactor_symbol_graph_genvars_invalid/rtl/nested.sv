module nested_genvar;
    for (genvar i = 0; i < 2; i++) begin : g_outer
        for (genvar i = 0; i < 2; i++) begin : g_inner
            logic [i:0] lane_nested;
        end
    end
endmodule

module genvar_reuse #(
    parameter int WIDTH = 2
);
    genvar j;
    for (j = 0; j < WIDTH; j = j + 1) begin : g_first
        logic [j:0] lane_first;
    end
    for (j = 0; j < WIDTH; j = j + 1) begin : g_second
        logic [j:0] lane_second;
    end
endmodule

module genvar_shadow #(
    parameter int k = 2
);
    for (genvar k = 0; k < 2; k++) begin : g_shadow
        logic [k:0] lane_shadow;
    end
endmodule

module genvar_top;
    genvar_reuse u_reuse();
    genvar_shadow u_shadow();
endmodule

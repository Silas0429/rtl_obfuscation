module t131_external_top (
    input  logic clk_i,
    input  logic data_i,
    output logic data_o
);
    generate
        if (0) begin : inactive_targets
            t131_unused_a u_a (
                .clk_i  (clk_i),
                .data_i (data_i),
                .data_o ()
            );
            t131_unused_b u_b (
                .clk_i  (clk_i),
                .data_i (data_i),
                .data_o ()
            );
            t131_shadowed u_shadowed (
                .clk_i  (clk_i),
                .data_i (data_i),
                .data_o ()
            );
        end
    endgenerate

    assign data_o = data_i;
endmodule

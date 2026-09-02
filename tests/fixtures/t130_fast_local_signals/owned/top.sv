module t130_top (
    input  logic clk_i,
    input  logic left_i,
    input  logic right_i,
    output logic data_o
);
    logic left_value;
    logic right_value;
    wire  combined;

    t130_leaf_a u_left (
        .clk_i(clk_i),
        .data_i(left_i),
        .data_o(left_value)
    );

    t130_leaf_b u_right (
        .clk_i(clk_i),
        .data_i(right_i),
        .data_o(right_value)
    );

    assign combined = left_value ^ right_value;
    assign data_o = combined ^ 1'b0;
endmodule

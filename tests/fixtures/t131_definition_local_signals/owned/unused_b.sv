module t131_unused_b (
    input  logic clk_i,
    input  logic data_i,
    output logic data_o
);
    logic state;

    always_ff @(posedge clk_i)
        state <= state ^ data_i;

    assign data_o = state;
endmodule

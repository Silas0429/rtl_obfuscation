module t131_unused_a (
    input  logic clk_i,
    input  logic data_i,
    output logic data_o
);
    logic state;
    logic next_state;

    always_comb
        next_state = state ^ data_i;

    always_ff @(posedge clk_i)
        state <= next_state;

    assign data_o = state;
endmodule

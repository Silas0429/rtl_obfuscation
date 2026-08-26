module formal_top (
    input  logic clk,
    input  logic in_a,
    output logic out_y
);
    logic state;
    always_ff @(posedge clk)
        state <= in_a;
    assign out_y = state;
endmodule

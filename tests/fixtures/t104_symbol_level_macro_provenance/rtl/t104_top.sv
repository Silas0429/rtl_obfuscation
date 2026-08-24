module t104_top (
    input logic clk,
    output logic result
);
    t104_core u_core (
        .clk(clk),
        .result(result)
    );
endmodule

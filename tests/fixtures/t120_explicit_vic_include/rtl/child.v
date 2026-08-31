module t120_child #(
    parameter WIDTH = 8
) (
    input  logic [WIDTH-1:0] i,
    output logic [WIDTH-1:0] o
);
    logic [WIDTH-1:0] child_signal;
    assign child_signal = i ^ {{(WIDTH-1){1'b0}}, 1'b1};
    assign o = child_signal;
endmodule

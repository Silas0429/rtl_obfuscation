module t121_child (
    input  wire [7:0] data_i,
    output wire [7:0] data_o
);
    wire [7:0] child_signal;
    assign child_signal = data_i ^ 8'h3c;
    assign data_o = child_signal;
endmodule

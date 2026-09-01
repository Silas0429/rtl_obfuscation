module t125_child (
    input logic in_i,
    output logic out_o
);
    logic child_signal;
    assign child_signal = in_i;
    assign out_o = child_signal;
endmodule

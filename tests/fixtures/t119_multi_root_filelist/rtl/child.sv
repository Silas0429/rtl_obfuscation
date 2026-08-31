module t119_child (
    input  logic i,
    output logic o
);
    logic child_signal;
    assign child_signal = i ^ 1'b1;
    assign o = child_signal;
endmodule

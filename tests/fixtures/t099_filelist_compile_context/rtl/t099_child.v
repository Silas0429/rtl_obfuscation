module t099_child (
    input logic in_a,
    output logic out_y
);
    logic [`T099_WIDTH-1:0] child_signal;
    assign child_signal = in_a;
    assign out_y = child_signal;
endmodule

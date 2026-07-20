module t034_unused (
    input  logic d,
    output logic q
);
    logic unused_state;

    assign unused_state = d;
    assign q = unused_state;
endmodule

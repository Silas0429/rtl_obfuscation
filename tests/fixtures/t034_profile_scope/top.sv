module t034_top (
    input  logic data,
    output logic q
);
    logic top_state;

    t034_child u_child (
        .data(data),
        .q(top_state)
    );

    assign q = top_state;
endmodule

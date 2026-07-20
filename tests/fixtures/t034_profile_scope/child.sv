module t034_child (
    input  logic data,
    output logic q
);
    logic child_state;
    logic child_signal;

    assign child_signal = ~data;

    always_comb begin
        child_state = child_signal;
        q = child_state;
    end
endmodule

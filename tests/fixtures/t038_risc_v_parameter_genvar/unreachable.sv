module t038_unreachable #(
    parameter int HIDDEN_WIDTH = 3
) (
    input logic [HIDDEN_WIDTH-1:0] hidden_i
);
    logic [HIDDEN_WIDTH-1:0] hidden_state;
    assign hidden_state = hidden_i;
endmodule

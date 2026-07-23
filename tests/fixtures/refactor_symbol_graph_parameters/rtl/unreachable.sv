module parameter_unreachable #(
    parameter int HIDDEN_WIDTH = 3
);
    localparam int HIDDEN_LOCAL = HIDDEN_WIDTH + 1;
    logic [HIDDEN_LOCAL-1:0] hidden_value;
endmodule

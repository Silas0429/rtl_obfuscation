module project_top (
    input  logic                    top_clk,
    input  logic                    top_reset_n,
    input  logic                    top_valid_i,
    input  logic [`T027_WIDTH-1:0]  top_data_i,
    output logic                    top_valid_o,
    output logic [`T027_WIDTH-1:0]  top_data_o
);
    internal_if top_bus(.clk(top_clk));
    logic top_signal;
    logic child_valid;
    logic [`T027_WIDTH-1:0] child_data;

    assign top_bus.if_request = top_valid_i;
    assign top_bus.if_data = top_data_i;

    project_child u_child (
        .clk           (top_clk),
        .reset_n       (top_reset_n),
        .child_valid_i (top_bus.if_request),
        .child_data_i  (top_bus.if_data),
        .child_valid_o (child_valid),
        .child_data_o  (child_data)
    );

    assign top_bus.if_acknowledge = child_valid;
    assign top_signal = top_bus.if_acknowledge;
    assign top_valid_o = top_signal;
    assign top_data_o = child_data;
endmodule

module same_file_unused (
    input  logic unused_i,
    output logic unused_o
);
    logic same_file_secret;
    assign same_file_secret = unused_i;
    assign unused_o = same_file_secret;
endmodule

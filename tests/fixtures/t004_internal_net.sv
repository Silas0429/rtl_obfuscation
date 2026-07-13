// T004 fixture: one internal net and one net port.
module t004_internal_net (
    input  logic input_a,
    input  logic input_b,
    output wire  output_y
);

    wire combined_net;

    assign combined_net = input_a & input_b;
    assign output_y = combined_net;

endmodule

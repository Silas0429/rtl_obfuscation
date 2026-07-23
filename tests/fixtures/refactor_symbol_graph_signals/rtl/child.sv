module child (
    input logic in_i,
    output logic out_o
);
    logic state;
    wire state_net;
    assign state = in_i;
    assign state_net = state;
    assign out_o = state_net;
endmodule

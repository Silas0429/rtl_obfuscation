module t033_top #(
    parameter int TOP_WIDTH = 8
) (
    input  logic [TOP_WIDTH-1:0] data,
    output logic [TOP_WIDTH-1:0] q
);
    localparam int TOP_LOCAL = TOP_WIDTH + 1;
    logic [TOP_WIDTH-1:0] top_signal;
    t033_shared_t top_shared;
    t033_bus_if bus();
    t033_child #(.WIDTH(TOP_WIDTH)) u_child (
        .data(data),
        .q(q),
        .bus(bus)
    );
    assign top_signal = data;
    assign top_shared.valid = bus.valid;
endmodule

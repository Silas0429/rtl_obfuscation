module fifo_top #(
    parameter int DATA_WIDTH = 8,
    parameter int DEPTH = 4,
    parameter int ADDR_WIDTH = 2
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  push,
    input  logic                  pop,
    input  logic [DATA_WIDTH-1:0] data,
    output logic [DATA_WIDTH-1:0] q,
    output logic                  full,
    output logic                  empty,
    output logic                  valid
);
    // Keep the external top-level ports unchanged while using fifo_bus as the
    // internal interface bundle between the top-level adapter and FIFO logic.
    fifo_if fifo_bus (
        .clk(clk),
        .rst_n(rst_n)
    );

    assign fifo_bus.push = push;
    assign fifo_bus.pop = pop;
    assign fifo_bus.data = data;
    assign q = fifo_bus.q;
    assign full = fifo_bus.full;
    assign empty = fifo_bus.empty;
    assign valid = fifo_bus.valid;

    fifo_ctrl #(
        .DATA_WIDTH(DATA_WIDTH),
        .DEPTH(DEPTH),
        .ADDR_WIDTH(ADDR_WIDTH)
    ) u_fifo (
        .clk(clk),
        .rst_n(rst_n),
        .push(fifo_bus.push),
        .pop(fifo_bus.pop),
        .data(fifo_bus.data),
        .q(fifo_bus.q),
        .full(fifo_bus.full),
        .empty(fifo_bus.empty),
        .valid(fifo_bus.valid)
    );
endmodule

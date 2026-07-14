interface t017_bus_if (
    input  logic clk,
    input  logic rst_n
);
    logic [7:0] data;
    logic        valid;
    logic        ready;
endinterface

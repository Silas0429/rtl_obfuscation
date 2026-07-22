interface fifo_if (
    input logic clk,
    input logic rst_n
);
    logic        push;
    logic        pop;
    logic [7:0]  data;
    logic [7:0]  q;
    logic        full;
    logic        empty;
    logic        valid;

    modport producer (
        output push,
        output pop,
        output data,
        input  q,
        input  full,
        input  empty,
        input  valid
    );

    modport consumer (
        input  clk,
        input  rst_n,
        input  push,
        input  pop,
        input  data,
        output q,
        output full,
        output empty,
        output valid
    );
endinterface

interface t018_bus_if (
    input  logic clk,
    input  logic rst_n
);
    logic [7:0] data;
    logic        valid;
    logic        ready;

    modport master (
        output data,
        output valid,
        input  ready
    );

    modport slave (
        input  data,
        input  valid,
        output ready
    );
endinterface

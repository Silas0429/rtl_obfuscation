`include "common.svh"

interface internal_if(input logic clk);
    logic if_request;
    logic if_acknowledge;
    logic [`T027_WIDTH-1:0] if_data;

    modport producer(output if_request, if_data, input if_acknowledge);
    modport consumer(input if_request, if_data, output if_acknowledge);
endinterface

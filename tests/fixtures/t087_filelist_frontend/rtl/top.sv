`include "common.svh"

module top (
    input logic [`COMMON_WIDTH-1:0] in_data,
    output logic [`COMMON_WIDTH-1:0] out_data
);
    child u_child(.in_data(in_data), .out_data(out_data));
endmodule

`include "common.svh"

module child (
    input logic [`COMMON_WIDTH-1:0] in_data,
    output data_t out_data
);
    assign out_data = in_data;
endmodule

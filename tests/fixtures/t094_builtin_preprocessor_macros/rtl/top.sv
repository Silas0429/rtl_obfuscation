`ifdef __FILE__
`define T094_BUILTIN_BRANCH_WIDTH 1
`else
`define T094_BUILTIN_BRANCH_WIDTH T094_UNKNOWN_BRANCH_WIDTH
`endif

module t094_top (
    input logic [`T094_BUILTIN_BRANCH_WIDTH-1:0] data_i,
    output logic [`T094_BUILTIN_BRANCH_WIDTH-1:0] data_o
);
    localparam integer T094_SOURCE_LINE = `__LINE__;
    localparam string T094_SOURCE_FILE = `__FILE__;
    assign data_o = data_i;
endmodule

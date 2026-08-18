module t094_unknown (
    input logic [`T094_UNKNOWN_WIDTH-1:0] data_i,
    output logic data_o
);
    assign data_o = data_i[0];
endmodule

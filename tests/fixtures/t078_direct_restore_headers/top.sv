module t078_header_top (
    input  logic data_i,
    output logic data_o
);
    logic data_q;
    assign data_q = data_i;
    assign data_o = data_q;
endmodule

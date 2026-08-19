module t098_top (
    input logic [`T098_WIDTH-1:0] in_data,
    output t098_pkg::t098_data_t out_data
);
    t098_if link();
    t098_child u_child(.in_data(in_data), .out_data(out_data));
endmodule

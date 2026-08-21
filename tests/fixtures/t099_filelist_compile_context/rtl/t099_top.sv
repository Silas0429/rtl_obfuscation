module t099_top (
    input logic in_a,
    output logic out_y
);
    logic top_data;
    t099_child u_child(.in_a(in_a), .out_y(top_data));
    assign out_y = top_data;

`ifndef YOSYS
    t099_pkg::t099_data_t package_data;
    t099_if link();
    assign package_data = top_data;
    assign link.payload = package_data;
`endif
endmodule

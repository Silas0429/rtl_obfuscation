module t017_top (
    input  logic clk,
    input  logic rst_n,
    output logic [7:0] data_out,
    output logic        valid_out
);
    t017_bus_if u_bus (
        .clk(clk),
        .rst_n(rst_n)
    );

    t017_child u_child (
        .bus_inst(u_bus)
    );

    assign data_out = u_bus.data;
    assign valid_out = u_bus.valid;
endmodule

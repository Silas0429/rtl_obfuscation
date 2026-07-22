module t038_top #(
    parameter int TOP_WIDTH = 4,
    parameter int TOP_UNUSED = 7
) (
    input  logic [TOP_WIDTH-1:0] data_i,
    output logic [TOP_WIDTH-1:0] data_o
);
    localparam int TOP_LOCAL = TOP_WIDTH + 1;

    t038_child #(
        .WIDTH(TOP_WIDTH)
    ) u_child (
        .data_i(data_i),
        .data_o(data_o)
    );

    t038_shadow u_shadow (.out(data_o[1:0]));
endmodule

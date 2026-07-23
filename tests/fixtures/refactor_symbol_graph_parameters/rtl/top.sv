module parameter_top #(
    parameter int WIDTH = 4,
    parameter int TOP_DEPTH = 2,
    parameter int TOP_UNUSED = 7
) (
    input  logic [WIDTH-1:0] data_i,
    output logic [WIDTH-1:0] data_o
);
    localparam int TOP_LOCAL = WIDTH + TOP_DEPTH;

    parameter_child #(
        .WIDTH(WIDTH),
        .DEPTH(TOP_DEPTH)
    ) u_child (
        .data_i(data_i),
        .data_o(data_o)
    );

    parameter_shadow #(
        .WIDTH(WIDTH)
    ) u_shadow();
endmodule

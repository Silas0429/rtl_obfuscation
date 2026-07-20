module t032_top #(
    parameter integer DATA_WIDTH = 8
) (
    input  logic [DATA_WIDTH-1:0] data_i,
    output logic [DATA_WIDTH-1:0] data_o
);
    localparam integer CHILD_WIDTH = DATA_WIDTH + 0;
    localparam integer CHILD_DEPTH = DATA_WIDTH / 2;
    logic [DATA_WIDTH-1:0] child_data;

    t032_child #(
        .WIDTH(CHILD_WIDTH),
        .DEPTH(CHILD_DEPTH)
    ) u_child (
        .data_i(data_i),
        .data_o(child_data)
    );

    assign data_o = child_data;
endmodule

module t079_child #(
    parameter logic COMPRESSED = 1'b0,
    parameter logic ALIGN = COMPRESSED,
    parameter int WIDTH = 4,
    parameter int DOUBLE_WIDTH = WIDTH * 2
) (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    assign data_o = (ALIGN || COMPRESSED) ? data_i : (data_i ^ DOUBLE_WIDTH);
endmodule

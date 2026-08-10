module t079_sibling #(
    parameter int WIDTH = 3,
    parameter int DERIVED = WIDTH + 1
) (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    assign data_o = data_i ^ DERIVED;
endmodule

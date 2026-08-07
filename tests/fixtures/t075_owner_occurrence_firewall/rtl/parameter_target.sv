module t075_parameter_target #(
    parameter int WIDTH = 8
) (
    input  logic [WIDTH-1:0] data_i,
    output logic [WIDTH-1:0] data_o
);
    assign data_o = data_i;
endmodule

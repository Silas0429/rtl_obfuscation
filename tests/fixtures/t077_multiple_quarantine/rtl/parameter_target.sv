module t077_parameter_target #(
    parameter int WIDTH = 8
) (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] target_state;

    assign target_state = data_i ^ WIDTH;
    assign data_o = target_state;
endmodule

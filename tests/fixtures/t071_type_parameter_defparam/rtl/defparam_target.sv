module t071_defparam_target #(
    parameter int WIDTH = 8
) (
    input  logic [7:0] data_i,
    output logic [7:0] data_o
);
    logic [7:0] target_hold;

    assign target_hold = data_i ^ WIDTH;
    assign data_o = target_hold;
endmodule

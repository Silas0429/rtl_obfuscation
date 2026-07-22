module t038_type_parameter #(
    parameter type T = logic
) (
    input T data_i,
    output T data_o
);
    assign data_o = data_i;
endmodule

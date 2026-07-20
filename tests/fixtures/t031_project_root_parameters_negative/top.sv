module parameter_type_negative #(
    parameter type T = logic [7:0]
) (
    input logic clk
);
    T value;
    always_comb value = '0;
endmodule

// T005 fixture: one value parameter used in an expression.
module t005_value_parameter #(
    parameter logic INVERT = 1'b1
) (
    input  logic input_a,
    output logic output_y
);

    logic selected_value;

    assign selected_value = input_a ^ INVERT;
    assign output_y = selected_value;

endmodule

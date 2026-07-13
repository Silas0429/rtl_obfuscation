// T006 fixture: one type parameter used by an internal signal.
module t006_type_parameter #(
    parameter type DATA_T = logic [7:0]
) (
    input  logic [7:0] input_data,
    output logic [7:0] output_data
);

    DATA_T internal_data;

    assign internal_data = input_data;
    assign output_data = internal_data;

endmodule

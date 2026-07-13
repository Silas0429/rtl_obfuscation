module t009_function_argument (
    input  logic [3:0] input_data,
    output logic [3:0] output_data
);

    function automatic logic [3:0] transform_value(
        input logic [3:0] function_data
    );
        transform_value = function_data ^ 4'ha;
    endfunction

    assign output_data = transform_value(input_data);

endmodule

// Sample 09: automatic function, typed argument, and local loop variable.
module sample09_function_call (
    input  logic [7:0] input_data,
    output logic [3:0] population_count
);

    logic [3:0] count_result;

    function automatic logic [3:0] count_ones(input logic [7:0] function_data);
        logic [3:0] accumulated_count;

        accumulated_count = '0;
        for (int unsigned loop_index = 0; loop_index < 8; loop_index++) begin
            accumulated_count += function_data[loop_index];
        end
        return accumulated_count;
    endfunction

    assign count_result = count_ones(input_data);
    assign population_count = count_result;

endmodule

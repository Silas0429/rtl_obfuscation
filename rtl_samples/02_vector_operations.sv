// Sample 02: packed vectors, bit/part select, and concatenation.
module sample02_vector_operations (
    input  logic [7:0] input_data,
    output logic [7:0] output_data
);

    logic [3:0] lower_nibble;
    logic [3:0] upper_nibble;

    assign lower_nibble = input_data[3:0];
    assign upper_nibble = input_data[7:4];
    assign output_data = {lower_nibble, upper_nibble};

endmodule

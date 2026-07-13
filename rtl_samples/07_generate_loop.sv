// Sample 07: typed parameter and a named generate-for block.
module sample07_generate_loop #(
    parameter int unsigned WIDTH = 4
) (
    input  logic [WIDTH-1:0] input_data,
    input  logic             mask_enable,
    output logic [WIDTH-1:0] output_data
);

    logic [WIDTH-1:0] masked_data;

    for (genvar bit_index = 0; bit_index < WIDTH; bit_index++) begin : generate_mask
        assign masked_data[bit_index] = input_data[bit_index] & mask_enable;
    end

    assign output_data = masked_data;

endmodule
